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
DEST="./filetriage"

echo "Detected: $OS ($ARCH)"
echo "Downloading $ASSET ..."

# Download using curl or wget
if command -v curl >/dev/null 2>&1; then
    curl -fSL -o "$DEST" "$DOWNLOAD_URL"
elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$DEST" "$DOWNLOAD_URL"
else
    echo "Error: Neither curl nor wget found. Please install one and try again."
    exit 1
fi

chmod +x "$DEST"
echo "Downloaded to $(pwd)/filetriage"

# Offer to install system-wide
printf "Move to /usr/local/bin/filetriage for system-wide access? [Y/n] "
read -r answer
case "$answer" in
    [nN]*)
        echo "Done. Run it with: ./filetriage"
        ;;
    *)
        sudo mv "$DEST" /usr/local/bin/filetriage
        echo "Installed to /usr/local/bin/filetriage"
        echo "Run it with: filetriage"
        ;;
esac
