"""The template data model and the editing operations on it.

Nothing in here touches the disk except :func:`folder_from_disk`, which only
*reads* a folder so it can be turned into a template.

A template is a tree of :class:`Folder` objects.  The top (root) folder's name is
the default name for the folder that gets created.  Any folder can also carry
:class:`DocSpec` entries - small text documents generated when the template is
applied (their name and text may contain ``{placeholders}``, see ``names.py``).
"""

from __future__ import annotations

import itertools
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from .names import (
    PlaceholderContext,
    clean_name,
    extension_problem,
    name_problem,
    resolve,
    sibling_key,
    unique_name,
)

MAX_DEPTH = 64            # how deep folders may nest (guards against hand-edited files)
MAX_OUTLINE_FOLDERS = 2000

_uids = itertools.count(1)


def _next_uid() -> int:
    return next(_uids)


class TemplateError(ValueError):
    """A problem with a template, worded so it can be shown to the user as-is."""


@dataclass(eq=False)
class DocSpec:
    """A text document that will be written into a folder when the template is used."""

    name: str = "{title} raw data"   # file name without extension; may hold placeholders
    ext: str = ".txt"                # includes the dot, or "" for none
    content: str = ""                # may hold placeholders
    uid: int = field(default_factory=_next_uid, repr=False)

    @property
    def file_pattern(self) -> str:
        return self.name + self.ext

    def clone(self) -> "DocSpec":
        return DocSpec(self.name, self.ext, self.content)


@dataclass(eq=False)
class Folder:
    name: str = "New folder"
    folders: List["Folder"] = field(default_factory=list)
    docs: List[DocSpec] = field(default_factory=list)
    uid: int = field(default_factory=_next_uid, repr=False)

    def clone(self) -> "Folder":
        return Folder(
            self.name,
            [f.clone() for f in self.folders],
            [d.clone() for d in self.docs],
        )


Node = Union[Folder, DocSpec]


@dataclass(eq=False)
class Template:
    name: str
    root: Folder
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def clone(self, *, new_id: bool = False) -> "Template":
        copy = Template(self.name, self.root.clone())
        if not new_id:
            copy.id = self.id
        return copy


# --------------------------------------------------------------------------- #
# Walking / measuring
# --------------------------------------------------------------------------- #

def iter_folders(root: Folder) -> Iterator[Folder]:
    """Every folder in the tree, parents before children (includes ``root``)."""
    yield root
    for child in root.folders:
        yield from iter_folders(child)


def iter_docs(root: Folder) -> Iterator[DocSpec]:
    for folder in iter_folders(root):
        yield from folder.docs


def count_folders(root: Folder) -> int:
    return sum(1 for _ in iter_folders(root))


def count_docs(root: Folder) -> int:
    return sum(1 for _ in iter_docs(root))


def contains(ancestor: Folder, node: Node) -> bool:
    """True if ``node`` is ``ancestor`` itself or sits anywhere beneath it."""
    if ancestor is node:
        return True
    if any(d is node for d in ancestor.docs):
        return True
    return any(contains(f, node) for f in ancestor.folders)


def find_parent(root: Folder, target: Node) -> Optional[Folder]:
    """The folder directly holding ``target`` (None for the root or if not found)."""
    for folder in iter_folders(root):
        if any(f is target for f in folder.folders) or any(d is target for d in folder.docs):
            return folder
    return None


def find_by_uid(root: Folder, uid: int) -> Optional[Node]:
    for folder in iter_folders(root):
        if folder.uid == uid:
            return folder
        for doc in folder.docs:
            if doc.uid == uid:
                return doc
    return None


# --------------------------------------------------------------------------- #
# Editing operations (each raises TemplateError with a friendly message)
# --------------------------------------------------------------------------- #

def _insert(items: list, item: Node, before: Optional[Node]) -> None:
    if before is not None:
        for i, other in enumerate(items):
            if other is before:
                items.insert(i, item)
                return
    items.append(item)


def _detach(items: list, item: Node) -> None:
    for i, other in enumerate(items):
        if other is item:
            del items[i]
            return


