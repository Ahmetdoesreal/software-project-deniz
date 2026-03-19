#!/usr/bin/env python3
"""
Cross-platform demo launcher.

Starts one server and three clients, each in a separate terminal window
(matching the behavior of the original run_demo.bat).

Works on Windows (cmd), macOS (Terminal.app), and Linux (gnome-terminal, xterm, etc).
"""

import subprocess
import sys
import time
import os
import platform

SERVER_ID = "my-server"

def spawn_terminal(title: str, command: str):
    """Launch a new terminal window to run the given command."""
    system = platform.system()
    
    if system == "Windows":
        # cmd.exe /k keeps the window open after command finishes
        subprocess.Popen(f'start "{title}" cmd /k "{command}"', shell=True)
        
    elif system == "Darwin":
        # macOS: Use AppleScript to tell Terminal.app to open a new window and run the command
        # The command needs to be properly escaped
        escaped_cmd = command.replace('"', '\\"')
        script = f'''
        tell application "Terminal"
            activate
            do script "{escaped_cmd}"
        end tell
        '''
        subprocess.Popen(["osascript", "-e", script])
        
    elif system == "Linux":
        # Try common Linux terminal emulators
        terminals = [
            ["gnome-terminal", "--title", title, "--", "bash", "-c", f"{command}; exec bash"],
            ["konsole", "-e", "bash", "-c", f"{command}; exec bash"],
            ["xfce4-terminal", "-T", title, "-e", f"bash -c '{command}; exec bash'"],
            ["xterm", "-title", title, "-e", f"bash -c '{command}; exec bash'"]
        ]
        
        success = False
        for term_cmd in terminals:
            try:
                subprocess.Popen(term_cmd)
                success = True
                break
            except FileNotFoundError:
                continue
                
        if not success:
            print(f"[ERROR] Could not find a suitable terminal emulator on Linux to launch '{title}'.")
            print(f"        Tried: {[t[0] for t in terminals]}")

def main():
    # Ensure commands run in the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    python_cmd = sys.executable

    print(f"[LAUNCHER] Spawning UI terminals... (OS: {platform.system()})\n")

    # 1. Start Server
    print(f"-> Starting Server ({SERVER_ID})")
    if platform.system() == "Windows":
        server_cmd = f"cd \\\"{script_dir}\\\" && \\\"{python_cmd}\\\" -m server.main --id {SERVER_ID} --reset --gui"
    else:
        server_cmd = f"cd '{script_dir}' && '{python_cmd}' -m server.main --id {SERVER_ID} --reset --gui"
    spawn_terminal("Server", server_cmd)

    # Give server a moment to start
    time.sleep(1.5)

    # 2. Start Clients
    for i in range(1, 4):
        print(f"-> Starting Client {i}")
        if platform.system() == "Windows":
            client_cmd = (
                f"cd \\\"{script_dir}\\\" && "
                f"\\\"{python_cmd}\\\" -m client.main --id {SERVER_ID} "
                f"--login-id student{i} --password secret{i} --no-record"
            )
        else:
            client_cmd = (
                f"cd '{script_dir}' && "
                f"'{python_cmd}' -m client.main --id {SERVER_ID} "
                f"--login-id student{i} --password secret{i} --no-record"
            )
        spawn_terminal(f"Client {i}", client_cmd)
        time.sleep(0.5)

    print("\n[LAUNCHER] All windows spawned. You can close this window now.")

if __name__ == "__main__":
    main()
