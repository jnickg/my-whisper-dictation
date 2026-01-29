#!/usr/bin/env python3
"""
Whisper Dictation Daemon (Streaming Mode)

A systemd-compatible daemon that provides real-time speech-to-text dictation
by connecting to a SimulStreaming server. Text appears as you speak instead
of after recording stops.
"""

import subprocess
import os
import signal
import socket
import sys
import threading
import json
import time
from pathlib import Path

# Configuration
SOCKET_PATH = os.environ.get("JNICKG_DICTATE_SOCKET", "/tmp/jnickg-dictate.sock")
TEXT_INPUT_METHOD = os.environ.get("JNICKG_DICTATE_INPUT_METHOD", "ydotool")
STREAMING_HOST = os.environ.get("JNICKG_DICTATE_STREAMING_HOST", "localhost")
STREAMING_PORT = os.environ.get("JNICKG_DICTATE_STREAMING_PORT", "43001")

# Global state
arecord_proc = None
nc_proc = None
reader_thread = None
streaming_lock = threading.Lock()
typed_so_far = ""
stop_reader = threading.Event()


def log(msg: str):
    """Log to stderr for systemd journal."""
    print(msg, file=sys.stderr, flush=True)


def type_text(text: str):
    """Type text into the focused window using the configured method."""
    if not text:
        return

    try:
        if TEXT_INPUT_METHOD == "wtype":
            subprocess.run(["wtype", "--", text], check=True)
        elif TEXT_INPUT_METHOD == "ydotool":
            subprocess.run(["ydotool", "type", "--", text], check=True)
        elif TEXT_INPUT_METHOD == "xdotool":
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], check=True)
        else:
            log(f"Unknown input method: {TEXT_INPUT_METHOD}")
    except subprocess.CalledProcessError as e:
        log(f"Failed to type text: {e}")
    except FileNotFoundError:
        log(f"Text input tool not found: {TEXT_INPUT_METHOD}")


def send_backspaces(count: int):
    """Send backspace key presses to delete characters."""
    if count <= 0:
        return

    try:
        if TEXT_INPUT_METHOD == "wtype":
            # wtype uses key names
            for _ in range(count):
                subprocess.run(["wtype", "-k", "BackSpace"], check=True)
        elif TEXT_INPUT_METHOD == "ydotool":
            # ydotool: key code 14 is backspace, :1 press :0 release
            for _ in range(count):
                subprocess.run(["ydotool", "key", "14:1", "14:0"], check=True)
        elif TEXT_INPUT_METHOD == "xdotool":
            for _ in range(count):
                subprocess.run(["xdotool", "key", "BackSpace"], check=True)
        else:
            log(f"Unknown input method for backspace: {TEXT_INPUT_METHOD}")
    except subprocess.CalledProcessError as e:
        log(f"Failed to send backspaces: {e}")
    except FileNotFoundError:
        log(f"Text input tool not found: {TEXT_INPUT_METHOD}")


def parse_streaming_line(line: str) -> str:
    """Parse '<start_ms> <end_ms>  <text>' format, return text (preserving leading space)."""
    parts = line.strip().split(' ', maxsplit=2)
    if len(parts) >= 3:
        return parts[2]
    return ""


def find_common_prefix_length(s1: str, s2: str) -> int:
    """Find the length of the longest common prefix between two strings."""
    min_len = min(len(s1), len(s2))
    for i in range(min_len):
        if s1[i] != s2[i]:
            return i
    return min_len


def handle_streaming_output(new_text: str):
    """Handle streaming output by typing each segment directly."""
    global typed_so_far

    if not new_text:
        return

    # Each line from the server is a new segment - type it directly
    log(f"Typing: {repr(new_text)}")
    type_text(new_text)

    # Accumulate for final result
    typed_so_far += new_text


def reader_thread_func():
    """Thread function to read streaming output from nc and type incrementally."""
    global nc_proc, typed_so_far

    log("Reader thread started")

    while not stop_reader.is_set():
        if nc_proc is None or nc_proc.stdout is None:
            break

        try:
            line = nc_proc.stdout.readline()
            if not line:
                # EOF - connection closed
                log("Reader: EOF from nc")
                break

            line = line.decode("utf-8", errors="replace").strip()
            if line:
                log(f"Received: {line}")
                text = parse_streaming_line(line)
                if text:
                    handle_streaming_output(text)

        except Exception as e:
            log(f"Reader error: {e}")
            break

    log("Reader thread exiting")


