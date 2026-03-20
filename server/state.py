import json
import os

USERS_FILE = "data/server/server_users.json"
ALLOWED_USERS_FILE = "allowed_users.json"

class ServerState:
    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.users_db: dict[str, dict] = {}
        self.allowed_users: dict[str, str] = {}
        self.gui_process = None

    def load_users(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r") as f:
                    self.users_db = json.load(f)
                for user in self.users_db.values():
                    self.ensure_user_defaults(user)
            except Exception as e:
                print(f"[!] Failed to load {USERS_FILE}: {e}")
                self.users_db = {}
                
        if os.path.exists(ALLOWED_USERS_FILE):
            try:
                with open(ALLOWED_USERS_FILE, "r") as f:
                    self.allowed_users = json.load(f)
            except Exception as e:
                print(f"[!] Failed to load {ALLOWED_USERS_FILE}: {e}")
                self.allowed_users = {}

    def save_users(self):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        try:
            with open(USERS_FILE, "w") as f:
                json.dump(self.users_db, f, indent=2)
        except Exception as e:
            print(f"[!] Failed to save {USERS_FILE}: {e}")

    def ensure_user_defaults(self, user: dict):
        user.setdefault("time_spent_seconds", 0)
        user.setdefault("exam_started", False)
        user.setdefault("extra_time_seconds", 0)
        user.setdefault("banned", False)
        user.setdefault("kick_count", 0)
        user.setdefault("last_action", "")
        user.setdefault("computer_name", "")

    def is_valid_session_uuid(self, client_id: str) -> bool:
        return any(user.get("uuid") == client_id for user in self.users_db.values())

    def find_user_by_uuid(self, client_id: str):
        for login_id, user in self.users_db.items():
            if user.get("uuid") == client_id:
                return login_id, user
        return None, None

    def get_gui_process(self):
        process = self.gui_process
        if process and process.poll() is None:
            return process
        return None

    def resolve_user(self, target: str):
        if target in self.users_db:
            return target, self.users_db[target]

        login_id, user = self.find_user_by_uuid(target)
        if user:
            return login_id, user

        client_id, _ = self.resolve_client(target)
        if client_id:
            return self.find_user_by_uuid(client_id)

        return None, None

    def resolve_client(self, target: str):
        """
        Find a client by:
        1. Full UUID
        2. Short ID (first 8 chars)
        3. IP Address
        Returns (full_id, client_data) or (None, None)
        """
        # 1. Check Full ID
        if target in self.clients:
            return target, self.clients[target]

        # 2. Check Short ID and IP
        for cid, data in self.clients.items():
            if data["short_id"] == target or data["ip"] == target:
                return cid, data

        return None, None

state = ServerState()
