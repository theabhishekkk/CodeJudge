import socket

try:
    socket.create_connection(("example.com", 80), timeout=2)
    print("connected")
except Exception:
    print("blocked")
