#!/bin/bash
# Whisper Dictation Installer for Manjaro

set -e

# Defaults
MODEL="base.en"
INPUT_METHOD="ydotool"
STREAMING_PORT="43001"
STREAMING_HOST="localhost"
CLEAN_VENV=false

# Parse arguments
show_help() {
    echo "Usage: ./install.sh [OPTIONS]"
    echo
    echo "Options:"
    echo "  --model MODEL    Whisper model to use (default: base.en)"
    echo "                   Options: tiny.en, base.en, small.en, medium.en, large"
    echo "  --input METHOD   Text input method (default: ydotool)"
    echo "                   Options: ydotool, wtype, xdotool"
    echo "  --port PORT      Streaming server port (default: 43001)"
    echo "  --clean          Remove and recreate the Python virtual environment"
    echo "  --help           Show this help message"
    echo
    echo "Examples:"
    echo "  ./install.sh                      # Fresh install with defaults"
    echo "  ./install.sh --model small.en     # Install/update with small model"
    echo "  ./install.sh --input xdotool      # Use xdotool (for X11)"
    echo "  ./install.sh --clean              # Reinstall with fresh venv"
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
        --port)
            STREAMING_PORT="$2"
            shift 2
            ;;
        --clean)
            CLEAN_VENV=true
            shift
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
echo "Streaming port: $STREAMING_PORT"
echo

# Check for required system packages
echo "Checking system dependencies..."
MISSING_PKGS=""

if ! command -v arecord &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS alsa-utils"
fi

if ! command -v nc &> /dev/null; then
    MISSING_PKGS="$MISSING_PKGS openbsd-netcat"
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

# Create directories
echo "Creating directories..."
mkdir -p ~/.local/bin
mkdir -p ~/.config/systemd/user
mkdir -p ~/.cache/whisper
mkdir -p ~/.cache/whisper-dictate
mkdir -p ~/.cache/torch
mkdir -p ~/.cache/silero-vad-versions
mkdir -p ~/.local/share/whisper-dictate

# Install SimulStreaming
echo "Installing SimulStreaming..."
if [ -d "$SCRIPT_DIR/SimulStreaming" ]; then
    rm -rf ~/.local/share/whisper-dictate/SimulStreaming
    cp -r "$SCRIPT_DIR/SimulStreaming" ~/.local/share/whisper-dictate/SimulStreaming
else
    echo "Error: SimulStreaming directory not found in $SCRIPT_DIR"
    echo "Make sure to clone with submodules: git clone --recurse-submodules"
    exit 1
fi

# Create virtual environment for SimulStreaming
VENV_DIR="$HOME/.cache/whisper-dictate/venv"
if [ -d "$VENV_DIR" ] && [ "$CLEAN_VENV" = false ]; then
    echo "Virtual environment already exists at $VENV_DIR (use --clean to recreate)"
else
    echo "Creating virtual environment at $VENV_DIR..."
    if [ -d "$VENV_DIR" ]; then
        echo "Removing existing venv..."
        rm -rf "$VENV_DIR"
    fi
    python3 -m venv "$VENV_DIR"

    # Install SimulStreaming dependencies into venv
    echo "Installing SimulStreaming dependencies into venv..."
    source "$VENV_DIR/bin/activate"

    pip install --upgrade pip
    pip install librosa torchaudio torch tqdm tiktoken

    # Install triton on Linux x86_64 only
    if [ "$(uname -s)" = "Linux" ] && [ "$(uname -m)" = "x86_64" ]; then
        pip install 'triton>=2.0.0'
    fi

    # Install openai-whisper (needed by SimulStreaming)
    pip install openai-whisper

    deactivate
    echo "Virtual environment setup complete."
fi

# Generate warmup WAV file (1 second of silence at 16kHz mono)
echo "Generating warmup audio file..."
WARMUP_FILE="$HOME/.cache/whisper-dictate/warmup.wav"
if [ ! -f "$WARMUP_FILE" ]; then
    python3 -c "
import wave
import struct

# Generate 1 second of silence at 16kHz mono
sample_rate = 16000
duration = 1  # seconds
num_samples = sample_rate * duration

with wave.open('$WARMUP_FILE', 'w') as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)  # 16-bit
    wav_file.setframerate(sample_rate)
    # Write silence (zeros)
    wav_file.writeframes(struct.pack('<' + 'h' * num_samples, *([0] * num_samples)))
print('Warmup file created: $WARMUP_FILE')
"
fi

# Install scripts
echo "Installing scripts..."
cp "$SCRIPT_DIR/whisper_dictate_daemon.py" ~/.local/bin/
cp "$SCRIPT_DIR/dictate.py" ~/.local/bin/
chmod +x ~/.local/bin/whisper_dictate_daemon.py
chmod +x ~/.local/bin/dictate.py

# Install streaming server systemd service
echo "Installing streaming server systemd service..."
sed -e "s/JNICKG_DICTATE_MODEL=.*/JNICKG_DICTATE_MODEL=$MODEL\"/" \
    -e "s/JNICKG_DICTATE_STREAMING_PORT=.*/JNICKG_DICTATE_STREAMING_PORT=$STREAMING_PORT\"/" \
    "$SCRIPT_DIR/whisper-streaming-server.service" > ~/.config/systemd/user/whisper-streaming-server.service

# Install main dictation systemd service with configured values
echo "Installing dictation daemon systemd service..."
sed -e "s/JNICKG_DICTATE_MODEL=.*/JNICKG_DICTATE_MODEL=$MODEL\"/" \
    -e "s/JNICKG_DICTATE_INPUT_METHOD=.*/JNICKG_DICTATE_INPUT_METHOD=$INPUT_METHOD\"/" \
    -e "s/JNICKG_DICTATE_STREAMING_PORT=.*/JNICKG_DICTATE_STREAMING_PORT=$STREAMING_PORT\"/" \
    "$SCRIPT_DIR/whisper-dictate.service" > ~/.config/systemd/user/whisper-dictate.service

# Reload and enable services
echo "Enabling systemd services..."
systemctl --user daemon-reload
systemctl --user enable whisper-streaming-server.service
systemctl --user enable whisper-dictate.service

# Restart services (restart instead of start to pick up changes)
echo "Restarting streaming server..."
systemctl --user restart whisper-streaming-server.service

echo "Waiting for streaming server to initialize..."
sleep 3

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
echo "  Streaming port: $STREAMING_PORT"
echo
echo "To change settings, run again with options:"
echo "  ./install.sh --model small.en"
echo
echo "Check status:"
echo "  systemctl --user status whisper-streaming-server.service"
echo "  systemctl --user status whisper-dictate.service"
echo
echo "Test streaming server:"
echo "  nc -z localhost $STREAMING_PORT && echo 'Server OK'"
