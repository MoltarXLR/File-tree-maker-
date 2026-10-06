"""The few places where the program has to know which operating system it is on."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Tuple

APP_DIR_NAME = "FolderTemplateMaker"
HOME_ENV_VAR = "FOLDER_TEMPLATE_MAKER_HOME"   # lets you keep the data somewhere else


def is_windows() -> bool:
    return os.name == "nt"


def app_data_dir() -> str:
    """Folder where templates and settings are kept (created on demand by the caller).

    Windows: %APPDATA%\\FolderTemplateMaker.  Elsewhere: ~/.local/share/FolderTemplateMaker.
    Set the FOLDER_TEMPLATE_MAKER_HOME environment variable to use a different folder.
    """
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_windows():
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_DIR_NAME)


def normalize_path_text(text: str) -> str:
    """Clean up a path typed or pasted into a box.

    Explorer's "Copy as path" wraps the path in quotes, and people often paste
    stray spaces; ``%VARIABLES%`` and ``~`` are expanded.
    """
    text = text.strip().strip('"').strip("'").strip()
    if not text:
        return ""
    return os.path.expandvars(os.path.expanduser(text))


def open_in_file_manager(path: str) -> None:
    """Show a folder in Explorer (Finder / the default file manager elsewhere)."""
    if is_windows():
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _windows_known_folder(csidl: int) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:  # type: ignore[attr-defined]
            return buf.value
    except Exception:
        pass
    return ""


def quick_locations() -> List[Tuple[str, str]]:
    """(label, folder) pairs worth offering as shortcuts: OneDrive, Documents, Desktop."""
    found: List[Tuple[str, str]] = []
    seen = set()

    def add(label: str, path: str) -> None:
        if path and os.path.isdir(path) and os.path.normcase(os.path.abspath(path)) not in seen:
            seen.add(os.path.normcase(os.path.abspath(path)))
            found.append((label, path))

    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        path = os.environ.get(var, "")
        if path:
            base = os.path.basename(os.path.normpath(path))
            add(base or "OneDrive", path)
    if is_windows():
        add("Documents", _windows_known_folder(0x0005))   # CSIDL_PERSONAL
        add("Desktop", _windows_known_folder(0x0010))     # CSIDL_DESKTOPDIRECTORY
    home = os.path.expanduser("~")
    add("Documents", os.path.join(home, "Documents"))
    add("Desktop", os.path.join(home, "Desktop"))
    return found


def enable_dpi_awareness() -> None:
    """Ask Windows not to blur the window on high-resolution / scaled displays."""
    if not is_windows():
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
    except Exception:
        pass
