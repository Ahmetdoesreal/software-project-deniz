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

        # Admin Command Area
        cmd_frame = ttk.Frame(self, padding=5)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        ttk.Label(cmd_frame, text="Admin Command:").pack(side=tk.LEFT, padx=5)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind("<Return>", lambda e: self.send_console_command())
        
        ttk.Button(cmd_frame, text="Execute", command=self.send_console_command).pack(side=tk.RIGHT, padx=5)

        # Message Log Area (Bottom)
        log_frame = ttk.LabelFrame(main_frame, text="Live Client Message Log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED, wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Scrollable Treeview (Top)
        tree_frame = ttk.Frame(main_frame)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        columns = ("login_id", "status", "remaining", "uuid")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
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
        
        # Action Buttons frame (Right side)
        action_frame = ttk.Frame(self)
        action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        btn_info = ttk.Button(action_frame, text="Show Info", command=self.show_info)
        btn_info.pack(fill=tk.X, pady=5)
        
        btn_opts = ttk.Button(action_frame, text="Options", command=self.show_options)
        btn_opts.pack(fill=tk.X, pady=5)

        # uuid -> { login_id, status, remaining, ip, short_id }
        self.clients_data = {}
        
        # Start the local countdown loop
        self.after(1000, self.update_timers)

    def update_timers(self):
        """Tick down the remaining time locally every second for smooth UI."""
        for cid, data in self.clients_data.items():
            if data.get("status") == "Connected" and data.get("remaining", 0) > 0:
                data["remaining"] -= 1
                
                # Find tree item
                existing_items = self.tree.get_children()
                for child in existing_items:
                    if self.tree.item(child)["values"][3] == cid:
                        m, s = divmod(data["remaining"], 60)
                        time_str = f"{m:02d}:{s:02d}"
                        self.tree.item(child, values=(data["login_id"], data["status"], time_str, cid))
                        break
                        
        self.after(1000, self.update_timers)

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
        
        status = "Unknown"
        if data:
            status = data.get("status", "Unknown")
        
        if status != "Connected":
            messagebox.showwarning("Options", "Cannot send commands to offline clients.")
            return

        # Simple popup window with actions
        top = tk.Toplevel(self)
        top.title(f"Options: {data.get('login_id', 'Unknown')}")
        top.geometry("250x200")
        top.grab_set()
        
        lbl = ttk.Label(top, text="WebSocket Commands:")
        lbl.pack(pady=10)
        
        def save_screen():
            print(json.dumps({"cmd": "savescreen", "uuid": uuid_val}), flush=True)
            top.destroy()
            messagebox.showinfo("Sent", "Save screen command sent via IPC.")
            
        def request_processes():
            print(json.dumps({"cmd": "get_processes", "uuid": uuid_val}), flush=True)
            top.destroy()
            messagebox.showinfo("Sent", "Process Report requested via IPC.")
            
        btn_save = ttk.Button(top, text="Request Save Screen", command=save_screen)
        btn_save.pack(fill=tk.X, padx=20, pady=5)
        
        btn_procs = ttk.Button(top, text="Request Process Report", command=request_processes)
        btn_procs.pack(fill=tk.X, padx=20, pady=5)

    def send_console_command(self):
        """Send a /command from the entry field to the server process."""
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
            
        # Commands must start with / for the unified handler
        if not cmd.startswith("/"):
            cmd = "/" + cmd
            
        print(json.dumps({"type": "console_command", "command": cmd}), flush=True)
        self.cmd_entry.delete(0, tk.END)
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[ADMIN] Executing: {cmd}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def log_message(self, client_id, message):
        """Append a message from a client to the log area."""
        data = self.clients_data.get(client_id, {})
        display_name = data.get("login_id", client_id[:8])
        
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {display_name}: {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

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
            rem_sec = int(float(c.get("remaining", 0)))
            
            if status == "Connected":
                active_count += 1
                
            m, s = divmod(rem_sec, 60)
            time_str = f"{m:02d}:{s:02d}"
            
            self.clients_data[cid] = c
            
            # Check if exists in tree
            existing_items = self.tree.get_children()
            found = False
            for child in existing_items:
                if self.tree.item(child, "values")[3] == cid:
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
            print(f"[DEBUG] GUI received IPC line: {line[:50]}...")
            msg = json.loads(line)
            m_type = msg.get("type")
            if m_type == "state_update":
                app.after(0, app.process_state_update, msg)
            elif m_type == "client_message":
                cid = msg.get("uuid")
                text = msg.get("text")
                app.after(0, app.log_message, cid, text)
        except Exception as e:
            print(f"[DEBUG] GUI IPC Error: {e}")
            pass
#test
if __name__ == "__main__":
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
