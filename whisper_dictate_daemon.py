#!/usr/bin/env python3
"""
Whisper Dictation Daemon

A systemd-compatible daemon that keeps the Whisper model loaded in memory
and listens on a Unix socket for dictation commands.
"""

import whisper
import subprocess
import os
import signal
import socket
import sys
import threading
import json
import time
import tempfile
from pathlib import Path

# Configuration
SOCKET_PATH = os.environ.get("JNICKG_DICTATE_SOCKET", "/tmp/jnickg-dictate.sock")
AUDIO_FILE = os.environ.get("JNICKG_DICTATE_AUDIO", "/tmp/jnickg-dictation.wav")
MODEL_NAME = os.environ.get("JNICKG_DICTATE_MODEL", "base.en")
TEXT_INPUT_METHOD = os.environ.get("JNICKG_DICTATE_INPUT_METHOD", "ydotool")  # ydotool, wtype, or xdotool

# Global state
model = None
recording_process = None
recording_lock = threading.Lock()


def log(msg: str):
    """Log to stderr for systemd journal."""
    print(msg, file=sys.stderr, flush=True)


def load_model():
    """Load the Whisper model."""
    global model
    log(f"Loading Whisper model: {MODEL_NAME}")
    model = whisper.load_model(MODEL_NAME)
    log("Model loaded successfully")


def type_text(text: str):
    """Type text into the focused window using the configured method."""
    if not text:
        return

    try:
        if TEXT_INPUT_METHOD == "wtype":
            # wtype for Wayland
            subprocess.run(["wtype", "--", text], check=True)
        elif TEXT_INPUT_METHOD == "ydotool":
            # ydotool for Wayland (requires ydotoold)
            subprocess.run(["ydotool", "type", "--", text], check=True)
        elif TEXT_INPUT_METHOD == "xdotool":
            # xdotool for X11
            subprocess.run(["xdotool", "type", "--clearmodifiers", "--", text], check=True)
        else:
            log(f"Unknown input method: {TEXT_INPUT_METHOD}")
    except subprocess.CalledProcessError as e:
        log(f"Failed to type text: {e}")
    except FileNotFoundError:
        log(f"Text input tool not found: {TEXT_INPUT_METHOD}")


def start_recording() -> dict:
    """Start audio recording."""
    global recording_process

    with recording_lock:
        if recording_process is not None:
            return {"status": "error", "message": "Already recording"}

        try:
            # Remove old audio file if it exists
            if os.path.exists(AUDIO_FILE):
                os.remove(AUDIO_FILE)

            # Start recording with arecord (ALSA)
            # 16kHz mono WAV is what Whisper expects
            # -d 300 = max 5 minutes, -q = quiet
            recording_process = subprocess.Popen(
                ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", "300", AUDIO_FILE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            log("Recording started")
            return {"status": "ok", "message": "Recording started"}
        except FileNotFoundError:
            return {"status": "error", "message": "rec (sox) not found"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def stop_recording() -> dict:
    """Stop recording and transcribe."""
    global recording_process

    with recording_lock:
        if recording_process is None:
            return {"status": "error", "message": "Not recording"}

        try:
            # Stop the recording process gracefully with SIGINT
            # (SIGTERM cuts off the buffer, SIGINT lets rec flush)
            recording_process.send_signal(signal.SIGINT)
            # Give rec a moment to flush its audio buffer
            time.sleep(0.5)
            recording_process.wait(timeout=5)
            recording_process = None
            log("Recording stopped")
        except Exception as e:
            recording_process = None
            return {"status": "error", "message": f"Failed to stop recording: {e}"}

    # Transcribe the audio
    if not os.path.exists(AUDIO_FILE):
        return {"status": "error", "message": "No audio file found"}

    try:
        log("Transcribing...")
        result = model.transcribe(AUDIO_FILE, fp16=False)
        text = result["text"].strip()
        log(f"Transcribed: {text}")

        if text:
            type_text(text)
            return {"status": "ok", "message": "Transcribed", "text": text}
        else:
            return {"status": "ok", "message": "No speech detected", "text": ""}
    except Exception as e:
        return {"status": "error", "message": f"Transcription failed: {e}"}


def toggle_recording() -> dict:
    """Toggle recording state."""
    with recording_lock:
        is_recording = recording_process is not None

    if is_recording:
        return stop_recording()
    else:
        return start_recording()


def get_status() -> dict:
    """Get current daemon status."""
    with recording_lock:
        is_recording = recording_process is not None
    return {
        "status": "ok",
        "recording": is_recording,
        "model": MODEL_NAME,
        "input_method": TEXT_INPUT_METHOD
    }


def handle_command(cmd: str) -> dict:
    """Handle a command from the client."""
    cmd = cmd.strip().lower()

    if cmd == "start":
        return start_recording()
    elif cmd == "stop":
        return stop_recording()
    elif cmd == "toggle":
        return toggle_recording()
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
    global recording_process

    log("Shutting down...")

    # Stop any ongoing recording
    if recording_process:
        recording_process.terminate()
        recording_process = None

    # Remove socket file
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    sys.exit(0)


def main():
    """Main daemon loop."""
    # Set up signal handlers
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    # Load the model
    load_model()

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
