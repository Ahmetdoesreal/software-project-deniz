import sys
import tkinter as tk
from tkinter import ttk, messagebox
import json
from threading import Thread

class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Server Monitor Dashboard")
        self.geometry("800x400")
        
        # --- Layout ---
        # Main frame
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Scrollable Treeview
        columns = ("login_id", "status", "remaining", "uuid")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("login_id", text="Login ID", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.CENTER)
        self.tree.heading("remaining", text="Remaining Time", anchor=tk.CENTER)
        self.tree.heading("uuid", text="UUID", anchor=tk.W)
        
        self.tree.column("login_id", width=150)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("remaining", width=120, anchor=tk.CENTER)
        self.tree.column("uuid", width=250)
        
        # Scrollbars
        y_scroll = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom Statistics Bar
        self.stats_var = tk.StringVar()
        self.stats_var.set("Connections: 0 | Active: 0 | Disconnected: 0")
        stats_label = ttk.Label(self, textvariable=self.stats_var, relief=tk.SUNKEN, padding=5)
        stats_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Action Buttons frame (Right side)
        action_frame = ttk.Frame(self)
        action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        btn_info = ttk.Button(action_frame, text="Show Info", command=self.show_info)
        btn_info.pack(fill=tk.X, pady=5)
        
        btn_opts = ttk.Button(action_frame, text="Options", command=self.show_options)
        btn_opts.pack(fill=tk.X, pady=5)

        # State storage
        # uuid -> { login_id, status, remaining, ip, short_id }
        self.clients_data = {}

    def show_info(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Select a client first.")
            return
        
        item = self.tree.item(selected[0])
        uuid_val = item["values"][3]
        data = self.clients_data.get(uuid_val)
        if data:
            info_str = (
                f"Login ID: {data.get('login_id', 'Unknown')}\n"
                f"UUID: {uuid_val}\n"
            )
            messagebox.showinfo(f"Info: {data.get('login_id', 'Unknown')}", info_str)
            
    def show_options(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Options", "Select a client first.")
            return
            
        item = self.tree.item(selected[0])
        uuid_val = item["values"][3]
        data = self.clients_data.get(uuid_val)
        status = data.get("status", "Unknown") if data else "Unknown"
        
        if status != "Connected":
            messagebox.showwarning("Options", "Cannot send commands to offline clients.")
            return

        # Simple popup window with actions
        top = tk.Toplevel(self)
        top.title(f"Options: {data.get('login_id', 'Unknown')}")
        top.geometry("250x150")
        top.grab_set()
        
        lbl = ttk.Label(top, text="WebSocket Commands:")
        lbl.pack(pady=10)
        
        def save_screen():
            print(json.dumps({"cmd": "savescreen", "uuid": uuid_val}), flush=True)
            top.destroy()
            messagebox.showinfo("Sent", "Save screen command sent via IPC.")
            
        btn_save = ttk.Button(top, text="Request Save Screen", command=save_screen)
        btn_save.pack(fill=tk.X, padx=20, pady=5)

    def process_state_update(self, payload):
        """Update the UI based on state dictionary from server.py"""
        clients_list = payload.get("clients", [])
        
        active_count = 0
        total_count = len(clients_list)
        
        # Upsert into treeview and internal state
        for c in clients_list:
            cid = c["uuid"]
            login = c["login_id"]
            status = c["status"]
            rem_sec = c["remaining"]
            
            if status == "Connected":
                active_count += 1
                
            m, s = divmod(rem_sec, 60)
            time_str = f"{m:02d}:{s:02d}"
            
            self.clients_data[cid] = c
            
            # Check if exists in tree
            existing_items = self.tree.get_children()
            found = False
            for child in existing_items:
                if self.tree.item(child)["values"][3] == cid:
                    self.tree.item(child, values=(login, status, time_str, cid))
                    found = True
                    break
            
            if not found:
                self.tree.insert("", tk.END, values=(login, status, time_str, cid))
                
        # Update statistics bar
        disc_count = total_count - active_count
        self.stats_var.set(f"Connections Managed: {total_count} | Active: {active_count} | Disconnected: {disc_count}")

def ipc_reader(app: ServerGUI):
    """Read lines from stdin (JSON objects sent by server.py)."""
    for line in iter(sys.stdin.readline, ''):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("type") == "state_update":
                app.after(0, app.process_state_update, msg)
        except Exception:
            pass
#test
if __name__ == "__main__":
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