def check_streaming_server() -> bool:
    """Check if the streaming server is running and accepting connections."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((STREAMING_HOST, int(STREAMING_PORT)))
            return True
    except (socket.error, socket.timeout, ValueError):
        return False


def start_streaming() -> dict:
    """Start streaming dictation."""
    global arecord_proc, nc_proc, reader_thread, typed_so_far, stop_reader

    with streaming_lock:
        if arecord_proc is not None:
            return {"status": "error", "message": "Already streaming"}

        # Check if streaming server is available
        if not check_streaming_server():
            return {
                "status": "error",
                "message": f"Streaming server not available at {STREAMING_HOST}:{STREAMING_PORT}. "
                           "Check: systemctl --user status whisper-streaming-server"
            }

        try:
            # Reset state
            typed_so_far = ""
            stop_reader.clear()

            # Start arecord piping to nc
            # arecord: -f S16_LE (16-bit signed little-endian), -c1 (mono), -r 16000 (16kHz), -t raw (raw PCM)
            arecord_proc = subprocess.Popen(
                ["arecord", "-f", "S16_LE", "-c1", "-r", "16000", "-t", "raw", "-D", "default"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            nc_proc = subprocess.Popen(
                ["nc", STREAMING_HOST, STREAMING_PORT],
                stdin=arecord_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            # Allow SIGPIPE propagation
            arecord_proc.stdout.close()

            # Start reader thread
            reader_thread = threading.Thread(target=reader_thread_func, daemon=True)
            reader_thread.start()

            log(f"Streaming started to {STREAMING_HOST}:{STREAMING_PORT}")
            return {"status": "ok", "message": "Streaming started"}

        except FileNotFoundError as e:
            arecord_proc = None
            nc_proc = None
            return {"status": "error", "message": f"Required tool not found: {e.filename}"}
        except Exception as e:
            arecord_proc = None
            nc_proc = None
            return {"status": "error", "message": str(e)}


def stop_streaming() -> dict:
    """Stop streaming and return the final transcription."""
    global arecord_proc, nc_proc, reader_thread, typed_so_far, stop_reader

    with streaming_lock:
        if arecord_proc is None:
            return {"status": "error", "message": "Not streaming"}

        final_text = typed_so_far

        try:
            # Signal reader thread to stop
            stop_reader.set()

            # Stop arecord gracefully
            if arecord_proc and arecord_proc.poll() is None:
                arecord_proc.terminate()
                try:
                    arecord_proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    arecord_proc.kill()

            # Wait for nc to close (server sends final segment on disconnect)
            if nc_proc and nc_proc.poll() is None:
                try:
                    nc_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    nc_proc.terminate()

            # Wait for reader thread to finish
            if reader_thread and reader_thread.is_alive():
                reader_thread.join(timeout=2)

            log("Streaming stopped")

            # Get the final text that was typed
            final_text = typed_so_far

        except Exception as e:
            log(f"Error stopping streaming: {e}")
        finally:
            arecord_proc = None
            nc_proc = None
            reader_thread = None

        if final_text:
            return {"status": "ok", "message": "Stopped", "text": final_text}
        else:
            return {"status": "ok", "message": "Stopped (no speech detected)", "text": ""}


def toggle_streaming() -> dict:
    """Toggle streaming state."""
    with streaming_lock:
        is_streaming = arecord_proc is not None

    if is_streaming:
        return stop_streaming()
    else:
        return start_streaming()


def get_status() -> dict:
    """Get current daemon status."""
    with streaming_lock:
        is_streaming = arecord_proc is not None

    server_available = check_streaming_server()

    return {
        "status": "ok",
        "streaming": is_streaming,
        "server_available": server_available,
        "streaming_host": STREAMING_HOST,
        "streaming_port": STREAMING_PORT,
        "input_method": TEXT_INPUT_METHOD,
        "typed_so_far": typed_so_far if is_streaming else ""
    }


def handle_command(cmd: str) -> dict:
    """Handle a command from the client."""
    cmd = cmd.strip().lower()

    if cmd == "start":
        return start_streaming()
    elif cmd == "stop":
        return stop_streaming()
    elif cmd == "toggle":
        return toggle_streaming()
    elif cmd == "status":
        return get_status()
    elif cmd == "ping":
        return {"status": "ok", "message": "pong"}
    else:
        return {"status": "error", "message": f"Unknown command: {cmd}"}


def handle_client(conn: socket.socket):
    """Handle a client connection."""
    try:
        data = conn.recv(1024).decode("utf-8")
        if data:
            result = handle_command(data)
            conn.sendall(json.dumps(result).encode("utf-8"))
    except Exception as e:
        log(f"Client error: {e}")
    finally:
        conn.close()


def cleanup(signum=None, frame=None):
    """Clean up on exit."""
    global arecord_proc, nc_proc, stop_reader

    log("Shutting down...")

    # Stop any ongoing streaming
    stop_reader.set()

    if arecord_proc:
        arecord_proc.terminate()
        arecord_proc = None

    if nc_proc:
        nc_proc.terminate()
        nc_proc = None

    # Remove socket file
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    sys.exit(0)


def main():
    """Main daemon loop."""
    # Set up signal handlers
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    log(f"Whisper Dictation Daemon (Streaming Mode)")
    log(f"Streaming server: {STREAMING_HOST}:{STREAMING_PORT}")
    log(f"Input method: {TEXT_INPUT_METHOD}")

    # Check streaming server availability (warning only, not fatal)
    if not check_streaming_server():
        log(f"Warning: Streaming server not available at {STREAMING_HOST}:{STREAMING_PORT}")
        log("The server may still be starting up. Dictation will fail until it's ready.")

    # Remove stale socket
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    # Create Unix socket
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(5)

    log(f"Daemon listening on {SOCKET_PATH}")

    try:
        while True:
            conn, _ = server.accept()
            # Handle each client in a thread to avoid blocking
            thread = threading.Thread(target=handle_client, args=(conn,))
            thread.daemon = True
            thread.start()
    except Exception as e:
        log(f"Server error: {e}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
