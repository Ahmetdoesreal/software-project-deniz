import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import os

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

class ClientLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Exam Client Login")
        self.geometry("350x300")
        self.resizable(False, False)
        
        # Configure layout
        self.columnconfigure(1, weight=1)
        
        ttk.Label(self, text="Student Details", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, columnspan=2, pady=(10, 5), sticky=tk.W, padx=10)
        
        # Login ID
        ttk.Label(self, text="Login ID:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.v_login = tk.StringVar(value="")
        ttk.Entry(self, textvariable=self.v_login).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)
        
        # Password
        ttk.Label(self, text="Password:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=5)
        self.v_pass = tk.StringVar(value="")
        ttk.Entry(self, textvariable=self.v_pass, show="*").grid(row=2, column=1, sticky=tk.EW, padx=10, pady=5)
        
        ttk.Separator(self, orient='horizontal').grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=10)
        ttk.Label(self, text="Server Connection Validation", font=("TkDefaultFont", 10, "bold")).grid(row=4, column=0, columnspan=2, pady=(0, 5), sticky=tk.W, padx=10)
        
        # Server ID
        ttk.Label(self, text="Server ID:").grid(row=5, column=0, sticky=tk.W, padx=10, pady=5)
        self.v_id = tk.StringVar(value="default")
        ttk.Entry(self, textvariable=self.v_id).grid(row=5, column=1, sticky=tk.EW, padx=10, pady=5)
        
        # Options
        self.v_adv = tk.BooleanVar(value=False)
        btn_adv = ttk.Checkbutton(self, text="Advanced Networking Options", variable=self.v_adv, command=self.toggle_advanced)
        btn_adv.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 0))
        
        # Advanced Frame
        self.adv_frame = ttk.Frame(self)
        self.adv_frame.columnconfigure(1, weight=1)
        
        ttk.Label(self.adv_frame, text="Host IP:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=5)
        self.v_host = tk.StringVar(value="")
        ttk.Entry(self.adv_frame, textvariable=self.v_host).grid(row=0, column=1, sticky=tk.EW, padx=10, pady=5)
        
        ttk.Label(self.adv_frame, text="Port:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.v_port = tk.IntVar(value=8080)
        ttk.Entry(self.adv_frame, textvariable=self.v_port).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=5)

        # Login button at the bottom
        btn_start = ttk.Button(self, text="Connect & Login", command=self.start_client)
        btn_start.grid(row=8, column=0, columnspan=2, pady=20)
        
    def toggle_advanced(self):
        if self.v_adv.get():
            self.adv_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW)
            self.geometry("350x400")
        else:
            self.adv_frame.grid_forget()
            self.geometry("350x300")

    def start_client(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        client_path = os.path.join(script_dir, "client.py")
        
        lid = self.v_login.get().strip()
        pwd = self.v_pass.get().strip()
        sid = self.v_id.get().strip()
        
        if not lid or not pwd:
            messagebox.showerror("Validation Field", "Login ID and Password required.")
            return
            
        cmd = [sys.executable, client_path]
        cmd.extend(["--login-id", lid])
        cmd.extend(["--password", pwd])
        
        if sid:
            cmd.extend(["--id", sid])
            
        if self.v_adv.get():
            host = self.v_host.get().strip()
            if host:
                cmd.extend(["--host", host])
            cmd.extend(["--port", str(self.v_port.get())])
            
        try:
            self.withdraw()
            # Popen because we don't want the UI hanging waiting for the multi-hour exam to finish.
            subprocess.Popen(cmd)
            sys.exit(0)
        except Exception as e:
            messagebox.showerror("Error Launching Client", str(e))
            self.deiconify()

if __name__ == "__main__":
    app = ClientLauncher()
    app.mainloop()
