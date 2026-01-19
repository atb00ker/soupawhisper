# SoupaWhisper

A simple push-to-talk voice dictation tool for Linux using faster-whisper. Hold a key to record, release to transcribe, and it automatically copies to clipboard and types into the active input.

## Requirements

- Python 3.10+
- Poetry
- Linux with X11 or Wayland
- Audio: PipeWire/PulseAudio/ALSA

## Supported Distros

- KDE Plasma / Debian (apt)

## Installation

```bash
git clone https://github.com/atb00ker/soupawhisper.git
cd soupawhisper
chmod +x install.sh
./install.sh
```

The installer will:

1. Detect your package manager
2. Install system dependencies
3. Install Python dependencies via Poetry
4. Set up the config file
5. Optionally install as a systemd service

### Manual Installation

```bash
# Ubuntu/Debian (modern systems with PipeWire + Wayland/X11)
sudo apt install pipewire pipewire-pulse pulseaudio-utils wl-clipboard xclip wtype xdotool libnotify-bin

# Ubuntu/Debian (older systems with ALSA + X11)
sudo apt install alsa-utils xclip xdotool libnotify-bin

# Fedora (PipeWire default on 34+, supports Wayland)
sudo dnf install pipewire pipewire-pulseaudio pulseaudio-utils wl-clipboard xclip wtype xdotool libnotify

# Arch
sudo pacman -S pipewire pipewire-pulse pulseaudio wl-clipboard xclip wtype xdotool libnotify

# Then install Python deps
poetry install
```

**Note for KDE Plasma Wayland users:**

For auto-typing to work with native Wayland apps on KDE, install **dotool**:

```bash
# Install Rust/Cargo if not already installed
sudo apt install cargo

# Add your user to the input group (required for /dev/uinput access)
sudo usermod -aG input $USER
# Log out and log back in for the group change to take effect

# Install dotool
cargo install dotool

# Start dotoold daemon (doesn't require root!)
dotoold &

# Or enable as systemd user service
systemctl --user enable --now dotoold
```

### GPU Support (Optional)

For NVIDIA GPU acceleration, install cuDNN 9:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install libcudnn9-cuda-12
```

Then edit `~/.config/soupawhisper/config.ini`:

```ini
device = cuda
compute_type = float16
```

## Usage

```bash
poetry run python dictate.py
```

- Hold **F12** to record
- Release to transcribe → copies to clipboard and types into active input
- Press **Ctrl+C** to quit (when running manually)

### Model Downloading

For a better experience, you can download the Whisper model before running the main script using the included standalone downloader. This allows you to see the download progress.

```bash
# Download using settings from config.ini
poetry run python model_downloader.py

# Download a specific model to CPU
poetry run python model_downloader.py --model base.en --device cpu

# Download a specific model to GPU (requires cuDNN)
poetry run python model_downloader.py --model small --device cuda
```

## Run as a systemd Service

The installer can set this up automatically. If you skipped it, run:

```bash
./install.sh  # Select 'y' when prompted for systemd
```

### Service Commands

```bash
systemctl --user start soupawhisper     # Start
systemctl --user stop soupawhisper      # Stop
systemctl --user restart soupawhisper   # Restart
systemctl --user status soupawhisper    # Status
journalctl --user -u soupawhisper -f    # View logs
```

### If the service can't access your display / hotkey fails

If you see errors like `failed to acquire X connection` / `Authorization required` from `pynput`, your systemd user service isn't inheriting the right GUI session environment (X11/Wayland).

You have two options:

- **Option A (recommended for reliability): signal trigger mode**

Run SoupaWhisper without a GUI keyboard hook and toggle recording via `SIGUSR1`:

```bash
# Update ExecStart to include:
#   ... dictate.py --trigger signal
systemctl --user daemon-reload
systemctl --user restart soupawhisper

# Toggle recording (start/stop+transcribe)
systemctl --user kill -s USR1 soupawhisper
```

- **Option B: fix GUI environment for the service**

Ensure the unit has correct values for `DISPLAY`/`XAUTHORITY` (X11) and `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` (common for Wayland + notifications). Re-run `./install.sh` or edit `~/.config/systemd/user/soupawhisper.service`.

## Configuration

Edit `~/.config/soupawhisper/config.ini`:

```ini
[whisper]
# Model size: tiny.en, base.en, small.en, medium.en, large-v3
model = base.en

# Device: cpu or cuda (cuda requires cuDNN)
device = cpu

# Compute type: int8 for CPU, float16 for GPU
compute_type = int8

[hotkey]
# Key to hold for recording: f12, scroll_lock, pause, etc.
key = f12

[behavior]
# Type text into active input field
auto_type = true

# Show desktop notification
notifications = true

[audio]
# Audio backend: auto (auto-detect), parecord, pw-record, or arecord
# Default: auto (recommended)
# backend = auto
```

Create the config directory and file if it doesn't exist:

```bash
mkdir -p ~/.config/soupawhisper
cp /path/to/soupawhisper/config.example.ini ~/.config/soupawhisper/config.ini
```

## Troubleshooting

**No audio recording:**

```bash
# Check which audio backends are available
which parecord pw-record arecord

# Test PipeWire/PulseAudio recording (if parecord is available)
parecord --rate=16000 --channels=1 --format=s16le test.wav
# Press Ctrl+C after a few seconds
aplay test.wav

# Test native PipeWire recording (if pw-record is available)
pw-record --rate=16000 --channels=1 --format=s16 test.wav
# Press Ctrl+C after a few seconds
aplay test.wav

# Test ALSA recording (if arecord is available)
arecord -d 3 test.wav && aplay test.wav

# Check your input device (ALSA)
arecord -l
```

**Force a specific audio backend:**

Edit `~/.config/soupawhisper/config.ini` and add:

```ini
[audio]
backend = parecord  # or pw-record, or arecord
```

**KDE Plasma Wayland - Auto-typing not working:**

KDE Plasma Wayland (KWin) doesn't support the virtual-keyboard protocol that wtype uses. xdotool only works with X11 apps via XWayland.

**Solution:** Install dotool for native Wayland app support:

```bash
# Install dotool (no root required!)
cargo install dotool
dotoold &

# Then restart SoupaWhisper
systemctl --user restart soupawhisper
```

**Wayland clipboard/typing not working:**

```bash
# Check which display server you're using
echo $XDG_SESSION_TYPE  # Should show "wayland" or "x11"

# Test Wayland clipboard (wl-clipboard)
echo "test" | wl-copy
wl-paste

# Test Wayland typing tools
# Option 1: wtype (simple, no daemon required)
wtype "test text"

# Option 2: dotool (no root required, best for KDE)
# First, check if daemon is running
pgrep dotoold

# If not running, start it
dotoold &

# Then test
echo "type test text" | dotool

# For X11, use xclip and xdotool instead
```

**Permission issues with keyboard:**

```bash
sudo usermod -aG input $USER
# Then log out and back in
```

**cuDNN errors with GPU:**

```text
Unable to load any of {libcudnn_ops.so.9...}
```

Install cuDNN 9 (see GPU Support section above) or switch to CPU mode.

## Model Sizes

| Model | Size | Speed | Accuracy |
| :--- | :--- | :--- | :--- |
| **tiny.en** | ~75MB | Fastest | Basic |
| **base.en** | ~150MB | Fast | Good |
| **small.en** | ~500MB | Medium | Better |
| **medium.en** | ~1.5GB | Slower | Great |
| **large-v3** | ~3GB | Slowest | Best |

For dictation, `base.en` or `small.en` is usually the sweet spot.
