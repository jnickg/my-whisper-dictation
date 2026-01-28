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

# Stop the service if running
echo "Stopping whisper-dictate service..."
systemctl --user stop whisper-dictate.service 2>/dev/null || true

# Disable the service
echo "Disabling whisper-dictate service..."
systemctl --user disable whisper-dictate.service 2>/dev/null || true

# Remove systemd service file
echo "Removing systemd service file..."
rm -f ~/.config/systemd/user/whisper-dictate.service
rm -rf ~/.config/systemd/user/whisper-dictate.service.d

# Reload systemd
systemctl --user daemon-reload

# Remove scripts
echo "Removing scripts from ~/.local/bin/..."
rm -f ~/.local/bin/whisper_dictate_daemon.py
rm -f ~/.local/bin/dictate.py

# Remove socket and audio files
echo "Cleaning up temporary files..."
rm -f /tmp/jnickg-dictate.sock
rm -f /tmp/jnickg-dictation.wav

echo
echo "=== Core uninstallation complete ==="
echo

# Note about system packages
echo
echo "Note: System packages (sox, wtype) were not removed."
echo "Remove them manually if no longer needed:"
echo "  sudo pacman -Rs sox wtype"
echo
echo "Uninstallation complete."
