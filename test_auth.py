import os
import signal
import subprocess
import sys
import time

def main():
    print("--- Starting server ---")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "server.main",
            "--id",
            "test-server",
            "--host",
            "127.0.0.1",
            "--port",
            "8098",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    print("--- Starting client 1 ---")
    client1 = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "client.main",
            "--host",
            "127.0.0.1",
            "--port",
            "8098",
            "--login-id",
            "student1",
            "--password",
            "secret1",
            "--no-record",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(6)
    client1.send_signal(signal.SIGINT)
    out1, err1 = client1.communicate()
    print("Client 1 output excerpt:")
    for line in out1.split("\n")[:8]:
        print(line)

    print("--- Stopping server ---")
    server.send_signal(signal.SIGINT)
    server.wait()

    print("--- Verifying data ---")
    os.system("find data -type f")


if __name__ == "__main__":
    main()
