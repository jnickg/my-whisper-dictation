#!/usr/bin/env python3
"""
Whisper Dictation Client

Connects to the whisper-dictate daemon and sends commands.
"""

import socket
import sys
import json
import os

SOCKET_PATH = os.environ.get("JNICKG_DICTATE_SOCKET", "/tmp/jnickg-dictate.sock")


def send_command(cmd: str) -> dict:
    """Send a command to the daemon and return the response."""
    if not os.path.exists(SOCKET_PATH):
        return {"status": "error", "message": "Daemon not running (socket not found)"}

    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(30)  # 30 second timeout for transcription
        client.connect(SOCKET_PATH)
        client.sendall(cmd.encode("utf-8"))
        response = client.recv(4096).decode("utf-8")
        client.close()
        return json.loads(response)
    except socket.timeout:
        return {"status": "error", "message": "Timeout waiting for response"}
    except ConnectionRefusedError:
        return {"status": "error", "message": "Connection refused - is the daemon running?"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def main():
    if len(sys.argv) < 2:
        cmd = "toggle"  # Default action
    else:
        cmd = sys.argv[1]

    result = send_command(cmd)

    if result.get("status") == "ok":
        msg = result.get("message", "OK")
        if "text" in result:
            print(f"{msg}: {result['text']}")
        else:
            print(msg)
        sys.exit(0)
    else:
        print(f"Error: {result.get('message', 'Unknown error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
