"""Turn a template into real folders and documents on disk.

Safety rules (this is why it lives in its own, well tested, module):

* It only ever creates folders and brand-new files.  Nothing is overwritten,
  moved or deleted - if a document already exists it is left exactly as it is.
* Everything is checked *before* the first folder is created, so a bad name can
  never leave a half-built structure behind.
* If the new top folder already exists, the missing pieces are added to it - but
  only when the caller says that is wanted (the GUI asks first).
"""

from __future__ import annotations

import codecs
import errno
import ntpath
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from .model import Folder, Template, count_docs, count_folders, normalize_newlines
from .names import (
    PlaceholderContext,
    clean_name,
    extension_problem,
    name_problem,
    resolve,
    sibling_key,
)
from .osutil import is_windows, normalize_path_text

NEWLINE = "\r\n"            # documents are written for Windows programs (Notepad, Word...)
WIN_MAX_DIR_PATH = 247      # longest folder path Windows' classic API can create
WIN_MAX_FILE_PATH = 259     # longest file path


class PlanError(Exception):
    """The request can't be carried out; ``problems`` explains why in plain English."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


class FolderExistsError(Exception):
    """The new top folder already exists and the caller didn't allow adding to it."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(path)


@dataclass(frozen=True)
class PlanItem:
    kind: str                        # "dir" or "file"
    parts: Tuple[str, ...]           # location below the destination; parts[0] is the new top folder
    content: str = ""                # file text (placeholders already filled in)

    @property
    def display(self) -> str:
        return os.sep.join(self.parts)


@dataclass
class Plan:
    items: List[PlanItem] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def _where(trail: List[str]) -> str:
    return " > ".join('"%s"' % t for t in trail)


def make_plan(template: Template, title: str, *, today: Optional[date] = None) -> Plan:
    """Work out exactly which folders and documents would be created (touches no disk)."""
    today = today or date.today()
    title = clean_name(title)
    plan = Plan()

    problem = name_problem(title)
    if problem:
        plan.problems.append("The name for the new folder: " + problem)

    def visit(folder: Folder, parts: Tuple[str, ...], trail: List[str], on_disk_name: str) -> None:
        plan.items.append(PlanItem("dir", parts))
        taken: Dict[str, str] = {}
        children: List[Folder] = []
        for child in folder.folders:
            problem = name_problem(child.name)
            if problem:
                plan.problems.append('Folder "%s" inside %s: %s' % (child.name, _where(trail), problem))
                continue
            key = sibling_key(child.name)
            if key in taken:
                plan.problems.append(
                    '%s would contain "%s" twice (Windows ignores upper/lower case).'
                    % (_where(trail), child.name))
                continue
            taken[key] = child.name
            children.append(child)

        ctx = PlaceholderContext(title, on_disk_name, template.name, today)
        for doc in folder.docs:
            if not doc.name.strip():
                plan.problems.append("A document inside %s has no name." % _where(trail))
                continue
            filename = resolve(doc.name, ctx, for_filename=True).strip() + doc.ext
            problem = extension_problem(doc.ext) or name_problem(filename)
            if problem:
                plan.problems.append(
                    'Document "%s" inside %s: %s' % (doc.file_pattern, _where(trail), problem))
                continue
            key = sibling_key(filename)
            if key in taken:
                plan.problems.append(
                    '%s would contain "%s" twice (Windows ignores upper/lower case).'
                    % (_where(trail), filename))
                continue
            taken[key] = filename
            plan.items.append(PlanItem("file", parts + (filename,), resolve(doc.content, ctx)))

        for child in children:
            visit(child, parts + (child.name,), trail + [child.name], child.name)

    visit(template.root, (title,), [template.root.name], title)
    return plan


def path_length_problems(items: List[PlanItem], destination: str,
                         windows: Optional[bool] = None) -> List[str]:
    """Windows can't create very long paths; say so up front instead of failing halfway."""
    if windows is None:
        windows = is_windows()
    if not windows:
        return []
    base = os.path.abspath(destination) if is_windows() else ntpath.normpath(destination)
    worst: Optional[Tuple[int, str]] = None
    too_long = 0
    for item in items:
        full = ntpath.join(base, *item.parts)
        limit = WIN_MAX_FILE_PATH if item.kind == "file" else WIN_MAX_DIR_PATH
        if len(full) > limit:
            too_long += 1
            if worst is None or len(full) > worst[0]:
                worst = (len(full), full)
    if worst is None:
        return []
    others = " (and %d more like it)" % (too_long - 1) if too_long > 1 else ""
    return [
        "The path would be %d characters long, but Windows can't handle paths over %d "
        "characters: %s%s\nChoose a destination closer to the top of the drive, or shorten some "
        "folder names." % (worst[0], WIN_MAX_FILE_PATH, worst[1], others)
    ]


def check_destination(destination: str) -> Optional[str]:
    if not destination.strip():
        return "Choose the folder where the new folder should be created."
    if not os.path.isdir(destination):
        return 'The destination folder "%s" doesn\'t exist.' % destination
    return None


def top_folder_state(destination: str, title: str) -> str:
    """"new", "folder" (already there - would be added to) or "file" (name taken by a file)."""
    path = os.path.join(destination, clean_name(title))
    if os.path.isdir(path):
        return "folder"
    if os.path.lexists(path):
        return "file"
    return "new"


@dataclass
class Preview:
    problems: List[str]
    destination_problem: Optional[str]
    top_path: str
    top_state: str                   # "new", "folder", "file" or "unknown"
    folder_count: int                # including the top folder
    doc_count: int

    @property
    def ok(self) -> bool:
        return not self.problems


