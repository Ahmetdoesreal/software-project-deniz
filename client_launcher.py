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
        self.geometry("550x500")
        self.resizable(False, False)
        
        # Apply 1.5x UI scaling equivalent via font rendering
        style = ttk.Style(self)
        style.configure('.', font=('Helvetica', 14))
        
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
        self.btn_start = ttk.Button(self, text="Connect & Login", command=self.start_client)
        self.btn_start.grid(row=8, column=0, columnspan=2, pady=20)
        
    def toggle_advanced(self):
        if self.v_adv.get():
            self.adv_frame.grid(row=7, column=0, columnspan=2, sticky=tk.EW)
            self.geometry("550x650")
        else:
            self.adv_frame.grid_forget()
            self.geometry("550x500")

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
            
        self.btn_start.config(state=tk.DISABLED, text="Validating...")
        
        def run_check():
            import threading
            cmd_check = cmd + ["--check-login", "--timeout", "3"]
            try:
                # Create process without a visible console window on Windows
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                result = subprocess.run(cmd_check, capture_output=True, text=True, startupinfo=startupinfo)
                if result.returncode == 0:
                    self.after(0, self.on_check_success, cmd)
                else:
                    error_msg = "Unknown validation error."
                    output = result.stdout + "\n" + result.stderr
                    for line in output.splitlines():
                        if "[FATAL]" in line or "[!]" in line:
                            error_msg = line.strip()
                            break
                    self.after(0, self.on_check_fail, error_msg)
            except Exception as e:
                self.after(0, self.on_check_fail, str(e))
                
        import threading
        threading.Thread(target=run_check, daemon=True).start()

    def on_check_success(self, cmd):
        try:
            self.withdraw()
            
            # Ensure the client gets its own console window on Windows so it can stay interactive
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NEW_CONSOLE

            # Launch the real client
            subprocess.Popen(cmd, creationflags=creationflags)
            sys.exit(0)
        except Exception as e:
            messagebox.showerror("Error Launching Client", str(e))
            self.deiconify()

    def on_check_fail(self, error_msg):
        self.btn_start.config(state=tk.NORMAL, text="Connect & Login")
        messagebox.showerror("Login Failed", f"Could not connect or authenticate with the server:\n\n{error_msg}")

if __name__ == "__main__":
    app = ClientLauncher()
    app.mainloop()
