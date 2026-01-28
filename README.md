# Whisper Dictation for Manjaro/KDE Plasma (Wayland)

A speech-to-text dictation system using OpenAI's Whisper model. Press a hotkey to start dictating, press again to transcribe and type into the focused window.

## Features

- **Daemon architecture**: Whisper model stays loaded in memory for fast transcription
- **KDE Plasma Wayland**: Uses `ydotool` for text input
- **Systemd integration**: Runs as a user service, starts on login
- **Simple toggle**: One hotkey to start/stop recording

## Installation

### 1. Install system dependencies

```bash
# Audio recording (alsa-utils) and text input (ydotool)
sudo pacman -S alsa-utils ydotool

# Python and pip (if not already installed)
sudo pacman -S python python-pip

# Enable ydotool daemon
sudo systemctl enable --now ydotool.service

# Add yourself to the input group (required for ydotool)
sudo usermod -aG input $USER
# Log out and back in for group change to take effect
```

### 2. Install OpenAI Whisper

```bash
pip install --user openai-whisper

# Or with pipx for isolation:
# pipx install openai-whisper
```

**Note**: First run will download the model (~140MB for base.en). Larger models provide better accuracy but use more RAM and are slower:

| Model     | Size   | RAM    | Speed   |
|-----------|--------|--------|---------|
| tiny.en   | 39MB   | ~1GB   | Fastest |
| base.en   | 142MB  | ~1GB   | Fast    |
| small.en  | 466MB  | ~2GB   | Medium  |
| medium.en | 1.5GB  | ~5GB   | Slow    |
| large     | 2.9GB  | ~10GB  | Slowest |

### 3. Install the dictation scripts

```bash
# Create local bin directory if it doesn't exist
mkdir -p ~/.local/bin

# Copy the scripts
cp whisper_dictate_daemon.py ~/.local/bin/
cp dictate.py ~/.local/bin/

# Make them executable
chmod +x ~/.local/bin/whisper_dictate_daemon.py
chmod +x ~/.local/bin/dictate.py

# Ensure ~/.local/bin is in your PATH
# Add to ~/.bashrc or ~/.zshrc if not present:
# export PATH="$HOME/.local/bin:$PATH"
```

### 4. Install and enable the systemd service

```bash
# Create user systemd directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy the service file
cp whisper-dictate.service ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload

# Enable the service (starts on login)
systemctl --user enable whisper-dictate.service

# Start the service now
systemctl --user start whisper-dictate.service

# Check status
systemctl --user status whisper-dictate.service
```

### 5. Configure the KDE Plasma hotkey

1. Open **System Settings**
2. Navigate to **Shortcuts** → **Custom Shortcuts**
3. Click **Edit** → **New** → **Global Shortcut** → **Command/URL**
4. Name it "Dictate" (or whatever you prefer)
5. In the **Trigger** tab, click the button and press your desired hotkey (e.g., `Meta+D` or `Ctrl+Alt+D`)
6. In the **Action** tab, enter the command:
   ```
   /home/YOUR_USERNAME/.local/bin/dictate.py toggle
   ```
   (Replace `YOUR_USERNAME` with your actual username)
7. Click **Apply**

Alternatively, use `kwriteconfig5` from the command line:
```bash
# This adds a global shortcut for Meta+D
kwriteconfig5 --file kglobalshortcutsrc --group "dictate.desktop" --key "_k_friendly_name" "Dictate"
kwriteconfig5 --file kglobalshortcutsrc --group "dictate.desktop" --key "toggle" "Meta+D,none,Toggle Dictation"
```

## Usage

1. Focus on any text input (terminal, text editor, browser, etc.)
2. Press your hotkey to **start recording**
3. Speak your text
4. Press the hotkey again to **stop and transcribe**
5. The transcribed text will be typed into the focused window

### Command-line usage

```bash
# Toggle recording (default)
dictate.py

# Explicit commands
dictate.py start   # Start recording
dictate.py stop    # Stop and transcribe
dictate.py toggle  # Toggle recording
dictate.py status  # Check daemon status
dictate.py ping    # Check if daemon is alive
```

## Configuration

Edit the service file to change settings:

```bash
# Edit the service
systemctl --user edit whisper-dictate.service --full
```

Or create an override:

```bash
# Create override directory
mkdir -p ~/.config/systemd/user/whisper-dictate.service.d

# Create override file
cat > ~/.config/systemd/user/whisper-dictate.service.d/override.conf << 'EOF'
[Service]
# Use a larger model for better accuracy
Environment="JNICKG_DICTATE_MODEL=small.en"
EOF

# Reload and restart
systemctl --user daemon-reload
systemctl --user restart whisper-dictate.service
```

### Environment variables

| Variable                    | Default                      | Description                          |
|-----------------------------|------------------------------|--------------------------------------|
| `JNICKG_DICTATE_MODEL`      | `base.en`                    | Whisper model to use                 |
| `JNICKG_DICTATE_SOCKET`     | `/tmp/jnickg-dictate.sock`   | Unix socket path                     |
| `JNICKG_DICTATE_AUDIO`      | `/tmp/jnickg-dictation.wav`  | Temporary audio file path            |
| `JNICKG_DICTATE_INPUT_METHOD`| `ydotool`                   | Text input method (ydotool/wtype/xdotool) |

## Troubleshooting

### Check service logs

```bash
journalctl --user -u whisper-dictate.service -f
```

### Service won't start

1. Make sure whisper is installed: `python3 -c "import whisper; print('OK')"`
2. Check the socket isn't stale: `rm -f /tmp/jnickg-dictate.sock`
3. Verify wtype is installed: `which wtype`

### No audio recorded

1. Check your microphone is working: `arecord -d 3 test.wav && aplay test.wav`
2. Check sox is installed: `which rec`
3. Make sure no other app has exclusive mic access

### Text not appearing

1. For KDE Plasma Wayland, ensure `ydotool` is installed and running:
   - `sudo systemctl status ydotool.service`
   - Your user must be in the `input` group: `groups | grep input`
2. Check the input method setting matches your session type:
   - KDE Plasma Wayland: `ydotool`
   - Other Wayland: `wtype` or `ydotool`
   - X11: `xdotool`
3. Some applications (Electron apps, games) may not accept simulated input

### Model loading is slow

The first time you run the daemon after a reboot, it needs to load the model into memory. This takes a few seconds. Subsequent transcriptions are fast.

To pre-warm the model on login, the systemd service handles this automatically.

## Uninstallation

Run the uninstall script:

```bash
./uninstall.sh
```

This will:
- Stop and disable the systemd service
- Remove the service file and scripts
- Clean up temporary files
- Optionally uninstall openai-whisper (prompts you)

## License

MIT
