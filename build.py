#!/usr/bin/env python3
"""Build script for FileTriage — produces a single-file executable via PyInstaller."""

import platform
import subprocess
import sys
from pathlib import Path


def main() -> None:
    system = platform.system()
    if system == "Windows":
        name = "filetriage.exe"
    elif system == "Linux":
        name = "filetriage"
    else:
        name = "filetriage"
        print(f"Note: untested platform '{system}', building anyway.")

    print(f"Building for {system}...")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "filetriage",
        "filetriage.py",
    ]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Build failed.", file=sys.stderr)
        sys.exit(1)

    dist = Path("dist") / name
    print()
    print(f"Build complete: {dist.resolve()}")
    print(f"Run it with:    ./{name}" if system != "Windows" else f"Run it with:    {name}")


if __name__ == "__main__":
    main()
