import subprocess
import time

def main():
    print("--- Starting Server ---")
    server = subprocess.Popen(
        ["python", "server.py", "--id", "qt-test", "--exam-duration", "5"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    time.sleep(2)
    
    print("--- Starting Client ---")
    client = subprocess.Popen(
        ["python", "client.py", "--id", "qt-test", "--login-id", "testuser", "--password", "secret", "--no-record"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    time.sleep(5)
    
    print("--- Stopping Processes ---")
    client.terminate()
    server.terminate()
    
    print("\n\n=== SERVER LOGS ===")
    try:
        outs, _ = server.communicate(timeout=2)
        print(outs)
    except:
        pass
        
    print("\n\n=== CLIENT LOGS ===")
    try:
        outc, _ = client.communicate(timeout=2)
        print(outc)
    except:
        pass

if __name__ == "__main__":
    main()
