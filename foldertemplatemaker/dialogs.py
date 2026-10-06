"""The small pop-up windows: add/edit a document, add several folders, help text."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .names import PLACEHOLDERS, unknown_placeholders

ERROR_FG = "#b00020"
HINT_FG = "#555555"
WARN_FG = "#8a5a00"


class ModalDialog(tk.Toplevel):
    """A pop-up centred over its parent.  ``show()`` returns True if the user accepted it."""

    def __init__(self, parent: tk.Misc, title: str, modal: bool = True):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self._modal = modal
        self.accepted = False
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _e: self.cancel())

    def present(self) -> None:
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
        self.deiconify()
        self.lift()
        if self._modal:
            try:
                self.wait_visibility()
                self.grab_set()
            except tk.TclError:
                pass
        self.focus_force()

    def show(self) -> bool:
        self.present()
        if self._modal:
            self.wait_window(self)
        return self.accepted

    def cancel(self) -> None:
        self.accepted = False
        self.destroy()


class DocumentDialog(ModalDialog):
    """Create or edit a text document that will be written into a folder."""

    EXTENSIONS = (".txt", ".md", ".csv", ".log", ".json", ".html", "(none)")

    def __init__(self, parent: tk.Misc, *, title: str, folder_name: str, name: str, ext: str,
                 content: str, preview: Callable[[str, str], str],
                 apply: Callable[[str, str, str], Optional[str]],
                 ok_text: str = "Save document", modal: bool = True):
        super().__init__(parent, title, modal)
        self._preview = preview
        self._apply = apply
        self._last_focus: tk.Widget

        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text='This document is created inside "%s".' % folder_name,
                  foreground=HINT_FG).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(body, text="Document name").grid(row=1, column=0, sticky="w")
        self.name_var = tk.StringVar(value=name)
        self.name_entry = ttk.Entry(body, textvariable=self.name_var, width=42)
        self.name_entry.grid(row=1, column=1, sticky="we", padx=(8, 12))
        ttk.Label(body, text="File type").grid(row=1, column=2, sticky="w")
        self.ext_var = tk.StringVar(value=ext if ext else "(none)")
        self.ext_box = ttk.Combobox(body, textvariable=self.ext_var, values=self.EXTENSIONS, width=8)
        self.ext_box.grid(row=1, column=3, sticky="w", padx=(8, 0))

        ttk.Label(body, text="Will be created as").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.preview_var = tk.StringVar()
        ttk.Label(body, textvariable=self.preview_var, font=("TkDefaultFont", 10, "bold")).grid(
            row=2, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(body, text="Text inside the document (optional)").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(12, 2))
        text_frame = ttk.Frame(body)
        text_frame.grid(row=4, column=0, columnspan=4, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        self.text = tk.Text(text_frame, width=62, height=7, wrap="word", undo=True,
                            relief="solid", borderwidth=1, padx=6, pady=4)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.insert("1.0", content)
        self.text.edit_reset()

        ttk.Label(body, text="Placeholders - click one to insert it where you are typing. They are "
                  "filled in when the folder is created.", foreground=HINT_FG,
                  wraplength=520, justify="left").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(10, 2))
        legend = ttk.Frame(body)
        legend.grid(row=6, column=0, columnspan=4, sticky="w")
        for index, (key, description) in enumerate(PLACEHOLDERS):
            button = ttk.Button(legend, text="{%s}" % key, width=12,
                                command=lambda k=key: self.insert_placeholder(k))
            button.grid(row=index, column=0, sticky="we", pady=1)
            ttk.Label(legend, text=description, foreground=HINT_FG).grid(
                row=index, column=1, sticky="w", padx=(10, 0))

        self.hint_var = tk.StringVar()
        ttk.Label(body, textvariable=self.hint_var, foreground=WARN_FG, wraplength=560,
                  justify="left").grid(row=7, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_FG, wraplength=560,
                  justify="left").grid(row=8, column=0, columnspan=4, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=4, sticky="e", pady=(12, 0))
        self.ok_button = ttk.Button(buttons, text=ok_text, command=self.ok)
        self.ok_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="left")

        self._last_focus = self.name_entry
        self.name_entry.bind("<FocusIn>", lambda _e: setattr(self, "_last_focus", self.name_entry))
        self.text.bind("<FocusIn>", lambda _e: setattr(self, "_last_focus", self.text))
        self.text.bind("<KeyRelease>", lambda _e: self._refresh_hint())
        self.name_var.trace_add("write", lambda *_: self._refresh_preview())
        self.ext_var.trace_add("write", lambda *_: self._refresh_preview())
        self._refresh_preview()
        self.name_entry.focus_set()
        self.name_entry.icursor("end")

    # -- helpers ----------------------------------------------------------- #

    def extension(self) -> str:
        raw = self.ext_var.get().strip()
        if raw.lower() in ("", "(none)", "none"):
            return ""
        return raw if raw.startswith(".") else "." + raw

    def _refresh_preview(self) -> None:
        name = self.name_var.get().strip()
        try:
            self.preview_var.set(self._preview(name, self.extension()) if name else "")
        except Exception:
            self.preview_var.set("")
        self.error_var.set("")
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        odd = self.warnings()
        self.hint_var.set(
            "Heads up: %s isn't a placeholder, so it will be written exactly as typed." % odd
            if odd else "")

    def insert_placeholder(self, key: str) -> None:
        target = self._last_focus
        token = "{%s}" % key
        if target is self.text:
            self.text.insert("insert", token)
            self.text.focus_set()
        else:
            self.name_entry.insert("insert", token)
            self.name_entry.focus_set()

    def ok(self) -> None:
        name = self.name_var.get().strip()
        content = self.text.get("1.0", "end-1c")
        error = self._apply(name, self.extension(), content)
        if error:
            self.error_var.set(error)
            return
        self.accepted = True
        self.destroy()

    def warnings(self) -> str:
        """Placeholder-looking text that isn't a real placeholder (probably a typo)."""
        odd = unknown_placeholders(self.name_var.get() + "\n" + self.text.get("1.0", "end-1c"))
        return ", ".join(odd)


