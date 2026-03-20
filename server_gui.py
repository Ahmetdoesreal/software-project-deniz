import json
import sys
import tkinter as tk
from datetime import datetime
from threading import Thread
from tkinter import messagebox, ttk


def _format_remaining(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.clients_data = {}
        self.tree_items = {}

        self.title("Server Monitor Dashboard")
        self.geometry("800x400")

        self._build_layout()
        self.after(1000, self.update_timers)

    def _build_layout(self):
        content = ttk.Frame(self)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_panel = ttk.Frame(content)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_tree_area(left_panel)
        self._build_log_area(left_panel)
        self._build_command_bar()
        self._build_stats_bar()
        self._build_action_panel(content)

    def _build_tree_area(self, parent):
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        columns = ("login_id", "status", "remaining", "uuid")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("login_id", text="Login ID", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.CENTER)
        self.tree.heading("remaining", text="Remaining Time", anchor=tk.CENTER)
        self.tree.heading("uuid", text="UUID", anchor=tk.W)

        self.tree.column("login_id", width=150)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("remaining", width=120, anchor=tk.CENTER)
        self.tree.column("uuid", width=250)

        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_log_area(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Live Client Message Log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED, wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_command_bar(self):
        cmd_frame = ttk.Frame(self, padding=5)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Label(cmd_frame, text="Admin Command:").pack(side=tk.LEFT, padx=5)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind("<Return>", lambda _: self.send_console_command())

        ttk.Button(cmd_frame, text="Execute", command=self.send_console_command).pack(
            side=tk.RIGHT,
            padx=5,
        )

    def _build_stats_bar(self):
        self.stats_var = tk.StringVar(value="Connections Managed: 0 | Active: 0 | Disconnected: 0")
        stats_label = ttk.Label(self, textvariable=self.stats_var, relief=tk.SUNKEN, padding=5)
        stats_label.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_action_panel(self, parent):
        action_frame = ttk.Frame(parent)
        action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        ttk.Button(action_frame, text="Show Info", command=self.show_info).pack(fill=tk.X, pady=5)
        ttk.Button(action_frame, text="Options", command=self.show_options).pack(fill=tk.X, pady=5)

    def _selected_client_id(self):
        selected = self.tree.selection()
        if not selected:
            return None

        item_id = selected[0]
        values = self.tree.item(item_id, "values")
        return values[3] if values else None

    def _selected_client_data(self):
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

    def update_timers(self):
        for client_id, data in self.clients_data.items():
            if data.get("status") != "Connected":
                continue
            if data.get("remaining", 0) <= 0:
                continue

            data["remaining"] -= 1
            self._upsert_tree_item(client_id, data)

        self.after(1000, self.update_timers)

    def show_info(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Info", "Select a client first.")
            return
        data = data or {}

        info_str = (
            f"Login ID: {data.get('login_id', 'Unknown')}\n"
            f"UUID: {client_id}\n"
        )
        messagebox.showinfo(f"Info: {data.get('login_id', 'Unknown')}", info_str)

    def show_options(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Options", "Select a client first.")
            return
        data = data or {}

        if data.get("status") != "Connected":
            messagebox.showwarning("Options", "Cannot send commands to offline clients.")
            return

        top = tk.Toplevel(self)
        top.title(f"Options: {data.get('login_id', 'Unknown')}")
        top.geometry("250x200")
        top.grab_set()

        ttk.Label(top, text="WebSocket Commands:").pack(pady=10)
        ttk.Button(
            top,
            text="Request Save Screen",
            command=lambda: self._send_client_command(top, "savescreen", client_id),
        ).pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(
            top,
            text="Request Process Report",
            command=lambda: self._send_client_command(top, "get_processes", client_id),
        ).pack(fill=tk.X, padx=20, pady=5)

    def _send_client_command(self, window, command: str, client_id: str):
        print(json.dumps({"cmd": command, "uuid": client_id}), flush=True)
        window.destroy()
        messagebox.showinfo("Sent", f"{command} command sent via IPC.")

    def send_console_command(self):
        command = self.cmd_entry.get().strip()
        if not command:
            return

        if not command.startswith("/"):
            command = "/" + command

        print(json.dumps({"type": "console_command", "command": command}), flush=True)
        self.cmd_entry.delete(0, tk.END)
        self._append_log(f"[ADMIN] Executing: {command}")

    def _append_log(self, line: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def log_message(self, client_id, message):
        data = self.clients_data.get(client_id, {})
        display_name = data.get("login_id", client_id[:8])
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{timestamp}] {display_name}: {message}")

    def process_state_update(self, payload):
        clients = payload.get("clients", [])
        active_count = 0

        for client in clients:
            client_id = client["uuid"]
            self.clients_data[client_id] = {
                **client,
                "remaining": int(float(client.get("remaining", 0))),
            }
            if client["status"] == "Connected":
                active_count += 1
            self._upsert_tree_item(client_id, self.clients_data[client_id])

        total_count = len(clients)
        disconnected_count = total_count - active_count
        self.stats_var.set(
            f"Connections Managed: {total_count} | Active: {active_count} | "
            f"Disconnected: {disconnected_count}"
        )

    def _upsert_tree_item(self, client_id: str, data: dict):
        values = (
            data["login_id"],
            data["status"],
            _format_remaining(data.get("remaining", 0)),
            client_id,
        )

        item_id = self.tree_items.get(client_id)
        if item_id and self.tree.exists(item_id):
            self.tree.item(item_id, values=values)
            return

        self.tree_items[client_id] = self.tree.insert("", tk.END, values=values)


def ipc_reader(app: ServerGUI):
    """Read lines from stdin (JSON objects sent by server.py)."""
    for line in iter(sys.stdin.readline, ""):
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] GUI IPC Error: {e}")
            continue

        message_type = msg.get("type")
        if message_type == "state_update":
            app.after(0, app.process_state_update, msg)
        elif message_type == "client_message":
            app.after(0, app.log_message, msg.get("uuid"), msg.get("text"))


if __name__ == "__main__":
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
