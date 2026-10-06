"""Program entry point."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from typing import List, Optional

from . import APP_NAME, osutil


def _log_crash(text: str) -> str:
    path = os.path.join(osutil.app_data_dir(), "error.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("%s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        return "(a log file couldn't be written)"
    return path


def _show_fatal(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message)
        root.destroy()
    except Exception:
        pass


def run_selftest(report_path: str) -> int:
    """Drive the real program end to end with nobody at the keyboard.

    The build uses this to prove the finished .exe really starts, opens its window and can
    create folders.  It works in a throw-away data folder and writes a report to
    ``report_path`` (a windowed .exe has no console to print to).
    """
    lines: List[str] = []
    code = 1
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[osutil.HOME_ENV_VAR] = os.path.join(tmp, "data")
            destination = os.path.join(tmp, "OneDrive", "Deals")
            os.makedirs(destination)

            from .gui import App
            from .storage import Store

            store = Store()
            store.load()
            app = App(store)
            problems: List[str] = []
            app.error = lambda title, message: problems.append("%s: %s" % (title, message))  # type: ignore
            app.confirm = lambda *args, **kwargs: True  # type: ignore
            app.update()
            lines.append("window opened: %s" % app.title())
            lines.append("window icon: %s" % ("loaded" if app.icon_loaded else "NOT loaded"))
            if not app.icon_loaded:
                problems.append("the window icon did not load")
            lines.append("templates: %s" % [t.name for t in store.templates])

            app.dest_var.set(destination)
            app.name_var.set("Selftest Deal")
            app.create()
            app.update()

            top = os.path.join(destination, "Selftest Deal")
            document = os.path.join(top, "Work product", "Selftest Deal raw data.txt")
            expected = [top, os.path.join(top, "Source documents"),
                        os.path.join(top, "Work product"), os.path.join(top, "Correspondence")]
            missing = [p for p in expected if not os.path.isdir(p)]
            if missing:
                problems.append("missing folders: %s" % missing)
            if not os.path.isfile(document):
                problems.append("missing document: %s" % document)
            lines.append("result: %s" % app.result_var.get())

            app.tname_var.set("Selftest template")
            app.update()
            if not app.save():
                problems.append("save failed")
            reloaded = Store()
            reloaded.load()
            if "Selftest template" not in [t.name for t in reloaded.templates]:
                problems.append("saved template was not found after reloading")

            app.destroy()
            lines.extend("PROBLEM: " + p for p in problems)
            code = 0 if not problems else 1
    except Exception:
        lines.append("CRASH:\n" + traceback.format_exc())
        code = 1
    lines.append("SELFTEST " + ("PASSED" if code == 0 else "FAILED"))
    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass
    else:
        print("\n".join(lines))
    return code


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--selftest":
        return run_selftest(args[1] if len(args) > 1 else "")

    osutil.enable_dpi_awareness()
    try:
        from .gui import App
        app = App()
        app.mainloop()
    except Exception:
        text = traceback.format_exc()
        where = _log_crash(text)
        _show_fatal("%s couldn't start.\n\n%s\n\nDetails: %s" % (APP_NAME, text.splitlines()[-1], where))
        return 1
    return 0
