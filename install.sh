#!/bin/bash
# Install SoupaWhisper on Linux
# Supports: Ubuntu, Pop!_OS, Debian, Fedora, Arch

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/soupawhisper"
SERVICE_DIR="$HOME/.config/systemd/user"

# Detect package manager
detect_package_manager() {
    if command -v apt &> /dev/null; then
        echo "apt"
    elif command -v dnf &> /dev/null; then
        echo "dnf"
    elif command -v pacman &> /dev/null; then
        echo "pacman"
    elif command -v zypper &> /dev/null; then
        echo "zypper"
    else
        echo "unknown"
    fi
}

# Install system dependencies
install_deps() {
    local pm=$(detect_package_manager)

    echo "Detected package manager: $pm"
    echo "Installing system dependencies..."

    case $pm in
        apt)
            sudo apt update
            sudo apt install -y pipewire pipewire-pulse pulseaudio-utils alsa-utils wl-clipboard xclip wtype xdotool libnotify-bin cargo
            ;;
        dnf)
            sudo dnf install -y pipewire pipewire-pulseaudio pulseaudio-utils alsa-utils wl-clipboard xclip wtype xdotool libnotify cargo
            ;;
        pacman)
            sudo pacman -S --noconfirm pipewire pipewire-pulse pulseaudio alsa-utils wl-clipboard xclip wtype xdotool libnotify rust
            ;;
        zypper)
            sudo zypper install -y pipewire pipewire-pulseaudio pulseaudio-utils alsa-utils wl-clipboard xclip wtype xdotool libnotify-tools cargo
            ;;
        *)
            echo "Unknown package manager. Please install manually:"
            echo "  Audio: pipewire pipewire-pulse pulseaudio-utils (or alsa-utils)"
            echo "  Clipboard: wl-clipboard (Wayland) or xclip (X11)"
            echo "  Typing: wtype (Wayland), dotool (cargo install, best for KDE), or xdotool (X11)"
            echo "  Other: libnotify"
            ;;
    esac

    echo ""
    echo "Installing dotool via cargo (for KDE Plasma Wayland support)..."
    if command -v cargo &> /dev/null; then
        cargo install dotool || echo "Warning: dotool installation failed. You can install it manually later."
    else
        echo "Warning: cargo not found. Install rust/cargo to use dotool."
    fi
}

# Install Python dependencies
install_python() {
    echo ""
    echo "Installing Python dependencies..."

    if ! command -v poetry &> /dev/null; then
        echo "Poetry not found. Please install Poetry first:"
        echo "  curl -sSL https://install.python-poetry.org | python3 -"
        exit 1
    fi

    poetry install
}

# Setup config file
setup_config() {
    echo ""
    echo "Setting up config..."
    mkdir -p "$CONFIG_DIR"

    if [ ! -f "$CONFIG_DIR/config.ini" ]; then
        cp "$SCRIPT_DIR/config.example.ini" "$CONFIG_DIR/config.ini"
        echo "Created config at $CONFIG_DIR/config.ini"
    else
        echo "Config already exists at $CONFIG_DIR/config.ini"
    fi
}

# Install systemd service
install_service() {
    echo ""
    echo "Installing systemd user service..."

    mkdir -p "$SERVICE_DIR"

    # Get current display settings
    local display="${DISPLAY:-:0}"
    local xauthority="${XAUTHORITY:-$HOME/.Xauthority}"
    local wayland_display="${WAYLAND_DISPLAY:-wayland-0}"
    local xdg_runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    local dbus_session_bus_address="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$xdg_runtime_dir/bus}"
    local venv_path="$SCRIPT_DIR/.venv"

    # Check if venv exists
    if [ ! -d "$venv_path" ]; then
        venv_path=$(poetry env info --path 2>/dev/null || echo "$SCRIPT_DIR/.venv")
    fi

    cat > "$SERVICE_DIR/soupawhisper.service" << EOF
[Unit]
Description=SoupaWhisper Voice Dictation
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$venv_path/bin/python $SCRIPT_DIR/dictate.py --trigger hotkey
Restart=on-failure
RestartSec=5

# X11 and Wayland display access
Environment=DISPLAY=$display
Environment=XAUTHORITY=$xauthority
Environment=WAYLAND_DISPLAY=$wayland_display
Environment=XDG_RUNTIME_DIR=$xdg_runtime_dir
Environment=DBUS_SESSION_BUS_ADDRESS=$dbus_session_bus_address

[Install]
WantedBy=default.target
EOF

    echo "Created service at $SERVICE_DIR/soupawhisper.service"

    # Reload and enable
    systemctl --user daemon-reload
    systemctl --user enable soupawhisper

    echo ""
    echo "Service installed! Commands:"
    echo "  systemctl --user start soupawhisper   # Start"
    echo "  systemctl --user stop soupawhisper    # Stop"
    echo "  systemctl --user status soupawhisper  # Status"
    echo "  journalctl --user -u soupawhisper -f  # Logs"
}

# Main
main() {
    echo "==================================="
    echo "  SoupaWhisper Installer"
    echo "==================================="
    echo ""

    install_deps
    install_python
    setup_config

    echo ""
    read -p "Install as systemd service? [y/N] " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        install_service
    fi

    echo ""
    echo "==================================="
    echo "  Installation complete!"
    echo "==================================="
    echo ""
    echo "To run manually:"
    echo "  poetry run python dictate.py"
    echo ""
    echo "Config: $CONFIG_DIR/config.ini"
    echo "Hotkey: F12 (hold to record)"
    echo "Exit:   Ctrl+C"
}

main "$@"
