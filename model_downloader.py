#!/usr/bin/env python3
"""
Model Downloader for SoupaWhisper
Downloads the Whisper model and shows progress.
"""

import argparse
import configparser
import sys
from pathlib import Path
from faster_whisper import WhisperModel


def load_config():
    """Load configuration from config file."""
    config_path = Path.home() / ".config" / "soupawhisper" / "config.ini"
    config = configparser.ConfigParser()

    # Defaults
    defaults = {
        "model": "base.en",
        "device": "cpu",
        "compute_type": "int8",
    }

    if config_path.exists():
        config.read(config_path)

    return {
        "model": config.get("whisper", "model", fallback=defaults["model"]),
        "device": config.get("whisper", "device", fallback=defaults["device"]),
        "compute_type": config.get(
            "whisper", "compute_type", fallback=defaults["compute_type"]
        ),
    }


def download_model(model_size=None, device=None, compute_type=None):
    """Download the Whisper model with progress indication."""

    # Load config if parameters not provided
    if model_size is None or device is None or compute_type is None:
        config = load_config()
        model_size = model_size or config["model"]
        device = device or config["device"]
        compute_type = compute_type or config["compute_type"]

    print(f"Downloading Whisper model: {model_size}")
    print(f"Device: {device}")
    print(f"Compute type: {compute_type}")
    print("-" * 50)

    try:
        # Initialize the model - this will download it if not present
        print("Initializing model (this will download if needed)...")
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=None,  # Use default cache directory
        )

        print("-" * 50)
        print(f"✓ Model '{model_size}' successfully downloaded and loaded!")
        print(f"✓ Model is ready to use with SoupaWhisper")

        # Get cache location
        from huggingface_hub import snapshot_download

        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        print(f"\nModel cached in: {cache_dir}")

        return True

    except Exception as e:
        print("-" * 50)
        print(f"✗ Error downloading model: {e}")

        if "cudnn" in str(e).lower() or "cuda" in str(e).lower():
            print("\nHint: Try using CPU device instead:")
            print(f"  python {sys.argv[0]} --device cpu")

        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download Whisper model for SoupaWhisper"
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        help="Model size (tiny, tiny.en, base, base.en, small, small.en, medium, medium.en, large-v2, large-v3)",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=str,
        choices=["cpu", "cuda", "auto"],
        help="Device to use (cpu, cuda, auto)",
    )
    parser.add_argument(
        "-c",
        "--compute-type",
        type=str,
        help="Compute type (int8, int8_float16, int16, float16, float32)",
    )

    args = parser.parse_args()

    print("SoupaWhisper Model Downloader")
    print("=" * 50)

    success = download_model(
        model_size=args.model,
        device=args.device,
        compute_type=args.compute_type,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