def preview(template: Template, destination: str, title: str, *,
            today: Optional[date] = None, windows: Optional[bool] = None) -> Preview:
    """Everything the window needs to describe what Create will do (touches no disk)."""
    destination = normalize_path_text(destination)
    title = clean_name(title)
    plan = make_plan(template, title, today=today)
    problems = list(plan.problems)

    destination_problem = check_destination(destination)
    state = "unknown"
    top_path = os.path.join(destination, title) if destination else title
    if destination_problem is None:
        state = top_folder_state(destination, title) if not name_problem(title) else "unknown"
        if state == "file":
            problems.append('A file named "%s" already exists in that folder, so a folder with '
                            'that name can\'t be created.' % title)
        if not plan.problems:
            problems.extend(path_length_problems(plan.items, destination, windows))
    else:
        problems.insert(0, destination_problem)

    return Preview(
        problems=problems,
        destination_problem=destination_problem,
        top_path=top_path,
        top_state=state,
        folder_count=sum(1 for i in plan.items if i.kind == "dir"),
        doc_count=sum(1 for i in plan.items if i.kind == "file"),
    )


# --------------------------------------------------------------------------- #
# Doing it
# --------------------------------------------------------------------------- #

def _plural(n: int, word: str) -> str:
    return "%d %s" % (n, word if n == 1 else word + "s")


@dataclass
class CreationResult:
    top_path: str
    top_existed: bool
    folders_created: List[str] = field(default_factory=list)
    folders_existing: List[str] = field(default_factory=list)
    docs_created: List[str] = field(default_factory=list)
    docs_skipped: List[str] = field(default_factory=list)      # already existed; left untouched
    errors: List[Tuple[str, str]] = field(default_factory=list)  # (item, reason)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        name = os.path.basename(self.top_path)
        new_subfolders = len(self.folders_created) - (0 if self.top_existed else 1)
        made = []
        if new_subfolders > 0:
            made.append(_plural(new_subfolders, "sub folder"))
        if self.docs_created:
            made.append(_plural(len(self.docs_created), "document"))
        what = " and ".join(made)
        if not self.top_existed:
            text = 'Created "%s"' % name + (" with %s." % what if what else ".")
        elif what:
            text = '"%s" already existed. Added %s.' % (name, what)
        else:
            text = ('"%s" already existed and already has everything in this template - '
                    "nothing was added." % name)
        if self.docs_skipped:
            text += " (%s already existed and was left as it was.)" % _plural(
                len(self.docs_skipped), "document")
        return text


def describe_os_error(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "permission was denied - the location may be read-only or in use"
    if isinstance(exc, FileExistsError):
        return "a file with that name already exists"
    if getattr(exc, "winerror", None) == 206 or exc.errno == errno.ENAMETOOLONG:
        return "the path is too long for Windows"
    if exc.errno == errno.ENOSPC:
        return "the disk is full"
    if isinstance(exc, FileNotFoundError):
        return ("the location couldn't be found (it may have been moved or disconnected, "
                "or the path is too long)")
    return exc.strerror or str(exc)


def encode_document(text: str) -> bytes:
    """UTF-8 with Windows line endings; a BOM is added only when non-ASCII text needs it."""
    text = normalize_newlines(text).replace("\n", NEWLINE)
    data = text.encode("utf-8")
    return data if text.isascii() else codecs.BOM_UTF8 + data


def _write_new_file(path: str, data: bytes) -> bool:
    """Create ``path`` with ``data``.  Returns False (touching nothing) if it already exists."""
    try:
        with open(path, "xb") as handle:
            handle.write(data)
        return True
    except FileExistsError:
        return False


def create_from_template(template: Template, destination: str, title: str, *,
                         allow_existing: bool = False, today: Optional[date] = None,
                         windows: Optional[bool] = None) -> CreationResult:
    """Create ``<destination>/<title>/...`` from ``template``.

    Raises :class:`PlanError` (nothing has been created) if anything is wrong with
    the request, or :class:`FolderExistsError` if the folder is already there and
    ``allow_existing`` is false.  Problems that happen *while* creating (a
    permission error, say) don't stop the run; they're listed in the result.
    """
    destination = normalize_path_text(destination)
    title = clean_name(title)
    info = preview(template, destination, title, today=today, windows=windows)
    if not info.ok:
        raise PlanError(info.problems)
    if info.top_state == "folder" and not allow_existing:
        raise FolderExistsError(info.top_path)

    plan = make_plan(template, title, today=today)
    result = CreationResult(top_path=info.top_path, top_existed=info.top_state == "folder")
    failed_dirs: List[Tuple[str, ...]] = []
    for item in plan.items:
        if any(item.parts[:len(prefix)] == prefix for prefix in failed_dirs):
            continue                      # its parent folder couldn't be made
        path = os.path.join(destination, *item.parts)
        shown = item.display
        try:
            if item.kind == "dir":
                existed = os.path.isdir(path)
                os.makedirs(path, exist_ok=True)
                (result.folders_existing if existed else result.folders_created).append(shown)
            elif os.path.isdir(path):
                result.errors.append((shown, "a folder with that name already exists"))
            elif _write_new_file(path, encode_document(item.content)):
                result.docs_created.append(shown)
            else:
                result.docs_skipped.append(shown)
        except OSError as exc:
            result.errors.append((shown, describe_os_error(exc)))
            if item.kind == "dir":
                failed_dirs.append(item.parts)
    return result


def template_stats(template: Template) -> Tuple[int, int]:
    """(sub folders, documents) - the top folder isn't counted."""
    return count_folders(template.root) - 1, count_docs(template.root)