class OutlineDialog(ModalDialog):
    """Type or paste a list of folder names (indent a line to nest it)."""

    EXAMPLE = "Legal\n    Contracts\n    Disputes\nFinancial\nTax"

    def __init__(self, parent: tk.Misc, *, parent_name: str,
                 apply: Callable[[str], Optional[str]], modal: bool = True):
        super().__init__(parent, "Add several folders", modal)
        self._apply = apply
        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        ttk.Label(body, text='Add several folders inside "%s"' % parent_name,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(body, justify="left", foreground=HINT_FG, text=(
            "Type or paste one folder name per line.\n"
            "Start a line with extra spaces (or a Tab) to make it a subfolder of the line above.\n"
            "Bullets such as - or • at the start of a line are ignored.")).grid(
            row=1, column=0, sticky="w", pady=(2, 8))

        text_frame = ttk.Frame(body)
        text_frame.grid(row=2, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text = tk.Text(text_frame, width=54, height=14, wrap="none", undo=True,
                            relief="solid", borderwidth=1, padx=6, pady=4)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        example = ttk.Button(body, text="Show an example", command=self._insert_example)
        example.grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.error_var = tk.StringVar()
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_FG, wraplength=480,
                  justify="left").grid(row=4, column=0, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, sticky="e", pady=(10, 0))
        self.ok_button = ttk.Button(buttons, text="Add folders", command=self.ok)
        self.ok_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="left")
        self.text.focus_set()

    def _insert_example(self) -> None:
        if not self.text.get("1.0", "end-1c").strip():
            self.text.insert("1.0", self.EXAMPLE)

    def ok(self) -> None:
        error = self._apply(self.text.get("1.0", "end-1c"))
        if error:
            self.error_var.set(error)
            return
        self.accepted = True
        self.destroy()


class TextDialog(ModalDialog):
    """A read-only message window with a Close button (used for Help and About)."""

    def __init__(self, parent: tk.Misc, title: str, text: str, *, width: int = 78,
                 height: int = 24, modal: bool = True):
        super().__init__(parent, title, modal)
        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        frame = ttk.Frame(body)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.text = tk.Text(frame, width=width, height=height, wrap="word", relief="solid",
                            borderwidth=1, padx=10, pady=8, font="TkDefaultFont")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.tag_configure("h", font=("TkDefaultFont", 10, "bold"), spacing1=8, spacing3=2)
        for line in text.split("\n"):
            if line.startswith("# "):
                self.text.insert("end", line[2:] + "\n", "h")
            else:
                self.text.insert("end", line + "\n")
        self.text.configure(state="disabled")
        close = ttk.Button(body, text="Close", command=self.cancel)
        close.grid(row=1, column=0, sticky="e", pady=(10, 0))
        close.focus_set()
        self.bind("<Return>", lambda _e: self.cancel())
