"""Small reusable widgets."""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class Tooltip:
    """A hover tip for any widget."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 550):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event: object = None) -> None:
        self._hide()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._after = None

    def _show(self) -> None:
        self._after = None
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 14
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry("+%d+%d" % (x, y))
            tk.Label(tip, text=self.text, background="#ffffe1", foreground="#000000",
                     relief="solid", borderwidth=1, padx=6, pady=3, justify="left").pack()
            self._tip = tip
        except tk.TclError:
            self._tip = None

    def _hide(self, _event: object = None) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
