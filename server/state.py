import json
import os
import uuid

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
