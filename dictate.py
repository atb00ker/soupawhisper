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
from pathlib import Path

from pynput import keyboard
from faster_whisper import WhisperModel

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
        "key": "f12",
        "auto_type": "true",
        "notifications": "true",
        "audio_backend": "auto",
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
    """Detect available clipboard tool (Wayland or X11)."""
    # Priority: wl-copy (Wayland) > xclip (X11)
    for cmd in ["wl-copy", "xclip"]:
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


def detect_typing_tool():
    """Detect available typing tool (Wayland or X11)."""
    # Priority: wtype (Wayland) > ydotool (Wayland) > xdotool (X11)
    for cmd in ["wtype", "ydotool", "xdotool"]:
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


CLIPBOARD_TOOL = detect_clipboard_tool()
TYPING_TOOL = detect_typing_tool()


def get_hotkey(key_name):
    """Map key name to pynput key."""
    key_name = key_name.lower()
    if hasattr(keyboard.Key, key_name):
        return getattr(keyboard.Key, key_name)
    elif len(key_name) == 1:
        return keyboard.KeyCode.from_char(key_name)
    else:
        print(f"Unknown key: {key_name}, defaulting to f12")
        return keyboard.Key.f12


HOTKEY = get_hotkey(CONFIG["key"])
MODEL_SIZE = CONFIG["model"]
DEVICE = CONFIG["device"]
COMPUTE_TYPE = CONFIG["compute_type"]
AUTO_TYPE = CONFIG["auto_type"]
NOTIFICATIONS = CONFIG["notifications"]


class Dictation:
    def __init__(self):
        self.recording = False
        self.record_process = None
        self.temp_file = None
        self.model = None
        self.model_loaded = threading.Event()
        self.model_error = None
        self.running = True

        # Check audio backend availability
        if AUDIO_BACKEND is None:
            print("ERROR: No audio recording backend found!")
            print("Please install one of: parecord, pw-record, or arecord")
            sys.exit(1)

        # Check clipboard tool availability
        if CLIPBOARD_TOOL is None:
            print("ERROR: No clipboard tool found!")
            print("Please install one of: wl-copy (Wayland) or xclip (X11)")
            sys.exit(1)

        # Check typing tool availability if auto-typing is enabled
        if AUTO_TYPE and TYPING_TOOL is None:
            print("ERROR: No typing tool found!")
            print(
                "Please install one of: wtype (Wayland), ydotool (Wayland), or xdotool (X11)"
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
                MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE
            )
            self.model_loaded.set()
            hotkey_name = (
                HOTKEY.name
                if hasattr(HOTKEY, "name") and HOTKEY.name
                else (getattr(HOTKEY, "char", None) or str(HOTKEY))
            )
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
            command = AUDIO_COMMAND_BUILDER(self.temp_file.name)
        else:
            print("ERROR: Audio command builder not found!")
            return

        self.record_process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"Recording with {AUDIO_BACKEND}...")
        hotkey_name = (
            HOTKEY.name
            if hasattr(HOTKEY, "name") and HOTKEY.name
            else (getattr(HOTKEY, "char", None) or str(HOTKEY))
        )
        self.notify(
            "Recording...",
            f"Release {hotkey_name.upper()} when done",
            "audio-input-microphone",
            30000,
        )

    def stop_recording(self):
        if not self.recording:
            return

        self.recording = False

        if self.record_process:
            self.record_process.terminate()
            self.record_process.wait()
            self.record_process = None

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

            segments, info = self.model.transcribe(
                self.temp_file.name,
                beam_size=5,
                vad_filter=True,
            )

            text = " ".join(segment.text.strip() for segment in segments)

            if text:
                # Copy to clipboard
                if CLIPBOARD_TOOL == "wl-copy":
                    process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                    process.communicate(input=text.encode())
                else:  # xclip
                    process = subprocess.Popen(
                        ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
                    )
                    process.communicate(input=text.encode())

                # Type it into the active input field
                if AUTO_TYPE:
                    if TYPING_TOOL == "wtype":
                        subprocess.run(["wtype", text])
                    elif TYPING_TOOL == "ydotool":
                        subprocess.run(["ydotool", "type", text])
                    else:  # xdotool
                        subprocess.run(["xdotool", "type", "--clearmodifiers", text])

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

    def on_press(self, key):
        if key == HOTKEY:
            self.start_recording()

    def on_release(self, key):
        if key == HOTKEY:
            self.stop_recording()

    def stop(self):
        print("\nExiting...")
        self.running = False
        os._exit(0)

    def run(self):
        with keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        ) as listener:
            listener.join()


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

    # Check for clipboard tool
    has_clipboard = any(
        subprocess.run(["which", cmd], capture_output=True).returncode == 0
        for cmd in ["wl-copy", "xclip"]
    )
    if not has_clipboard:
        missing.append(("clipboard tool", "none"))

    # Check for typing tool if auto-typing is enabled
    if AUTO_TYPE:
        has_typing = any(
            subprocess.run(["which", cmd], capture_output=True).returncode == 0
            for cmd in ["wtype", "ydotool", "xdotool"]
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
                print("  Clipboard tool - install one of:")
                print("    wl-copy: sudo apt install wl-clipboard (Wayland)")
                print("    xclip: sudo apt install xclip (X11)")
            elif cmd == "typing tool":
                print("  Typing tool - install one of:")
                print("    wtype: sudo apt install wtype (Wayland)")
                print("    ydotool: sudo apt install ydotool (Wayland)")
                print("    xdotool: sudo apt install xdotool (X11)")
            else:
                print(f"  {cmd} - install with: sudo apt install {pkg}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SoupaWhisper - Push-to-talk voice dictation"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"SoupaWhisper {__version__}"
    )
    parser.parse_args()

    print(f"SoupaWhisper v{__version__}")
    print(f"Config: {CONFIG_PATH}")

    check_dependencies()

    dictation = Dictation()

    # Handle Ctrl+C gracefully
    def handle_sigint(sig, frame):
        dictation.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    dictation.run()


if __name__ == "__main__":
    main()
