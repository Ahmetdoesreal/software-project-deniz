@echo off
start "Server" cmd /k "cd /d %~dp0 && python server.py --id my-server"
start "Client 1" cmd /k "cd /d %~dp0 && python client.py --id my-server --login-id client1 --password testpass"
start "Client 2" cmd /k "cd /d %~dp0 && python client.py --id my-server --login-id client2 --password testpass"
start "Client 3" cmd /k "cd /d %~dp0 && python client.py --id my-server --login-id client3 --password testpass"
