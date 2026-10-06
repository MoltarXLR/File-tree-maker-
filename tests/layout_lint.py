"""Checks a window's layout the way a person would notice problems: text that is cut off, and
widgets drawn on top of each other.  Used by the GUI tests, so it runs on Windows and Linux."""

from typing import Iterator, List

# Widgets whose text is cut off if they get less room than they asked for.  (Entries and
# combo boxes are left out: being narrower than their preferred width loses nothing.)
TEXT_WIDGETS = {"TButton", "Button", "TLabel", "Label", "TMenubutton", "TCheckbutton", "Checkbutton"}


def _walk(widget) -> Iterator:
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _name(widget) -> str:
    text = ""
    for option in ("text",):
        try:
            text = str(widget.cget(option))
        except Exception:
            pass
    if not text:
        try:
            variable = str(widget.cget("textvariable"))
            if variable:
                text = str(widget.getvar(variable))
        except Exception:
            pass
    return "%s %r" % (widget.winfo_class(), text[:40])


def layout_problems(window, tolerance: int = 2) -> List[str]:
    """Plain-English list of layout problems in ``window`` (empty if it looks fine)."""
    window.update_idletasks()
    window.update()
    problems: List[str] = []
    widgets = [w for w in _walk(window) if w.winfo_ismapped()]

    for widget in widgets:
        if widget.winfo_class() not in TEXT_WIDGETS:
            continue
        width, req_width = widget.winfo_width(), widget.winfo_reqwidth()
        height, req_height = widget.winfo_height(), widget.winfo_reqheight()
        if width + tolerance < req_width:
            problems.append("%s is squeezed sideways (gets %dpx, needs %dpx)" % (
                _name(widget), width, req_width))
        if height + tolerance < req_height:
            problems.append("%s is squeezed vertically (gets %dpx, needs %dpx)" % (
                _name(widget), height, req_height))

    for parent in [window] + [w for w in _walk(window)]:
        kids = [k for k in parent.winfo_children()
                if k.winfo_ismapped() and k.winfo_manager() in ("grid", "pack")]
        boxes = [(k, k.winfo_x(), k.winfo_y(), k.winfo_x() + k.winfo_width(),
                  k.winfo_y() + k.winfo_height()) for k in kids]
        for i, (a, ax0, ay0, ax1, ay1) in enumerate(boxes):
            for b, bx0, by0, bx1, by1 in boxes[i + 1:]:
                overlap_w = min(ax1, bx1) - max(ax0, bx0)
                overlap_h = min(ay1, by1) - max(ay0, by0)
                if overlap_w > tolerance and overlap_h > tolerance:
                    problems.append("%s overlaps %s (%dx%dpx)" % (
                        _name(a), _name(b), overlap_w, overlap_h))

    # A widget larger than the container it sits in is cut off by that container.
    for widget in widgets:
        if widget.winfo_manager() not in ("grid", "pack"):
            continue
        container = widget.master
        if container is None:
            continue
        if (widget.winfo_x() + widget.winfo_width() > container.winfo_width() + tolerance
                or widget.winfo_y() + widget.winfo_height() > container.winfo_height() + tolerance):
            problems.append("%s is cut off by its container (%s)" % (_name(widget), _name(container)))
    return problems
