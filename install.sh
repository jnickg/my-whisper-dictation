#!/bin/bash
# Whisper Dictation Installer for Manjaro

set -e

# Defaults
MODEL="base.en"
INPUT_METHOD="ydotool"

# Parse arguments
show_help() {
    echo "Usage: ./install.sh [OPTIONS]"
    echo
    echo "Options:"
    echo "  --model MODEL    Whisper model to use (default: base.en)"
    echo "                   Options: tiny.en, base.en, small.en, medium.en, large"
    echo "  --input METHOD   Text input method (default: ydotool)"
    echo "                   Options: ydotool, wtype, xdotool"
    echo "  --help           Show this help message"
    echo
    echo "Examples:"
    echo "  ./install.sh                      # Fresh install with defaults"
    echo "  ./install.sh --model small.en     # Install/update with small model"
    echo "  ./install.sh --input xdotool      # Use xdotool (for X11)"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --input)
            INPUT_METHOD="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Prevent running as root (systemctl --user won't work)
if [ "$EUID" -eq 0 ]; then
    echo "Error: Do not run this script with sudo."
    echo "The script will use sudo internally only where needed (pacman)."
    echo
    echo "Run instead:"
    echo "  ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Whisper Dictation Installer ==="
echo "Model: $MODEL"
echo "Input method: $INPUT_METHOD"
echo

# Check for required system packages
echo "Checking system dependencies..."
MISSING_PKGS=""

if ! command -v arecord &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS alsa-utils"
fi

if [ "$INPUT_METHOD" = "ydotool" ] && ! command -v ydotool &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS ydotool"
fi

if [ "$INPUT_METHOD" = "wtype" ] && ! command -v wtype &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS wtype"
fi

if [ "$INPUT_METHOD" = "xdotool" ] && ! command -v xdotool &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS xdotool"
fi

if [ -n "$MISSING_PKGS" ]; then
    echo "Installing missing packages:$MISSING_PKGS"
    sudo pacman -S --needed $MISSING_PKGS
fi

# Setup ydotool if selected
if [ "$INPUT_METHOD" = "ydotool" ]; then
    # Create ydotool user service if it doesn't exist
    if [ ! -f ~/.config/systemd/user/ydotool.service ]; then
        echo "Creating ydotool user service..."
        cat > ~/.config/systemd/user/ydotool.service << 'EOF'
[Unit]
Description=ydotool daemon
Documentation=https://github.com/ReimuNotMoe/ydotool

[Service]
Type=simple
ExecStart=/usr/bin/ydotoold
Restart=on-failure

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
    fi

    # Enable and start ydotool
    if ! systemctl --user is-active --quiet ydotool.service; then
        echo "Enabling ydotool user service..."
        systemctl --user enable --now ydotool.service
    fi
fi

# Check for whisper
echo "Checking for OpenAI Whisper..."
if ! python3 -c "import whisper" &> /dev/null; then
    echo "Installing openai-whisper via pip..."
    pip install --user openai-whisper
fi

# Create directories
echo "Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.config/systemd/user
mkdir -p ~/.cache/whisper

# Install scripts
echo "Installing scripts..."
cp "$SCRIPT_DIR/whisper_dictate_daemon.py" ~/.local/bin/
cp "$SCRIPT_DIR/dictate.py" ~/.local/bin/
chmod +x ~/.local/bin/whisper_dictate_daemon.py
chmod +x ~/.local/bin/dictate.py

# Install systemd service with configured values
echo "Installing systemd service..."
sed -e "s/JNICKG_DICTATE_MODEL=.*/JNICKG_DICTATE_MODEL=$MODEL\"/" \
    -e "s/JNICKG_DICTATE_INPUT_METHOD=.*/JNICKG_DICTATE_INPUT_METHOD=$INPUT_METHOD\"/" \
    "$SCRIPT_DIR/whisper-dictate.service" > ~/.config/systemd/user/whisper-dictate.service

# Reload and enable service
echo "Enabling systemd service..."
systemctl --user daemon-reload
systemctl --user enable whisper-dictate.service

# Restart service (restart instead of start to pick up changes)
echo "Restarting whisper-dictate service..."
systemctl --user restart whisper-dictate.service

# Check PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo
    echo "WARNING: ~/.local/bin is not in your PATH"
    echo "Add this line to your ~/.bashrc or ~/.zshrc:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
fi

echo
echo "=== Installation complete! ==="
echo
echo "Configuration:"
echo "  Model: $MODEL"
echo "  Input: $INPUT_METHOD"
echo
echo "To change settings, run again with options:"
echo "  ./install.sh --model small.en"
echo
echo "Check status: systemctl --user status whisper-dictate.service"
