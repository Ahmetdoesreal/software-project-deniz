import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import os
import socket

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

class ServerLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Exam Server Launcher")
        self.geometry("600x660")
        self.resizable(False, False)
        
        # Apply 1.5x UI scaling equivalent via font rendering
        style = ttk.Style(self)
        style.configure('.', font=('Helvetica', 14))
        
        # Configure layout
        self.columnconfigure(1, weight=1)
        
        # Resolve Network Details
        self.local_ip = self.get_local_ip()
        self.local_port = self.get_free_port()
        
        # Network Info Display
        info_frame = ttk.LabelFrame(self, text="Network Target")
        info_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        
        ttk.Label(info_frame, text=f"IP Address: {self.local_ip}", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        ttk.Label(info_frame, text=f"Port: {self.local_port}", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, padx=10, pady=(0, 5))
        
        # Server ID
        ttk.Label(self, text="Server ID:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_id = tk.StringVar(value="default")
        ttk.Entry(self, textvariable=self.v_id).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Exam Duration
        ttk.Label(self, text="Exam Duration (m):").grid(row=2, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_dur = tk.IntVar(value=45)
        ttk.Entry(self, textvariable=self.v_dur).grid(row=2, column=1, sticky=tk.EW, padx=10, pady=10)

        ttk.Label(self, text="Host:").grid(row=3, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_host = tk.StringVar(value="0.0.0.0")
        ttk.Entry(self, textvariable=self.v_host).grid(row=3, column=1, sticky=tk.EW, padx=10, pady=10)

        ttk.Label(self, text="Port:").grid(row=4, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_port = tk.IntVar(value=self.local_port)
        ttk.Entry(self, textvariable=self.v_port).grid(row=4, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Exam Files Path
        ttk.Label(self, text="Exam ZIP File:").grid(row=5, column=0, sticky=tk.W, padx=10, pady=10)
        
        file_frame = ttk.Frame(self)
        file_frame.grid(row=5, column=1, sticky=tk.EW, padx=10, pady=10)
        file_frame.columnconfigure(0, weight=1)
        
        self.v_file = tk.StringVar(value="")
        ttk.Entry(file_frame, textvariable=self.v_file, state="readonly").grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(file_frame, text="Browse", width=8, command=self.browse_file).grid(row=0, column=1, padx=(5,0))
        
        # Start GUI Monitor
        self.v_gui = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Launch Monitoring Dashboard", variable=self.v_gui).grid(row=6, column=0, columnspan=2, pady=(10, 0))

        self.v_reset = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Reset Runtime State On Start", variable=self.v_reset).grid(row=7, column=0, columnspan=2, pady=(10, 0))
        
        # Start Button
        btn = ttk.Button(self, text="Start Server", command=self.start_server)
        btn.grid(row=8, column=0, columnspan=2, pady=20)

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
            
    def get_free_port(self):
        try:
            # Check 8080 first
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("", 8080))
            s.close()
            return 8080
        except OSError:
            # 8080 is taken, find random open port
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("", 0))
                port = s.getsockname()[1]
                s.close()
                return port
            except Exception:
                return 8080

    def browse_file(self):
        filename = filedialog.askopenfilename(title="Select Exam Materials", filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if filename:
            self.v_file.set(filename)

    def start_server(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.copy()
        env["PYTHONPATH"] = script_dir + os.pathsep + env.get("PYTHONPATH", "")
        sid = self.v_id.get().strip()
        if not sid:
            messagebox.showerror("Error", "Server ID cannot be empty")
            return
        if self.v_dur.get() <= 0:
            messagebox.showerror("Error", "Exam duration must be greater than 0.")
            return
        if not 1 <= self.v_port.get() <= 65535:
            messagebox.showerror("Error", "Port must be between 1 and 65535.")
            return
            
        cmd = [
            sys.executable,
            "-m",
            "server.main",
            "--id",
            sid,
            "--host",
            self.v_host.get().strip() or "0.0.0.0",
            "--port",
            str(self.v_port.get()),
            "--exam-duration",
            str(self.v_dur.get()),
        ]
        
        filepath = self.v_file.get().strip()
        if filepath:
            cmd.extend(["--exam-files", filepath])
            
        if self.v_gui.get():
            cmd.append("--gui")
        if self.v_reset.get():
            cmd.append("--reset")
            
        try:
            # Hide the launcher, spawn the server
            self.withdraw()
            
            # Ensure the server gets its own console window on Windows so it can stay interactive
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_CONSOLE
                
            subprocess.Popen(cmd, creationflags=creationflags, env=env)
            sys.exit(0) # Close launcher fully
        except Exception as e:
            messagebox.showerror("Launch Error", str(e))
            self.deiconify() # bring back window

if __name__ == "__main__":
    app = ServerLauncher()
    app.mainloop()
