#!/usr/bin/env bash
set -euo pipefail

REPO="obol89/filetriage"
BASE_URL="https://github.com/${REPO}/releases/latest/download"

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux)  ASSET="filetriage-linux" ;;
    Darwin) ASSET="filetriage-macos" ;;
    *)
        echo "Error: Unsupported OS: $OS (only Linux and macOS are supported)"
        exit 1
        ;;
esac

# Detect architecture
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)  ;;
    arm64|aarch64) ;;
    *)
        echo "Error: Unsupported architecture: $ARCH (only x86_64 and arm64 are supported)"
        exit 1
        ;;
esac

DOWNLOAD_URL="${BASE_URL}/${ASSET}"
INSTALL_DIR="/usr/local/bin"
INSTALL_PATH="${INSTALL_DIR}/filetriage"
TMPFILE="$(mktemp)"

echo "Detected: $OS ($ARCH)"
echo "Downloading $ASSET ..."

# Download using curl or wget
if command -v curl >/dev/null 2>&1; then
    curl -fSL -o "$TMPFILE" "$DOWNLOAD_URL"
elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$TMPFILE" "$DOWNLOAD_URL"
else
    echo "Error: Neither curl nor wget found. Please install one and try again."
    rm -f "$TMPFILE"
    exit 1
fi

chmod +x "$TMPFILE"

# Check for existing install
if [ -f "$INSTALL_PATH" ]; then
    printf "filetriage already exists at %s. Overwrite? [Y/n] " "$INSTALL_PATH"
    read -r answer
    case "$answer" in
        [nN]*)
            echo "Aborted. Existing binary left unchanged."
            rm -f "$TMPFILE"
            exit 0
            ;;
    esac
fi

# Install to /usr/local/bin
echo "Installing to $INSTALL_PATH ..."

if [ -w "$INSTALL_DIR" ]; then
    cp "$TMPFILE" "$INSTALL_PATH"
else
    echo "Note: $INSTALL_DIR is not writable by your user, using sudo."
    if ! sudo cp "$TMPFILE" "$INSTALL_PATH"; then
        echo "Error: sudo failed. You can manually copy the binary:"
        echo "  sudo cp $TMPFILE $INSTALL_PATH"
        exit 1
    fi
fi

rm -f "$TMPFILE"

echo ""
echo "Installed to $INSTALL_PATH"
echo "Run it with: filetriage"
