import subprocess
import time
import json
import os
import signal

def main():
    print("--- Starting server ---")
    server = subprocess.Popen(["python", "server.py", "--id", "test-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    print("--- Starting client 1 ---")
    client1 = subprocess.Popen(["python", "client.py", "--id", "test-server", "--login-id", "testuser", "--password", "secret"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(6)
    client1.send_signal(signal.SIGINT)
    out1, err1 = client1.communicate()
    print("Client 1 output excerpt:")
    for line in out1.split('\n')[:8]: print(line)
    
    print("--- Stopping server ---")
    server.send_signal(signal.SIGINT)
    server.wait()
    
    print("--- Verifying data ---")
    os.system("find data -type f")

if __name__ == "__main__":
    main()
