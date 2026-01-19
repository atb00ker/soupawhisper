#!/usr/bin/env python3
"""
SoupaWhisper - Voice dictation tool using faster-whisper.
Hold the hotkey to record, release to transcribe and copy to clipboard.
"""

import argparse
import configparser
import subprocess
import tempfile
import threading
import signal
import sys
import os
import time
from pathlib import Path
from typing import Optional, Any

from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions

__version__ = "0.1.0"

# Load configuration
CONFIG_PATH = Path.home() / ".config" / "soupawhisper" / "config.ini"


def load_config():
    config = configparser.ConfigParser()

    # Defaults
    defaults = {
        "model": "base.en",
        "device": "cpu",
        "compute_type": "int8",
        "key": "f9",
        "auto_type": "true",
        "notifications": "true",
        "audio_backend": "auto",
        "preferred_keyboard": "",
    }

    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)

    return {
        "model": config.get("whisper", "model", fallback=defaults["model"]),
        "device": config.get("whisper", "device", fallback=defaults["device"]),
        "compute_type": config.get(
            "whisper", "compute_type", fallback=defaults["compute_type"]
        ),
        "key": config.get("hotkey", "key", fallback=defaults["key"]),
        "auto_type": config.getboolean("behavior", "auto_type", fallback=True),
        "notifications": config.getboolean("behavior", "notifications", fallback=True),
        "audio_backend": config.get(
            "audio", "backend", fallback=defaults["audio_backend"]
        ),
        "preferred_keyboard": config.get(
            "keyboard", "preferred_device", fallback=defaults["preferred_keyboard"]
        ),
    }


CONFIG = load_config()


def build_arecord_command(output_file):
    """Build arecord command with required audio format."""
    return [
        "arecord",
        "-f",
        "S16_LE",  # Format: 16-bit little-endian
        "-r",
        "16000",  # Sample rate: 16kHz (what Whisper expects)
        "-c",
        "1",  # Mono
        "-t",
        "wav",
        output_file,
    ]


def build_parecord_command(output_file):
    """Build parecord command with required audio format."""
    return [
        "parecord",
        "--rate=16000",
        "--channels=1",
        "--format=s16le",
        "--file-format=wav",
        output_file,
    ]


def build_pwrecord_command(output_file):
    """Build pw-record command with required audio format."""
    return ["pw-record", "--rate=16000", "--channels=1", "--format=s16", output_file]


def detect_audio_backend():
    """Detect available audio recording backend with optional config override."""
    config_backend = CONFIG.get("audio_backend", "auto")

    # Check for config override
    if config_backend != "auto":
        backend_map = {
            "parecord": ("parecord", build_parecord_command),
            "pw-record": ("pw-record", build_pwrecord_command),
            "arecord": ("arecord", build_arecord_command),
        }
        if config_backend in backend_map:
            cmd_name, builder = backend_map[str(config_backend)]
            if subprocess.run(["which", cmd_name], capture_output=True).returncode == 0:
                return (cmd_name, builder)
            print(
                f"Warning: Configured backend '{config_backend}' not found, using auto-detection"
            )

    # Auto-detection priority: parecord > pw-record > arecord
    for cmd_name, builder in [
        ("parecord", build_parecord_command),
        ("pw-record", build_pwrecord_command),
        ("arecord", build_arecord_command),
    ]:
        if subprocess.run(["which", cmd_name], capture_output=True).returncode == 0:
            return (cmd_name, builder)

    return (None, None)


AUDIO_BACKEND, AUDIO_COMMAND_BUILDER = detect_audio_backend()


def detect_clipboard_tool():
    """Detect available clipboard tool (Wayland only)."""
    # Only support wl-copy for Wayland
    if subprocess.run(["which", "wl-copy"], capture_output=True).returncode == 0:
        return "wl-copy"
    return None


def is_dotoold_running():
    """Check if dotoold daemon is running."""
    result = subprocess.run(["pgrep", "-x", "dotoold"], capture_output=True)
    return result.returncode == 0


def is_kwin_wayland():
    """Check if running under KDE Plasma Wayland (KWin)."""
    result = subprocess.run(["pgrep", "-x", "kwin_wayland"], capture_output=True)
    return result.returncode == 0


