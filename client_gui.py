import sys
import tkinter as tk
from threading import Thread
import time

class ExamTimerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Exam Timer")
        self.root.geometry("250x100")
        # Keep window on top
        self.root.attributes('-topmost', True)
        # Handle close attempt (mostly intercept it)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.geometry("300x150")

        self.label = tk.Label(root, text="Waiting for server...", font=("Helvetica", 16))
        self.label.pack(expand=True, pady=10)

        self.start_button = tk.Button(root, text="Start Exam", font=("Helvetica", 14, "bold"), 
                                      command=self.on_start_click, bg="#4CAF50", fg="white", 
                                      padx=20, pady=10)
        self.start_button.pack(pady=10)

        self.remaining = 0
        self.active = True

        self.update_clock()

    def on_start_click(self):
        """Notify the parent process that the user wants to start the exam."""
        print("ACTION:START", flush=True)
        self.start_button.config(state=tk.DISABLED, text="Starting...")

    def update_clock(self):
        if self.active:
            if self.remaining > 0:
                m, s = divmod(self.remaining, 60)
                self.label.config(text=f"{m:02d}:{s:02d}", fg="black" if self.remaining > 60 else "red")
                self.remaining -= 1
            elif self.remaining == 0:
                self.label.config(text="00:00", fg="red")
        
        self.root.after(1000, self.update_clock)

    def set_remaining(self, seconds):
        if seconds < 0:
             # Negative indicates termination command
             self.root.destroy()
        else:
             self.remaining = seconds
             # Once we have a timer, the exam has started
             if self.start_button.winfo_exists():
                 self.start_button.pack_forget()
                 self.label.config(font=("Helvetica", 24, "bold"))

    def on_closing(self):
        # Prevent manual closure during the exam unless specific conditions met
        pass

def ipc_reader(app):
    """Read remaining times from stdin (sent by the parent process)."""
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                msg = line.split(":")
                if msg[0] == "SYNC":
                    app.set_remaining(int(msg[1]))
                elif msg[0] == "END":
                    app.set_remaining(-1)
            except Exception:
                pass

if __name__ == "__main__":
    root = tk.Tk()
    app = ExamTimerGUI(root)
    
    # Run the stdin reader in a background thread to not block tkinter's mainloop
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    
    root.mainloop()
