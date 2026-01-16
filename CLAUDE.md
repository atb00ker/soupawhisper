# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SoupaWhisper is a push-to-talk voice dictation tool for Linux using faster-whisper. It's a single-file Python application that records audio when a hotkey is held, transcribes it using Whisper, and automatically types the result into the active input field.

## Architecture

### Single-File Design

The entire application logic resides in `dictate.py` (270 lines). Key components:

- **Dictation class**: Main application controller that manages the recording lifecycle, model loading, and keyboard listener
- **Model loading**: Happens asynchronously on startup in a background thread to avoid blocking the UI
- **Recording pipeline**: Uses auto-detected audio backend (parecord/pw-record/arecord) for audio capture → temporary WAV file → faster-whisper transcription → auto-detected clipboard tool (wl-copy/xclip) + typing tool (wtype/ydotool/xdotool)
- **Configuration**: INI-based config loaded from `~/.config/soupawhisper/config.ini` with fallback defaults

### Key Patterns

1. **Threading model**: Model loads in background thread (line 87), main thread runs keyboard listener
2. **Process management**: Recording uses subprocess.Popen for arecord, allows clean termination on key release
3. **Desktop integration**: Uses Linux CLI tools (xclip, xdotool, notify-send) for clipboard, typing, and notifications
4. **Configuration cascade**: Hard-coded defaults → config.ini → command-line args (only --version currently)

### External Dependencies

- **System tools** (checked in `check_dependencies()`): Audio backend (parecord, pw-record, or arecord - auto-detected), clipboard tool (wl-copy or xclip - auto-detected), typing tool (wtype, ydotool, or xdotool - auto-detected), notify-send
- **Python packages**: faster-whisper (Whisper inference), pynput (keyboard hooks)
- **Runtime requirements**: X11 or Wayland display server, audio backend (PipeWire/PulseAudio/ALSA)

## Development Commands

### Setup

```bash
# Install system dependencies (see install.sh for distribution-specific commands)
./install.sh

# Or manually with Poetry
poetry install
```

### Running

```bash
# Run directly (manual mode)
poetry run python dictate.py

# Show version
poetry run python dictate.py --version
```

### Testing

Currently no automated tests. Manual testing workflow:

1. Run `poetry run python dictate.py`
2. Hold F12, speak, release
3. Verify text appears in active input and clipboard
4. Check terminal output for errors

### Service Management

```bash
# Install as systemd user service (via install.sh)
./install.sh  # Select 'y' for systemd

# Control service
systemctl --user start/stop/restart/status soupawhisper
journalctl --user -u soupawhisper -f  # Live logs
```

## Configuration

Located at `~/.config/soupawhisper/config.ini`:

- **[whisper]**: model (tiny.en to large-v3), device (cpu/cuda), compute_type (int8/float16)
- **[hotkey]**: key name (f12, scroll_lock, pause, etc.) - mapped via `get_hotkey()` at line 55
- **[behavior]**: auto_type (bool), notifications (bool)

Config is loaded once at startup (line 52). Changes require restart.

## Common Patterns

### Adding new hotkeys

Modify `get_hotkey()` function (line 55). Must map to pynput.keyboard.Key enum or KeyCode.

### Adding transcription options

faster-whisper parameters are hardcoded in `stop_recording()` at line 170 (beam_size=5, vad_filter=True). Add config options if needed.

### Changing notification behavior

All notifications go through `Dictation.notify()` (line 104). Respects NOTIFICATIONS config flag.

### Error handling for GPU/CUDA

Model loading errors are caught at line 97-102. Special cuDNN error hints added for common issues.

## Platform Constraints

- **Linux-only**: Uses Linux audio backends (PipeWire/PulseAudio/ALSA) and display server tools (Wayland/X11)
- **Wayland support**: Auto-detects wl-copy/wtype (Wayland) or xclip/xdotool (X11)
- **Audio format**: Hardcoded to 16kHz mono S16_LE - Whisper's expected format
- **Audio backends**: Auto-detects parecord > pw-record > arecord in priority order
- **Clipboard tools**: Auto-detects wl-copy > xclip in priority order
- **Typing tools**: Auto-detects wtype > ydotool > xdotool in priority order
- **Temporary files**: Uses tempfile.NamedTemporaryFile for recordings, cleaned up in finally block

## Installation Script

`install.sh` is a Bash script that:

1. Detects package manager (apt/dnf/pacman/zypper)
2. Installs system dependencies
3. Runs `poetry install`
4. Copies config.example.ini to ~/.config/soupawhisper/
5. Optionally generates and installs systemd user service with correct DISPLAY/XAUTHORITY env vars

When modifying dependencies, update both `install.sh` package lists and `check_dependencies()` in dictate.py.

## Audio Backend Selection

The application auto-detects available audio recording tools in priority order:

1. **parecord** (PulseAudio/PipeWire compatibility layer) - preferred
   - Works on both PulseAudio and PipeWire systems
   - Most compatible across distributions
   - Package: pulseaudio-utils
   - Command: `parecord --rate=16000 --channels=1 --format=s16le --file-format=wav output.wav`

2. **pw-record** (native PipeWire) - secondary
   - Native PipeWire tool
   - Better integration on PipeWire-only systems
   - Package: pipewire-bin (Debian), pipewire-utils (Fedora)
   - Command: `pw-record --rate=16000 --channels=1 --format=s16 output.wav`

3. **arecord** (ALSA) - fallback
   - Works on systems without PipeWire/PulseAudio
   - Older but universally available
   - Package: alsa-utils
   - Command: `arecord -f S16_LE -r 16000 -c 1 -t wav output.wav`

Users can override auto-detection by setting `backend = <name>` in `[audio]` section of config.ini.

Detection logic is in `detect_audio_backend()` function (line 92), and command builders are `build_arecord_command()`, `build_parecord_command()`, and `build_pwrecord_command()` (lines 57-89).

## Wayland/X11 Tool Selection

The application auto-detects available clipboard and typing tools based on what's installed:

### Clipboard Tools

Priority order: **wl-copy** > **xclip**

1. **wl-copy** (Wayland) - preferred
   - Package: wl-clipboard
   - Command: `wl-copy` (stdin → clipboard)
   - Works on: Wayland compositors (GNOME, KDE Plasma, Sway, Hyprland, etc.)

2. **xclip** (X11) - fallback
   - Package: xclip
   - Command: `xclip -selection clipboard` (stdin → clipboard)
   - Works on: X11 display servers

### Typing Tools

Priority order: **wtype** > **ydotool** > **xdotool**

1. **wtype** (Wayland) - preferred
   - Package: wtype
   - Command: `wtype <text>`
   - Works on: Wayland compositors
   - Lightweight, no daemon required

2. **ydotool** (Wayland) - secondary
   - Package: ydotool
   - Command: `ydotool type <text>`
   - Works on: Wayland compositors
   - Requires ydotoold daemon running

3. **xdotool** (X11) - fallback
   - Package: xdotool
   - Command: `xdotool type --clearmodifiers <text>`
   - Works on: X11 display servers

Detection logic is in `detect_clipboard_tool()` (line 128) and `detect_typing_tool()` (line 137). The application automatically uses the detected tools in `stop_recording()` method.