def _ensure_free_folder_name(parent: Folder, name: str, ignore: Optional[Folder] = None) -> None:
    key = sibling_key(name)
    for sibling in parent.folders:
        if sibling is not ignore and sibling_key(sibling.name) == key:
            raise TemplateError(
                '"%s" already contains a folder named "%s".' % (parent.name, sibling.name))


def _ensure_free_doc_name(folder: Folder, doc: DocSpec, ignore: Optional[DocSpec] = None) -> None:
    key = sibling_key(doc.file_pattern)
    for other in folder.docs:
        if other is not ignore and sibling_key(other.file_pattern) == key:
            raise TemplateError(
                '"%s" already contains a document named "%s".' % (folder.name, other.file_pattern))


def add_folder(parent: Folder, name: Optional[str] = None, *,
               before: Optional[Folder] = None) -> Folder:
    """Add a sub folder.  Without a ``name`` an unused "New folder" name is chosen."""
    if name is None:
        name = unique_name("New folder", [f.name for f in parent.folders])
    else:
        name = clean_name(name)
        problem = name_problem(name)
        if problem:
            raise TemplateError(problem)
        _ensure_free_folder_name(parent, name)
    folder = Folder(name)
    _insert(parent.folders, folder, before)
    return folder


def rename_folder(root: Folder, folder: Folder, new_name: str) -> None:
    new_name = clean_name(new_name)
    problem = name_problem(new_name)
    if problem:
        raise TemplateError(problem)
    parent = find_parent(root, folder)
    if parent is not None:
        _ensure_free_folder_name(parent, new_name, ignore=folder)
    folder.name = new_name


def remove_node(root: Folder, node: Node) -> None:
    parent = find_parent(root, node)
    if parent is None:
        raise TemplateError("The top folder can't be deleted.")
    _detach(parent.folders if isinstance(node, Folder) else parent.docs, node)


def move_node(root: Folder, node: Node, new_parent: Folder,
              before: Optional[Node] = None) -> None:
    """Move ``node`` into ``new_parent``, just before ``before`` (or at the end)."""
    old_parent = find_parent(root, node)
    if old_parent is None:
        raise TemplateError("The top folder can't be moved.")
    if isinstance(node, Folder) and contains(node, new_parent):
        raise TemplateError("A folder can't be moved into itself.")
    if before is node:
        return
    if new_parent is not old_parent:
        if isinstance(node, Folder):
            _ensure_free_folder_name(new_parent, node.name)
        else:
            _ensure_free_doc_name(new_parent, node)
    is_folder = isinstance(node, Folder)
    _detach(old_parent.folders if is_folder else old_parent.docs, node)
    _insert(new_parent.folders if is_folder else new_parent.docs, node, before)


def _siblings(root: Folder, node: Node) -> Tuple[Optional[Folder], list]:
    parent = find_parent(root, node)
    if parent is None:
        return None, []
    return parent, (parent.folders if isinstance(node, Folder) else parent.docs)


def move_up(root: Folder, node: Node) -> bool:
    parent, items = _siblings(root, node)
    if parent is None:
        return False
    for i, item in enumerate(items):
        if item is node:
            if i == 0:
                return False
            items[i - 1], items[i] = items[i], items[i - 1]
            return True
    return False


def move_down(root: Folder, node: Node) -> bool:
    parent, items = _siblings(root, node)
    if parent is None:
        return False
    for i, item in enumerate(items):
        if item is node:
            if i == len(items) - 1:
                return False
            items[i + 1], items[i] = items[i], items[i + 1]
            return True
    return False


def indent(root: Folder, node: Node) -> bool:
    """Make a folder a sub folder of the folder just above it."""
    if not isinstance(node, Folder):
        return False
    parent, items = _siblings(root, node)
    if parent is None:
        return False
    index = next(i for i, item in enumerate(items) if item is node)
    if index == 0:
        return False
    target = items[index - 1]
    _ensure_free_folder_name(target, node.name)
    _detach(items, node)
    target.folders.append(node)
    return True


