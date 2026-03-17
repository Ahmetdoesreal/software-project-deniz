import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import os

try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

class ServerLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Exam Server Launcher")
        self.geometry("400x350")
        self.resizable(False, False)
        
        # Configure layout
        self.columnconfigure(1, weight=1)
        
        # Server ID
        ttk.Label(self, text="Server ID:").grid(row=0, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_id = tk.StringVar(value="default")
        ttk.Entry(self, textvariable=self.v_id).grid(row=0, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Host
        ttk.Label(self, text="Host IP:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_host = tk.StringVar(value="0.0.0.0")
        ttk.Entry(self, textvariable=self.v_host).grid(row=1, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Port
        ttk.Label(self, text="Port:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_port = tk.IntVar(value=8080)
        ttk.Entry(self, textvariable=self.v_port).grid(row=2, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Exam Duration
        ttk.Label(self, text="Exam Duration (m):").grid(row=3, column=0, sticky=tk.W, padx=10, pady=10)
        self.v_dur = tk.IntVar(value=45)
        ttk.Entry(self, textvariable=self.v_dur).grid(row=3, column=1, sticky=tk.EW, padx=10, pady=10)
        
        # Exam Files Path
        ttk.Label(self, text="Exam ZIP File:").grid(row=4, column=0, sticky=tk.W, padx=10, pady=10)
        
        file_frame = ttk.Frame(self)
        file_frame.grid(row=4, column=1, sticky=tk.EW, padx=10, pady=10)
        file_frame.columnconfigure(0, weight=1)
        
        self.v_file = tk.StringVar(value="")
        ttk.Entry(file_frame, textvariable=self.v_file, state="readonly").grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(file_frame, text="Browse", width=8, command=self.browse_file).grid(row=0, column=1, padx=(5,0))
        
        # Start GUI Monitor
        self.v_gui = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Launch Monitoring Dashboard", variable=self.v_gui).grid(row=5, column=0, columnspan=2, pady=(10, 0))
        
        # Start Button
        btn = ttk.Button(self, text="Start Server", command=self.start_server)
        btn.grid(row=6, column=0, columnspan=2, pady=20)

    def browse_file(self):
        filename = filedialog.askopenfilename(title="Select Exam Materials", filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if filename:
            self.v_file.set(filename)

    def start_server(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        server_path = os.path.join(script_dir, "server.py")
        
        sid = self.v_id.get().strip()
        if not sid:
            messagebox.showerror("Error", "Server ID cannot be empty")
            return
            
        cmd = [sys.executable, server_path, "--id", sid]
        cmd.extend(["--host", self.v_host.get().strip()])
        cmd.extend(["--port", str(self.v_port.get())])
        cmd.extend(["--exam-duration", str(self.v_dur.get())])
        
        filepath = self.v_file.get().strip()
        if filepath:
            cmd.extend(["--exam-files", filepath])
            
        if self.v_gui.get():
            cmd.append("--gui")
            
        try:
            # Hide the launcher, spawn the server
            self.withdraw()
            # If server crashes, we won't see it natively without keeping the terminal or pipe open, 
            # but for a simple launcher `Popen` works fine.
            subprocess.Popen(cmd)
            sys.exit(0) # Close launcher fully
        except Exception as e:
            messagebox.showerror("Launch Error", str(e))
            self.deiconify() # bring back window

if __name__ == "__main__":
    app = ServerLauncher()
    app.mainloop()
