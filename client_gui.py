import sys
import tkinter as tk
from threading import Thread
from tkinter import ttk


def _parse_ipc_line(line: str):
    command, _, value = line.partition(":")
    return command, value


def _format_time(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


class ExamTimerGUI:
    def __init__(self, root):
        self.root = root
        self.remaining = 0
        self.active = True
        self.started = False

        self._configure_window()
        self._build_widgets()
        self.update_clock()

    def _configure_window(self):
        self.root.title("Exam Timer")
        self.root.geometry("400x200")
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def _build_widgets(self):
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(expand=True, fill="both")

        self.label_var = tk.StringVar(value="Waiting to start...")
        self.label = ttk.Label(
            self.main_frame,
            textvariable=self.label_var,
            font=("Helvetica", 16),
        )
        self.label.pack(expand=True, pady=10)

        self.start_btn = ttk.Button(
            self.main_frame,
            text="Start Exam",
            command=self.on_start_click,
        )
        self.start_btn.pack(pady=10)

    def on_start_click(self):
        print("ACTION:START", flush=True)
        self.start_btn.config(state=tk.DISABLED)
        self.label_var.set("Starting exam...")

    def update_clock(self):
        if self.active and self.started:
            if self.remaining > 0:
                self.label_var.set(_format_time(self.remaining))
                self.remaining -= 1
            elif self.remaining == 0:
                self.label_var.set("00:00")

        self.root.after(1000, self.update_clock)

    def set_remaining(self, seconds):
        if seconds < 0:
            self.root.destroy()
            return

        self.remaining = seconds
        if self.started:
            return

        self.started = True
        self.start_btn.pack_forget()
        self.label.config(font=("Helvetica", 32, "bold"))

    def on_closing(self):
        pass


def ipc_reader(app: ExamTimerGUI):
    """Read remaining times from stdin."""
    for line in sys.stdin:
        command, value = _parse_ipc_line(line.strip())
        try:
            if command == "SYNC":
                app.set_remaining(int(value))
            elif command == "END":
                app.set_remaining(-1)
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = ExamTimerGUI(root)

    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()

    root.mainloop()