def outdent(root: Folder, node: Node) -> bool:
    """Move a folder/document up one level, to sit just after its current parent."""
    parent = find_parent(root, node)
    if parent is None:
        return False
    grand = find_parent(root, parent)
    if grand is None:
        return False
    if isinstance(node, Folder):
        _ensure_free_folder_name(grand, node.name)
        _detach(parent.folders, node)
        after = None
        for i, sibling in enumerate(grand.folders):
            if sibling is parent:
                after = grand.folders[i + 1] if i + 1 < len(grand.folders) else None
                break
        _insert(grand.folders, node, after)
    else:
        _ensure_free_doc_name(grand, node)
        _detach(parent.docs, node)
        grand.docs.append(node)
    return True


def doc_problem(doc: DocSpec, template_name: str = "Template") -> Optional[str]:
    """Check a document's name pattern by trying it with sample values."""
    if not doc.name.strip():
        return "The document needs a name."
    problem = extension_problem(doc.ext)
    if problem:
        return problem
    sample = PlaceholderContext("Sample title", "Sample folder", template_name, date.today())
    final = resolve(doc.name, sample, for_filename=True).strip() + doc.ext
    problem = name_problem(final)
    if problem:
        return "That document name won't work: " + problem[0].lower() + problem[1:]
    return None


def add_doc(folder: Folder, doc: Optional[DocSpec] = None) -> DocSpec:
    doc = doc or DocSpec()
    problem = doc_problem(doc)
    if problem:
        raise TemplateError(problem)
    _ensure_free_doc_name(folder, doc)
    folder.docs.append(doc)
    return doc


def update_doc(folder: Folder, doc: DocSpec, name: str, ext: str, content: str) -> None:
    candidate = DocSpec(name.strip(), ext, normalize_newlines(content))
    problem = doc_problem(candidate)
    if problem:
        raise TemplateError(problem)
    _ensure_free_doc_name(folder, candidate, ignore=doc)
    doc.name, doc.ext, doc.content = candidate.name, candidate.ext, candidate.content


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --------------------------------------------------------------------------- #
# Turning pasted text into folders
# --------------------------------------------------------------------------- #

_BULLET = re.compile(r"^[-–—*•·▪●]+\s+")


def parse_outline(text: str) -> Tuple[List[Folder], List[str]]:
    """Turn indented lines of text into folders.

    One folder per line; a line indented deeper than the one above becomes its
    sub folder.  Leading bullets ("-", "*", "•") are ignored.  Returns the top level
    folders and a list of problems (the folders must not be used if there are any).
    """
    top: List[Folder] = []
    problems: List[str] = []
    stack: List[Tuple[int, Folder]] = []
    total = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        expanded = raw.expandtabs(4)
        indent_width = len(expanded) - len(expanded.lstrip(" "))
        name = clean_name(_BULLET.sub("", expanded.strip()))
        problem = name_problem(name)
        if problem:
            problems.append("Line %d (%s): %s" % (number, name or raw.strip(), problem))
            continue
        while stack and stack[-1][0] >= indent_width:
            stack.pop()
        if len(stack) >= MAX_DEPTH:
            problems.append("Line %d: folders are nested too deeply." % number)
            continue
        siblings = stack[-1][1].folders if stack else top
        if any(sibling_key(s.name) == sibling_key(name) for s in siblings):
            problems.append('Line %d: "%s" appears twice in the same folder.' % (number, name))
            continue
        total += 1
        if total > MAX_OUTLINE_FOLDERS:
            problems.append("That's too many folders at once (limit %d)." % MAX_OUTLINE_FOLDERS)
            break
        folder = Folder(name)
        siblings.append(folder)
        stack.append((indent_width, folder))
    return top, problems


# --------------------------------------------------------------------------- #
# Saving / loading (plain dicts, so they can be written as JSON)
# --------------------------------------------------------------------------- #

def _as_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def doc_to_dict(doc: DocSpec) -> Dict[str, Any]:
    return {"name": doc.name, "ext": doc.ext, "content": doc.content}


def folder_to_dict(folder: Folder) -> Dict[str, Any]:
    return {
        "name": folder.name,
        "folders": [folder_to_dict(f) for f in folder.folders],
        "documents": [doc_to_dict(d) for d in folder.docs],
    }


def template_to_dict(template: Template) -> Dict[str, Any]:
    return {"id": template.id, "name": template.name, "root": folder_to_dict(template.root)}


