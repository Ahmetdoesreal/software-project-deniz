import subprocess
import sys
import time


def main():
    print("--- Starting Server ---")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "server.main",
            "--id",
            "qt-test",
            "--host",
            "127.0.0.1",
            "--port",
            "8097",
            "--exam-duration",
            "5",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(2)

    print("--- Starting Client ---")
    client = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "client.main",
            "--host",
            "127.0.0.1",
            "--port",
            "8097",
            "--login-id",
            "student1",
            "--password",
            "secret1",
            "--no-record",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(5)

    print("--- Stopping Processes ---")
    client.terminate()
    server.terminate()

    print("\n\n=== SERVER LOGS ===")
    try:
        outs, _ = server.communicate(timeout=2)
        print(outs)
    except Exception:
        pass

    print("\n\n=== CLIENT LOGS ===")
    try:
        outc, _ = client.communicate(timeout=2)
        print(outc)
    except Exception:
        pass


if __name__ == "__main__":
    main()
