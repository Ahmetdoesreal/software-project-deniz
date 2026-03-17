import sys
import tkinter as tk
from tkinter import ttk
from threading import Thread
import time

class ExamTimerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Exam Timer")
        self.root.geometry("400x200")
        self.root.attributes('-topmost', True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Main container with padding
        self.main_frame = ttk.Frame(root, padding="20")
        self.main_frame.pack(expand=True, fill="both")

        # Label for status/timer
        self.label_var = tk.StringVar(value="Waiting to start...")
        self.label = ttk.Label(self.main_frame, textvariable=self.label_var, font=("Helvetica", 16))
        self.label.pack(expand=True, pady=10)

        # Simple Start Button
        self.start_btn = ttk.Button(self.main_frame, text="Start Exam", command=self.on_start_click)
        self.start_btn.pack(pady=10)

        self.remaining = 0
        self.active = True
        self.started = False

        self.update_clock()

    def on_start_click(self):
        """Notify the parent process that the user wants to start the exam."""
        print("ACTION:START", flush=True)
        self.start_btn.config(state=tk.DISABLED)
        self.label_var.set("Starting exam...")

    def update_clock(self):
        if self.active and self.started:
            if self.remaining > 0:
                m, s = divmod(self.remaining, 60)
                time_str = f"{m:02d}:{s:02d}"
                self.label_var.set(time_str)
                # Keep the color black unless low on time
                # we can't easily set foreground on ttk.Label with just .config in some themes, 
                # but for simplicity we'll just stick to text updates or use a standard tk.Label for color
                self.remaining -= 1
            elif self.remaining == 0:
                self.label_var.set("00:00")
        
        self.root.after(1000, self.update_clock)

    def set_remaining(self, seconds):
        if seconds < 0:
             self.root.destroy()
        else:
             self.remaining = seconds
             if not self.started:
                 self.started = True
                 self.start_btn.pack_forget()
                 # Switch to large font for timer
                 self.label.config(font=("Helvetica", 32, "bold"))

    def on_closing(self):
        # Prevent manual closure
        pass

def ipc_reader(app):
    """Read remaining times from stdin."""
    for line in sys.stdin:
        line = line.strip()
        if ":" in line:
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
    
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    
    root.mainloop()
