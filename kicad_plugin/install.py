#!/usr/bin/env python3
"""
Install the MCP AI Bridge plugin into KiCad's scripting directory.

Usage:
    python install.py          # Auto-detect KiCad plugin dir
    python install.py --path /custom/kicad/plugins
    python install.py --uninstall
"""

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

PLUGIN_DIR_NAME = "mcp_ai_bridge"

def get_kicad_plugin_dirs():
    """Return candidate KiCad scripting/plugins directories."""
    system = platform.system()
    home = Path.home()
    candidates = []

    if system == "Darwin":
        candidates = [
            home / "Library" / "Preferences" / "kicad" / "9.0" / "scripting" / "plugins",
            home / "Library" / "Preferences" / "kicad" / "10.0" / "scripting" / "plugins",
            home / "Library" / "Preferences" / "kicad" / "scripting" / "plugins",
            home / ".local" / "share" / "kicad" / "9.0" / "scripting" / "plugins",
            home / ".local" / "share" / "kicad" / "10.0" / "scripting" / "plugins",
        ]
    elif system == "Linux":
        candidates = [
            home / ".local" / "share" / "kicad" / "9.0" / "scripting" / "plugins",
            home / ".local" / "share" / "kicad" / "10.0" / "scripting" / "plugins",
            home / ".local" / "share" / "kicad" / "scripting" / "plugins",
        ]
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates = [
            appdata / "kicad" / "9.0" / "scripting" / "plugins",
            appdata / "kicad" / "10.0" / "scripting" / "plugins",
            appdata / "kicad" / "scripting" / "plugins",
        ]

    return [p for p in candidates if p.parent.exists()]


def install(target_dir):
    plugin_src = Path(__file__).parent.resolve()
    dest = target_dir / PLUGIN_DIR_NAME

    if dest.exists():
        if dest.is_symlink():
            dest.unlink()
            print(f"Removed existing symlink: {dest}")
        else:
            shutil.rmtree(dest)
            print(f"Removed existing directory: {dest}")

    target_dir.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        shutil.copytree(plugin_src, dest, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "install.py"
        ))
        print(f"Copied plugin to: {dest}")
    else:
        dest.symlink_to(plugin_src)
        print(f"Symlinked plugin: {dest} -> {plugin_src}")

    print(f"\nPlugin installed. Restart KiCad, then find '{PLUGIN_DIR_NAME}' "
          "under Tools > External Plugins.")


def uninstall(target_dir):
    dest = target_dir / PLUGIN_DIR_NAME
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink():
            dest.unlink()
        else:
            shutil.rmtree(dest)
        print(f"Removed: {dest}")
    else:
        print(f"Not installed at: {dest}")


def main():
    parser = argparse.ArgumentParser(description="Install MCP AI Bridge KiCad plugin")
    parser.add_argument("--path", type=Path, help="Custom KiCad plugin directory")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall the plugin")
    args = parser.parse_args()

    if args.path:
        dirs = [args.path]
    else:
        dirs = get_kicad_plugin_dirs()
        if not dirs:
            print("Could not find KiCad plugin directory. Use --path to specify it.")
            sys.exit(1)
        print(f"Found KiCad plugin directories:")
        for i, d in enumerate(dirs):
            print(f"  [{i}] {d}")
        if len(dirs) > 1:
            choice = input(f"Install to which directory? [0-{len(dirs)-1}]: ").strip()
            try:
                dirs = [dirs[int(choice)]]
            except (ValueError, IndexError):
                print("Invalid choice.")
                sys.exit(1)

    target = dirs[0]

    if args.uninstall:
        uninstall(target)
    else:
        install(target)


if __name__ == "__main__":
    main()
