"""Rules for folder / file names, and ``{placeholder}`` substitution.

The rules are the Windows ones (plus the extra restrictions OneDrive adds) and
are enforced on every operating system, so a template that is accepted here can
always be created on Windows and synced through OneDrive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

MAX_NAME_LENGTH = 255

INVALID_CHARS = '<>:"/\\|?*'

_RESERVED_BASENAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(10)]
    + ["LPT%d" % i for i in range(10)]
    + ["COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"]
)

# Names OneDrive refuses even though plain Windows accepts them.
_ONEDRIVE_FORBIDDEN_NAMES = frozenset(["desktop.ini", ".lock"])

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def clean_name(name: str) -> str:
    """Tidy a name typed by the user: tabs/newlines become spaces, ends trimmed."""
    return re.sub(r"[\t\r\n]+", " ", name).strip()


def name_problem(name: str) -> Optional[str]:
    """Return a plain-English reason ``name`` can't be a folder/file name, or None."""
    if not name or not name.strip():
        return "The name can't be empty."

    bad = []
    for ch in name:
        if (ch in INVALID_CHARS or ord(ch) < 32) and ch not in bad:
            bad.append(ch)
    if bad:
        shown = "  ".join(("(tab/line break)" if ord(c) < 32 else c) for c in bad)
        return "The name can't contain: %s" % shown

    if name != name.strip():
        return "The name can't start or end with a space."
    if name.endswith("."):
        return "The name can't end with a period."

    base = name.split(".", 1)[0].rstrip(" ").upper()
    if base in _RESERVED_BASENAMES:
        return '"%s" is a reserved Windows name and can\'t be used.' % base

    lowered = name.lower()
    if lowered in _ONEDRIVE_FORBIDDEN_NAMES or name.startswith("~$") or "_vti_" in lowered:
        return '"%s" isn\'t allowed by Windows/OneDrive.' % name

    if len(name) > MAX_NAME_LENGTH:
        return "The name is too long (%d characters; the limit is %d)." % (
            len(name), MAX_NAME_LENGTH)
    return None


def extension_problem(ext: str) -> Optional[str]:
    """Validate a file extension such as ``.txt`` (an empty string is allowed)."""
    if ext == "":
        return None
    if not re.fullmatch(r"\.[A-Za-z0-9_\-]{1,16}", ext):
        return "The file type should look like .txt (a dot, then letters or digits)."
    return None


def sanitize_for_filename(text: str) -> str:
    """Make arbitrary text safe to embed in a file name (bad characters become '-')."""
    out = "".join("-" if (c in INVALID_CHARS or ord(c) < 32) else c for c in text)
    return out.strip().rstrip(". ")


def sibling_key(name: str) -> str:
    """Key under which two names count as the same item (Windows ignores case)."""
    return name.casefold()


def unique_name(base: str, taken) -> str:
    """Return ``base`` or ``base (2)``, ``base (3)``... so it doesn't clash with ``taken``."""
    taken_keys = {sibling_key(t) for t in taken}
    if sibling_key(base) not in taken_keys:
        return base
    n = 2
    while sibling_key("%s (%d)" % (base, n)) in taken_keys:
        n += 1
    return "%s (%d)" % (base, n)


# --------------------------------------------------------------------------- #
# Placeholders
# --------------------------------------------------------------------------- #

PLACEHOLDERS = (
    ("title", "The name you give the new folder when you create it (e.g. Xcom Diligence)"),
    ("folder", "The name of the folder the document sits in (e.g. Work product)"),
    ("template", "The name of the template"),
    ("date", "Today's date, like 2026-10-06"),
    ("date_long", "Today's date, like October 6, 2026"),
    ("year", "The current year, like 2026"),
)

_TOKEN = re.compile(r"\{([A-Za-z_]+)\}")


@dataclass(frozen=True)
class PlaceholderContext:
    title: str
    folder: str
    template: str
    today: date

    def values(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "folder": self.folder,
            "template": self.template,
            "date": self.today.isoformat(),
            "date_long": "%s %d, %d" % (
                _MONTHS[self.today.month - 1], self.today.day, self.today.year),
            "year": str(self.today.year),
        }


def resolve(text: str, ctx: PlaceholderContext, *, for_filename: bool = False) -> str:
    """Replace known ``{placeholders}`` in ``text``; unknown ones are left untouched.

    With ``for_filename`` the substituted values are made filename-safe.
    """
    values = ctx.values()

    def substitute(match: "re.Match[str]") -> str:
        value = values.get(match.group(1).lower())
        if value is None:
            return match.group(0)
        return sanitize_for_filename(value) if for_filename else value

    return _TOKEN.sub(substitute, text)


def unknown_placeholders(text: str) -> List[str]:
    """Names inside ``{braces}`` that aren't real placeholders (likely typos)."""
    known = {key for key, _ in PLACEHOLDERS}
    found: List[str] = []
    for match in _TOKEN.finditer(text):
        key = match.group(1)
        if key.lower() not in known and "{%s}" % key not in found:
            found.append("{%s}" % key)
    return found