def folder_from_dict(data: Any, _depth: int = 0) -> Folder:
    if not isinstance(data, dict):
        raise TemplateError("A folder entry in the file isn't in the expected format.")
    folder = Folder(_as_str(data.get("name"), "New folder"))
    children = data.get("folders")
    if isinstance(children, list) and _depth < MAX_DEPTH:
        for child in children:
            try:
                folder.folders.append(folder_from_dict(child, _depth + 1))
            except TemplateError:
                continue
    documents = data.get("documents")
    if isinstance(documents, list):
        for entry in documents:
            if not isinstance(entry, dict):
                continue
            ext = _as_str(entry.get("ext"), ".txt")
            if ext and not ext.startswith("."):
                ext = "." + ext
            folder.docs.append(DocSpec(
                _as_str(entry.get("name"), "Document"),
                ext,
                normalize_newlines(_as_str(entry.get("content"))),
            ))
    return folder


def template_from_dict(data: Any) -> Template:
    if not isinstance(data, dict):
        raise TemplateError("A template in the file isn't in the expected format.")
    root = folder_from_dict(data.get("root") if "root" in data else {"name": data.get("name")})
    name = clean_name(_as_str(data.get("name"), "")) or root.name or "Untitled template"
    template = Template(name, root)
    template_id = data.get("id")
    if isinstance(template_id, str) and template_id.strip():
        template.id = template_id
    return template


def structure_of(folder: Folder) -> Dict[str, Any]:
    """Like ``folder_to_dict`` - handy for comparing two trees in tests."""
    return folder_to_dict(folder)


# --------------------------------------------------------------------------- #
# Starter content
# --------------------------------------------------------------------------- #

def sample_template() -> Template:
    """The example template offered on first run."""
    root = Folder("Diligence folder")
    root.folders.append(Folder("Source documents"))
    work = Folder("Work product")
    work.docs.append(DocSpec(
        "{title} raw data", ".txt",
        "Raw data - {title}\nCreated {date_long}\n\n"))
    root.folders.append(work)
    root.folders.append(Folder("Correspondence"))
    return Template("Diligence folder template", root)


# --------------------------------------------------------------------------- #
# Reading an existing folder on disk (read-only)
# --------------------------------------------------------------------------- #

@dataclass
class ImportReport:
    folders: int = 0                 # sub folders imported (not counting the top one)
    files_ignored: int = 0           # only the folder structure is imported
    skipped: List[str] = field(default_factory=list)
    truncated: bool = False


_SKIP_DIRS = frozenset(["$recycle.bin", "system volume information"])
_WIN_HIDDEN_OR_SYSTEM = 0x2 | 0x4   # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


def natural_key(name: str) -> list:
    """Sort key that orders "2 Tax" before "10 Misc", like Windows Explorer does."""
    parts = re.split(r"(\d+)", name)
    return [int(p) if i % 2 else p.casefold() for i, p in enumerate(parts)]


def folder_from_disk(path: str, *, max_folders: int = 2000,
                     max_depth: int = 32) -> Tuple[Folder, ImportReport]:
    """Build a Folder tree from the sub folders found under ``path``.

    Only folders are imported; files are counted and ignored.  Hidden/system
    folders, shortcuts/links and unreadable folders are skipped.
    """
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise TemplateError("That isn't a folder I can read.")
    report = ImportReport()
    root_name = clean_name(os.path.basename(os.path.normpath(path)))
    if name_problem(root_name):
        root_name = "Imported folder"
    root = Folder(root_name)

    def scan(directory: str, into: Folder, depth: int) -> None:
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: natural_key(e.name))
        except OSError:
            report.skipped.append(directory)
            return
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if not is_dir:
                if not entry.is_symlink():
                    report.files_ignored += 1
                continue
            name = entry.name
            attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) \
                if os.name == "nt" else 0
            if name.lower() in _SKIP_DIRS or attrs & _WIN_HIDDEN_OR_SYSTEM:
                report.skipped.append(name)
                continue
            if name_problem(name):
                report.skipped.append(name)
                continue
            if report.folders >= max_folders or depth >= max_depth:
                report.truncated = True
                continue
            report.folders += 1
            child = Folder(name)
            into.folders.append(child)
            scan(entry.path, child, depth + 1)

    scan(path, root, 1)
    return root, report
