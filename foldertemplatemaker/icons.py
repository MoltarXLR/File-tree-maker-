"""Small folder / document icons drawn in code, so no image files are needed."""

from __future__ import annotations

import tkinter as tk
from typing import Iterable, List, Tuple

Rect = Tuple[int, int, int, int, str]

_AMBER = "#d9a21b"
_FOLDER_FRONT = "#ffd76a"
_FOLDER_SHINE = "#ffe9a8"

# Rectangles (x0, y0, x1, y1, colour) on a 16 x 16 grid, x1/y1 exclusive; later ones paint over earlier ones.
FOLDER: List[Rect] = [
    (1, 2, 7, 5, _AMBER),            # tab
    (1, 4, 15, 14, _AMBER),          # outline / back
    (2, 6, 14, 13, _FOLDER_FRONT),   # front face
    (2, 5, 14, 6, _FOLDER_SHINE),    # light edge along the top
]

DOCUMENT: List[Rect] = [
    (3, 1, 13, 15, "#8a8f98"),       # outline
    (4, 2, 12, 14, "#ffffff"),       # paper
    (9, 1, 13, 5, "#8a8f98"),        # folded corner
    (10, 2, 12, 4, "#dfe3e8"),
    (5, 6, 11, 7, "#8da2c0"),        # lines of text
    (5, 8, 11, 9, "#8da2c0"),
    (5, 10, 9, 11, "#8da2c0"),
]


def _scaled(rects: Iterable[Rect], size: int) -> Iterable[Rect]:
    k = size / 16.0
    for x0, y0, x1, y1, colour in rects:
        sx0, sy0 = int(round(x0 * k)), int(round(y0 * k))
        sx1, sy1 = max(int(round(x1 * k)), sx0 + 1), max(int(round(y1 * k)), sy0 + 1)
        yield sx0, sy0, sx1, sy1, colour


def draw(master: tk.Misc, rects: Iterable[Rect], size: int) -> tk.PhotoImage:
    image = tk.PhotoImage(master=master, width=size, height=size)
    for x0, y0, x1, y1, colour in _scaled(rects, size):
        image.put(colour, to=(x0, y0, x1, y1))
    return image


class Icons:
    """The icon set used by the tree views (keeps the images alive)."""

    def __init__(self, master: tk.Misc, size: int = 16):
        self.size = size
        self.folder = draw(master, FOLDER, size)
        self.document = draw(master, DOCUMENT, size)