def detect_typing_tool():
    """Detect available typing tool (Wayland only - dotool or wtype)."""
    # KDE Plasma Wayland (KWin) doesn't fully support virtual-keyboard protocol
    # Prefer dotool for KDE Wayland
    if is_kwin_wayland():
        # Check dotool with daemon
        if subprocess.run(["which", "dotool"], capture_output=True).returncode == 0:
            if is_dotoold_running():
                print(
                    "Detected KDE Plasma Wayland - using dotool (Wayland apps supported)"
                )
                return "dotool"
            else:
                # Try to auto-start dotoold
                print("Warning: dotool found but dotoold daemon is not running.")
                print("Attempting to start dotoold...")
                try:
                    # Start dotoold as background process
                    subprocess.Popen(
                        ["dotoold"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    # Wait briefly for daemon to start
                    time.sleep(0.2)
                    # Check if it started successfully
                    if is_dotoold_running():
                        print(
                            "Successfully started dotoold - using dotool (Wayland apps supported)"
                        )
                        print(
                            "Note: For persistence, enable dotoold as a systemd user service:"
                        )
                        print("  systemctl --user enable --now dotoold")
                        return "dotool"
                    else:
                        print("Failed to start dotoold.")
                except Exception as e:
                    print(f"Failed to start dotoold: {e}")
                    print(
                        "Hint: Start dotoold manually with 'dotoold' or enable as a service"
                    )

    # Try wtype for other Wayland compositors (doesn't work on KDE)
    if subprocess.run(["which", "wtype"], capture_output=True).returncode == 0:
        if not is_kwin_wayland():  # wtype doesn't work on KDE
            return "wtype"

    # Try dotool as fallback
    if subprocess.run(["which", "dotool"], capture_output=True).returncode == 0:
        if is_dotoold_running():
            return "dotool"
        else:
            print("Warning: dotool found but dotoold daemon is not running.")
            print("Attempting to start dotoold...")
            try:
                subprocess.Popen(
                    ["dotoold"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                time.sleep(0.2)
                if is_dotoold_running():
                    print("Successfully started dotoold.")
                    print(
                        "Note: For persistence, enable as service: systemctl --user enable --now dotoold"
                    )
                    return "dotool"
                else:
                    print("Failed to start dotoold.")
                    print(
                        "Hint: Start it manually with 'dotoold' or enable as a service"
                    )
            except Exception as e:
                print(f"Failed to start dotoold: {e}")
                print("Hint: Start it manually with 'dotoold' or enable as a service")

    return None


CLIPBOARD_TOOL = detect_clipboard_tool()
TYPING_TOOL = detect_typing_tool()


def _load_evdev_keyboard(key_name):
    """
    Load evdev for direct keyboard input on Wayland.

    evdev reads directly from /dev/input/event* devices, which works on Wayland.
    Requires user to be in 'input' group.

    Returns a list of all suitable keyboard devices and the target key code.
    This allows monitoring all keyboards simultaneously.
    """
    try:
        from evdev import InputDevice, list_devices, categorize, ecodes
    except ImportError as e:
        raise ImportError(
            f"evdev is required for Wayland keyboard support: {e}\n"
            "Install with: pip install evdev\n"
            "Also ensure your user is in the 'input' group: sudo usermod -aG input $USER"
        )

    # Find keyboard devices
    devices = [InputDevice(path) for path in list_devices()]

    # Filter for keyboard devices and exclude virtual ones
    virtual_keywords = ["dotool", "uinput", "virtual", "test device"]
    keyboards = []

    for dev in devices:
        # Check if device has keyboard capabilities
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            # Check if it's a virtual device
            name_lower = dev.name.lower()
            is_virtual = any(keyword in name_lower for keyword in virtual_keywords)

            if not is_virtual:
                # Count available keys to prefer physical keyboards (they have more keys)
                key_codes = caps.get(ecodes.EV_KEY, [])
                keyboards.append((dev, len(key_codes)))

    if not keyboards:
        # List all available devices for debugging
        print("Available input devices:")
        for dev in devices:
            print(f"  - {dev.name} ({dev.path})")
        raise RuntimeError(
            "No suitable keyboard devices found. Make sure you have read access to /dev/input/event*"
        )

    # Check if user has a preferred keyboard device in config
    preferred_keyboard_name = str(CONFIG.get("preferred_keyboard", "")).lower()

    # Sort by: 1) preferred device (if specified), 2) devices with "keyboard" in name, 3) number of keys
    def sort_key(device_tuple):
        dev, key_count = device_tuple
        is_preferred = (
            preferred_keyboard_name and preferred_keyboard_name in dev.name.lower()
        )
        has_keyboard_in_name = "keyboard" in dev.name.lower()
        # Return tuple: (is_preferred, has_keyboard, -key_count) for descending sort
        # Preferred devices come first, then devices with "keyboard" in name, then sorted by key count
        return (not is_preferred, not has_keyboard_in_name, -key_count)

    keyboards.sort(key=sort_key)

    # Map key name to evdev key code
    key_map = {
        "f1": ecodes.KEY_F1,
        "f2": ecodes.KEY_F2,
        "f3": ecodes.KEY_F3,
        "f4": ecodes.KEY_F4,
        "f5": ecodes.KEY_F5,
        "f6": ecodes.KEY_F6,
        "f7": ecodes.KEY_F7,
        "f8": ecodes.KEY_F8,
        "f9": ecodes.KEY_F9,
        "f10": ecodes.KEY_F10,
        "f11": ecodes.KEY_F11,
        "f12": ecodes.KEY_F12,
    }

    key_name_lower = key_name.lower()
    if key_name_lower not in key_map:
        raise ValueError(f"Unsupported key for evdev: {key_name}")

    target_key = key_map[key_name_lower]

    # Return all keyboard devices (not just one) so we can monitor all of them
    keyboard_devices = [dev for dev, _ in keyboards]

    # Debug output
    print(f"Found {len(keyboard_devices)} keyboard device(s) - monitoring ALL of them:")
    for dev in keyboard_devices[:10]:  # Show top 10
        has_kb = " (has 'keyboard' in name)" if "keyboard" in dev.name.lower() else ""
        print(f"  - {dev.name}{has_kb}")
    if len(keyboard_devices) > 10:
        print(f"  ... and {len(keyboard_devices) - 10} more")

    print(f"Monitoring for {key_name.upper()} key on all keyboards")

    return (keyboard_devices, target_key)


MODEL_SIZE = CONFIG["model"]
DEVICE = CONFIG["device"]
COMPUTE_TYPE = CONFIG["compute_type"]
AUTO_TYPE = CONFIG["auto_type"]
NOTIFICATIONS = CONFIG["notifications"]


class Dictation:
    def __init__(self):
        self.recording = False
        self.record_process: Optional[subprocess.Popen[Any]] = None
        self.temp_file: Optional[Any] = None
        self.model: Optional[WhisperModel] = None
        self.model_loaded = threading.Event()
        self.model_error: Optional[str] = None
        self.running = True

        # Check audio backend availability
        if AUDIO_BACKEND is None:
            print("ERROR: No audio recording backend found!")
            print("Please install one of: parecord, pw-record, or arecord")
            sys.exit(1)

        # Check clipboard tool availability
        if CLIPBOARD_TOOL is None:
            print("ERROR: No clipboard tool found!")
            print("Please install wl-copy: sudo apt install wl-clipboard")
            sys.exit(1)

        # Check typing tool availability if auto-typing is enabled
        if AUTO_TYPE and TYPING_TOOL is None:
            print("ERROR: No typing tool found!")
            print(
                "Please install one of: wtype (sudo apt install wtype) or dotool (cargo install dotool)"
            )
            sys.exit(1)

        # Load model in background
        print(f"Audio backend: {AUDIO_BACKEND}")
        print(f"Clipboard tool: {CLIPBOARD_TOOL}")
        if AUTO_TYPE:
            print(f"Typing tool: {TYPING_TOOL}")
        print(f"Loading Whisper model ({MODEL_SIZE})...")
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            self.model = WhisperModel(
                str(MODEL_SIZE), device=str(DEVICE), compute_type=str(COMPUTE_TYPE)
            )
            self.model_loaded.set()
            hotkey_name = str(CONFIG["key"]).upper()
            print(f"Model loaded. Ready for dictation!")
            print(f"Hold [{hotkey_name}] to record, release to transcribe.")
            print("Press Ctrl+C to quit.")
        except Exception as e:
            self.model_error = str(e)
            self.model_loaded.set()
            print(f"Failed to load model: {e}")
            if "cudnn" in str(e).lower() or "cuda" in str(e).lower():
                print(
                    "Hint: Try setting device = cpu in your config, or install cuDNN."
                )

    def notify(self, title, message, icon="dialog-information", timeout=2000):
        """Send a desktop notification."""
        if not NOTIFICATIONS:
            return
        subprocess.run(
            [
                "notify-send",
                "-a",
                "SoupaWhisper",
                "-i",
                icon,
                "-t",
                str(timeout),
                "-h",
                "string:x-canonical-private-synchronous:soupawhisper",
                title,
                message,
            ],
            capture_output=True,
        )

    def start_recording(self):
        if self.recording or self.model_error:
            return

        self.recording = True
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self.temp_file.close()

        # Build command for detected audio backend
        if AUDIO_COMMAND_BUILDER:
            command = AUDIO_COMMAND_BUILDER(self.temp_file.name)  # type: ignore[union-attr]
        else:
            print("ERROR: Audio command builder not found!")
            return

        self.record_process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # Small delay to ensure audio buffer is ready and first words aren't lost
        time.sleep(0.05)
        print(f"Recording with {AUDIO_BACKEND}...")
        hotkey_name = str(CONFIG["key"]).upper()
        self.notify(
            "Recording...",
            f"Release {hotkey_name} when done",
            "audio-input-microphone",
            30000,
        )

    def stop_recording(self):
        if not self.recording:
            return

        self.recording = False

        if self.record_process:
            # Send SIGINT (like Ctrl+C) to parecord/pw-record for clean termination
            # This ensures the WAV file header is properly written
            try:
                self.record_process.send_signal(signal.SIGINT)
            except (ProcessLookupError, OSError):
                # Process already terminated
                pass

            # Wait for process to finish (with timeout)
            try:
                self.record_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop
                self.record_process.kill()
                self.record_process.wait()

            self.record_process = None

            # Small delay to ensure file is flushed to disk
            time.sleep(0.1)

        print("Transcribing...")
        self.notify(
            "Transcribing...", "Processing your speech", "emblem-synchronizing", 30000
        )

        # Wait for model if not loaded yet
        self.model_loaded.wait()

        if self.model_error:
            print(f"Cannot transcribe: model failed to load")
            self.notify("Error", "Model failed to load", "dialog-error", 3000)
            return

        # Transcribe
        try:
            if not self.model or not self.temp_file:
                print("Error: Model or temp file not initialized")
                return

            # Verify temp file exists and has content
            temp_file_path = (
                self.temp_file.name
                if hasattr(self.temp_file, "name")
                else str(self.temp_file)
            )
            if not os.path.exists(temp_file_path):
                print(f"Error: Temp file does not exist: {temp_file_path}")
                self.notify("Error", "Recording file not found", "dialog-error", 3000)
                return

            file_size = os.path.getsize(temp_file_path)
            if file_size == 0:
                print(f"Error: Temp file is empty: {temp_file_path}")
                self.notify("Error", "Recording file is empty", "dialog-error", 3000)
                return

            print(f"Transcribing {file_size} bytes from {temp_file_path}...")
            # Configure VAD to be less aggressive and preserve first words
            vad_options = VadOptions(
                threshold=0.3,  # Lower = less aggressive (default 0.5)
                min_silence_duration_ms=100,  # Reduced from default 2000ms to catch speech sooner
                speech_pad_ms=500,  # Increased padding around speech (default 400ms)
            )
            segments, info = self.model.transcribe(
                temp_file_path,
                beam_size=5,
                vad_filter=True,
                vad_parameters=vad_options,
            )

            text = " ".join(segment.text.strip() for segment in segments)

            if text:
                # Copy to clipboard (Wayland only)
                process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                process.communicate(input=text.encode())

                # Type it into the active input field
                if AUTO_TYPE:
                    result = None
                    try:
                        if TYPING_TOOL == "wtype":
                            result = subprocess.run(
                                ["wtype", text], capture_output=True, text=True
                            )
                        elif TYPING_TOOL == "dotool":
                            # dotool reads from stdin: echo "type text" | dotool
                            # First verify dotoold is running
                            if not is_dotoold_running():
                                print(
                                    "ERROR: dotool selected but dotoold daemon is not running."
                                )
                                print("Attempting to start dotoold...")
                                try:
                                    subprocess.Popen(
                                        ["dotoold"],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        start_new_session=True,
                                    )
                                    time.sleep(0.2)
                                    if not is_dotoold_running():
                                        raise RuntimeError(
                                            "Failed to start dotoold daemon"
                                        )
                                except Exception as e:
                                    print(f"Failed to start dotoold: {e}")
                                    print("Please start dotoold manually: dotoold &")
                                    print(
                                        "Or enable as service: systemctl --user enable --now dotoold"
                                    )
                                    raise

                            process = subprocess.Popen(
                                ["dotool"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                            )
                            stdout, stderr = process.communicate(input=f"type {text}")
                            result = subprocess.CompletedProcess(
                                args=["dotool"],
                                returncode=process.returncode,
                                stdout=stdout,
                                stderr=stderr,
                            )

                        if result is not None and result.returncode != 0:
                            error_msg = (
                                result.stderr
                                if hasattr(result, "stderr")
                                else str(result)
                            )
                            print(f"Typing failed with {TYPING_TOOL}: {error_msg}")
                            if TYPING_TOOL == "dotool":
                                if not is_dotoold_running():
                                    print(
                                        "Hint: dotoold daemon may have stopped. Try restarting it: dotoold &"
                                    )
                    except Exception as e:
                        print(f"Error while typing: {e}")
                        if TYPING_TOOL == "dotool":
                            if not is_dotoold_running():
                                print(
                                    "Hint: dotoold daemon is not running. Start it with: dotoold &"
                                )

                print(f"Copied: {text}")
                self.notify(
                    "Copied!",
                    text[:100] + ("..." if len(text) > 100 else ""),
                    "emblem-ok-symbolic",
                    3000,
                )
            else:
                print("No speech detected")
                self.notify(
                    "No speech detected", "Try speaking louder", "dialog-warning", 2000
                )

        except Exception as e:
            print(f"Error: {e}")
            self.notify("Error", str(e)[:50], "dialog-error", 3000)
        finally:
            # Cleanup temp file
            if self.temp_file and os.path.exists(self.temp_file.name):
                os.unlink(self.temp_file.name)

    def stop(self):
        print("\nExiting...")
        self.running = False
        os._exit(0)

    def run_evdev_hotkey(self, keyboard_devices, target_key_code):
        """
        Run with evdev for direct keyboard monitoring on Wayland.

        Reads keyboard events directly from /dev/input/event* devices.
        Monitors ALL keyboard devices simultaneously so F9 works on any keyboard.
        """
        from evdev import ecodes, categorize

        key_name = str(CONFIG["key"]).upper()
        print(
            f"Monitoring {len(keyboard_devices)} keyboard(s) for {key_name} key (code: {target_key_code})..."
        )
        print("Press Ctrl+C to quit.")
        print("(Debug: Key events will be logged)")

        def monitor_device(device):
            """Monitor a single keyboard device in a separate thread."""
            try:
                for event in device.read_loop():
                    # Only process key events
                    if event.type == ecodes.EV_KEY:
                        # Check if this is our target key
                        if event.code == target_key_code:
                            # event.value: 0 = release, 1 = press, 2 = hold
                            if event.value == 1:  # Key pressed
                                print(
                                    f"DEBUG: {key_name} key PRESSED on {device.name} (code: {event.code})"
                                )
                                if not self.recording:
                                    self.start_recording()
                            elif event.value == 0:  # Key released
                                print(
                                    f"DEBUG: {key_name} key RELEASED on {device.name} (code: {event.code})"
                                )
                                if self.recording:
                                    self.stop_recording()
                            # Ignore repeat events (value == 2)
            except PermissionError:
                print(
                    f"ERROR: Permission denied accessing keyboard device: {device.name}"
                )
            except OSError as e:
                print(f"ERROR: Keyboard device error on {device.name}: {e}")
            except Exception as e:
                print(f"ERROR: Unexpected error monitoring {device.name}: {e}")

        # Start a monitoring thread for each keyboard device
        monitor_threads = []
        for device in keyboard_devices:
            thread = threading.Thread(
                target=monitor_device,
                args=(device,),
                daemon=True,
                name=f"KeyboardMonitor-{device.name}",
            )
            thread.start()
            monitor_threads.append((thread, device))

        try:
            # Wait for all threads (they run until interrupted)
            for thread, device in monitor_threads:
                thread.join()
        except KeyboardInterrupt:
            print("\nStopping keyboard monitors...")
        finally:
            # Close all devices
            for thread, device in monitor_threads:
                try:
                    device.close()
                except Exception:
                    pass  # Device may already be closed


def check_dependencies():
    """Check that required system commands are available."""
    missing = []

    # Check for any audio backend
    has_audio = any(
        subprocess.run(["which", cmd], capture_output=True).returncode == 0
        for cmd in ["parecord", "pw-record", "arecord"]
    )
    if not has_audio:
        missing.append(("audio backend", "none"))

    # Check for clipboard tool (Wayland only)
    has_clipboard = (
        subprocess.run(["which", "wl-copy"], capture_output=True).returncode == 0
    )
    if not has_clipboard:
        missing.append(("clipboard tool", "none"))

    # Check for typing tool if auto-typing is enabled (Wayland only)
    if AUTO_TYPE:
        has_typing = any(
            subprocess.run(["which", cmd], capture_output=True).returncode == 0
            for cmd in ["wtype", "dotool"]
        )
        if not has_typing:
            missing.append(("typing tool", "none"))

    if missing:
        print("Missing dependencies:")
        for cmd, pkg in missing:
            if cmd == "audio backend":
                print("  Audio recording backend - install one of:")
                print("    parecord: sudo apt install pulseaudio-utils (Ubuntu/Debian)")
                print("    pw-record: sudo apt install pipewire-bin (Ubuntu/Debian)")
                print("    arecord: sudo apt install alsa-utils (Ubuntu/Debian)")
            elif cmd == "clipboard tool":
                print("  Clipboard tool - install:")
                print("    wl-copy: sudo apt install wl-clipboard")
            elif cmd == "typing tool":
                print("  Typing tool - install one of:")
                print("    wtype: sudo apt install wtype")
                print("    dotool: cargo install dotool (best for KDE)")
            else:
                print(f"  {cmd} - install with: sudo apt install {pkg}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SoupaWhisper - Push-to-talk voice dictation for KDE Wayland"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"SoupaWhisper {__version__}"
    )
    args = parser.parse_args()

    print(f"SoupaWhisper v{__version__}")
    print(f"Config: {CONFIG_PATH}")

    # Check if running on KDE Wayland
    if not is_kwin_wayland():
        print("ERROR: SoupaWhisper only supports KDE Plasma Wayland.")
        print("This application requires KDE Wayland (KWin) to be running.")
        sys.exit(1)

    check_dependencies()

    # Initialize evdev keyboard monitoring
    try:
        evdev_devices, evdev_key_code = _load_evdev_keyboard(CONFIG["key"])
        print("Using evdev for KDE Wayland keyboard monitoring")
    except Exception as e:
        print("ERROR: Failed to initialize evdev keyboard monitor.")
        print(f"Reason: {e}")
        print("")
        print("evdev is required for Wayland keyboard support.")
        print("Install with: pip install evdev")
        print("Also ensure your user is in the 'input' group:")
        print("  sudo usermod -aG input $USER")
        print("Then log out and log back in.")
        sys.exit(1)

    dictation = Dictation()

    # Handle Ctrl+C gracefully
    def handle_sigint(sig, frame):
        dictation.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    # Run with evdev hotkey monitoring
    dictation.run_evdev_hotkey(evdev_devices, evdev_key_code)


if __name__ == "__main__":
    main()
