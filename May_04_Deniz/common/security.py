import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import protocol

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - optional dependency
    Fernet = None
    InvalidToken = Exception


DEFAULT_SECURED_EVENTS = {
    "exam_policy",
    "policy_update",
    "session_state",
    "incident_report",
    "kill_process",
    "pause_exam",
    "resume_exam",
}

DEFAULT_ENCRYPTED_EVENTS = {
    "exam_policy",
    "policy_update",
    "session_state",
    "incident_report",
    "kill_process",
    "pause_exam",
    "resume_exam",
}


def encryption_available() -> bool:
    return Fernet is not None


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _derive_key(password: str, session_uuid: str, label: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        f"{label}:{session_uuid}".encode("utf-8"),
        120_000,
        dklen=32,
    )


def _ts_to_epoch(value: str) -> float:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


@dataclass
class SessionSecurityContext:
    session_uuid: str
    password: str
    replay_window_seconds: int = 120
    secure_events: set[str] = field(default_factory=lambda: set(DEFAULT_SECURED_EVENTS))
    encrypt_events: set[str] = field(default_factory=lambda: set(DEFAULT_ENCRYPTED_EVENTS))
    signing_key: bytes = field(init=False)
    fernet: object | None = field(init=False)
    seen_nonces: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.signing_key = _derive_key(self.password, self.session_uuid, "signing")
        if Fernet is None:
            self.fernet = None
        else:
            encryption_key = base64.urlsafe_b64encode(
                _derive_key(self.password, self.session_uuid, "encryption")
            )
            self.fernet = Fernet(encryption_key)

    def should_secure(self, event: str) -> bool:
        return event in self.secure_events

    def should_encrypt(self, event: str) -> bool:
        return event in self.encrypt_events and self.fernet is not None

    def protect(self, event: str, payload: dict) -> dict:
        payload_json = _canonical(payload)
        timestamp = protocol.now_iso()
        nonce = secrets.token_hex(16)
        encrypted = self.should_encrypt(event)
        if encrypted:
            assert self.fernet is not None
            body = {"ciphertext": self.fernet.encrypt(payload_json).decode("utf-8")}
        else:
            body = {"payload": base64.urlsafe_b64encode(payload_json).decode("ascii")}

        signature_body = {
            "event": event,
            "timestamp": timestamp,
            "nonce": nonce,
            "encrypted": encrypted,
            **body,
        }
        signature = hmac.new(
            self.signing_key,
            _canonical(signature_body),
            hashlib.sha256,
        ).hexdigest()
        return {
            "_secured": True,
            "timestamp": timestamp,
            "nonce": nonce,
            "encrypted": encrypted,
            "signature": signature,
            **body,
        }

    def unprotect(self, event: str, envelope: dict) -> dict:
        if not isinstance(envelope, dict) or not envelope.get("_secured"):
            raise ValueError(f"missing secured envelope for event '{event}'")

        timestamp = str(envelope.get("timestamp", "")).strip()
        nonce = str(envelope.get("nonce", "")).strip()
        signature = str(envelope.get("signature", "")).strip()
        encrypted = bool(envelope.get("encrypted", False))

        if not timestamp or not nonce or not signature:
            raise ValueError("secured message missing timestamp, nonce, or signature")

        signature_body = {
            "event": event,
            "timestamp": timestamp,
            "nonce": nonce,
            "encrypted": encrypted,
        }
        if encrypted:
            signature_body["ciphertext"] = str(envelope.get("ciphertext", ""))
        else:
            signature_body["payload"] = str(envelope.get("payload", ""))

        expected_signature = hmac.new(
            self.signing_key,
            _canonical(signature_body),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("message signature mismatch")

        now = time.time()
        message_time = _ts_to_epoch(timestamp)
        if abs(now - message_time) > self.replay_window_seconds:
            raise ValueError("message timestamp outside replay window")

        self._prune_nonces(now)
        if nonce in self.seen_nonces:
            raise ValueError("replayed message nonce")
        self.seen_nonces[nonce] = message_time

        if encrypted:
            if self.fernet is None:
                raise ValueError("encrypted payload received but cryptography is unavailable")
            ciphertext = str(envelope.get("ciphertext", ""))
            try:
                payload_json = self.fernet.decrypt(ciphertext.encode("utf-8"))
            except InvalidToken as exc:
                raise ValueError("invalid encrypted payload") from exc
        else:
            encoded_payload = str(envelope.get("payload", ""))
            try:
                payload_json = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError("invalid signed payload") from exc

        try:
            payload = json.loads(payload_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("secured payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("secured payload must decode to a JSON object")
        return payload

    def _prune_nonces(self, now: float):
        cutoff = now - self.replay_window_seconds
        expired = [nonce for nonce, nonce_time in self.seen_nonces.items() if nonce_time < cutoff]
        for nonce in expired:
            self.seen_nonces.pop(nonce, None)


def build_session_context(session_uuid: str, password: str) -> SessionSecurityContext:
    return SessionSecurityContext(session_uuid=session_uuid, password=password)


def protect_wire_message(raw_message: str, context: SessionSecurityContext | None) -> str:
    event, data = protocol.decode(raw_message)
    if event == protocol.DECODE_ERROR or context is None or not context.should_secure(event):
        return raw_message
    return protocol.encode(event, context.protect(event, data))


def decode_wire_message(raw_message: str, context: SessionSecurityContext | None) -> tuple[str, dict]:
    event, data = protocol.decode(raw_message)
    if event == protocol.DECODE_ERROR:
        return event, data
    if context is None or not context.should_secure(event):
        return event, data
    try:
        return event, context.unprotect(event, data)
    except ValueError as exc:
        return protocol.DECODE_ERROR, {"reason": str(exc)}
