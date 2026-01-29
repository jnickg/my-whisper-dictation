#!/bin/bash
# Whisper Dictation Uninstaller for Manjaro

set -e

# Prevent running as root (systemctl --user won't work)
if [ "$EUID" -eq 0 ]; then
    echo "Error: Do not run this script with sudo."
    echo
    echo "Run instead:"
    echo "  ./uninstall.sh"
    exit 1
fi

echo "=== Whisper Dictation Uninstaller ==="
echo

# Stop the services if running
echo "Stopping whisper-dictate service..."
systemctl --user stop whisper-dictate.service 2>/dev/null || true

echo "Stopping whisper-streaming-server service..."
systemctl --user stop whisper-streaming-server.service 2>/dev/null || true

# Disable the services
echo "Disabling whisper-dictate service..."
systemctl --user disable whisper-dictate.service 2>/dev/null || true

echo "Disabling whisper-streaming-server service..."
systemctl --user disable whisper-streaming-server.service 2>/dev/null || true

# Remove systemd service files
echo "Removing systemd service files..."
rm -f ~/.config/systemd/user/whisper-dictate.service
rm -rf ~/.config/systemd/user/whisper-dictate.service.d
rm -f ~/.config/systemd/user/whisper-streaming-server.service

# Reload systemd
systemctl --user daemon-reload

# Remove scripts
echo "Removing scripts from ~/.local/bin/..."
rm -f ~/.local/bin/whisper_dictate_daemon.py
rm -f ~/.local/bin/dictate.py

# Remove SimulStreaming installation
echo "Removing SimulStreaming installation..."
rm -rf ~/.local/share/whisper-dictate

# Remove socket and audio files
echo "Cleaning up temporary files..."
rm -f /tmp/jnickg-dictate.sock
rm -f /tmp/jnickg-dictation.wav

# Remove warmup file and venv
rm -f ~/.cache/whisper-dictate/warmup.wav
rm -rf ~/.cache/whisper-dictate/venv
rmdir ~/.cache/whisper-dictate 2>/dev/null || true

echo
echo "=== Core uninstallation complete ==="
echo

# Note about system packages and cache
echo
echo "Note: System packages (alsa-utils, openbsd-netcat, ydotool/wtype/xdotool)"
echo "were not removed. Remove them manually if no longer needed."
echo
echo "Whisper model cache (~/.cache/whisper) was not removed."
echo "Remove manually if desired: rm -rf ~/.cache/whisper"
echo
echo "Uninstallation complete."
