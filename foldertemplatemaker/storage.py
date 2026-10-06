"""Saving and loading templates and settings.

Everything lives in two small JSON files inside the program's data folder
(``%APPDATA%\\FolderTemplateMaker`` on Windows):

* ``templates.json`` - all saved templates
* ``settings.json``  - last used locations, window size, etc.

Writes are atomic (a temporary file is swapped in), the previous version is
kept as ``templates.json.bak``, and a file that can't be read is set aside under
a new name - it is never silently overwritten.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import osutil
from .model import (
    Template,
    TemplateError,
    sample_template,
    template_from_dict,
    template_to_dict,
)
from .names import sibling_key, unique_name

TEMPLATES_FILE = "templates.json"
SETTINGS_FILE = "settings.json"
FORMAT_VERSION = 1
EXPORT_FORMAT = "folder-template-maker/template"
MAX_RECENT_DESTINATIONS = 12


class StorageError(Exception):
    """Something about saving/loading went wrong; the message is fit to show the user."""


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _is_valid_json_file(path: str) -> bool:
    try:
        read_json(path)
        return True
    except (OSError, ValueError):
        return False


def write_json_atomic(path: str, data: Any, *, keep_backup: bool = False) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if keep_backup and os.path.isfile(path) and _is_valid_json_file(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    _replace_with_retry(tmp, path)


def _replace_with_retry(source: str, target: str, attempts: int = 5) -> None:
    """``os.replace`` that waits out the short locks antivirus / sync tools put on files."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def set_aside(path: str) -> str:
    """Rename an unreadable file to ``<name>.damaged-<timestamp>``; returns the new path."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = "%s.damaged-%s" % (path, stamp)
    n = 1
    while os.path.exists(target):
        n += 1
        target = "%s.damaged-%s-%d" % (path, stamp, n)
    os.replace(path, target)
    return target


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

@dataclass
class Settings:
    last_template_id: str = ""
    destination: str = ""                                   # last destination used
    destination_by_template: Dict[str, str] = field(default_factory=dict)
    recent_destinations: List[str] = field(default_factory=list)
    open_after_create: bool = False
    geometry: str = ""                                      # e.g. "1000x680+120+80"

    def destination_for(self, template_id: str) -> str:
        return self.destination_by_template.get(template_id) or self.destination

    def remember_destination(self, template_id: str, path: str) -> None:
        self.destination = path
        self.destination_by_template[template_id] = path
        self.recent_destinations = [p for p in self.recent_destinations if not _same_path(p, path)]
        self.recent_destinations.insert(0, path)
        del self.recent_destinations[MAX_RECENT_DESTINATIONS:]

    def forget_template(self, template_id: str) -> None:
        self.destination_by_template.pop(template_id, None)
        if self.last_template_id == template_id:
            self.last_template_id = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "last_template_id": self.last_template_id,
            "destination": self.destination,
            "destination_by_template": self.destination_by_template,
            "recent_destinations": self.recent_destinations,
            "open_after_create": self.open_after_create,
            "geometry": self.geometry,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        settings = cls()
        if not isinstance(data, dict):
            return settings

        def text(key: str) -> str:
            value = data.get(key)
            return value if isinstance(value, str) else ""

        settings.last_template_id = text("last_template_id")
        settings.destination = text("destination")
        settings.geometry = text("geometry")
        settings.open_after_create = data.get("open_after_create") is True
        by_template = data.get("destination_by_template")
        if isinstance(by_template, dict):
            settings.destination_by_template = {
                k: v for k, v in by_template.items() if isinstance(k, str) and isinstance(v, str)}
        recents = data.get("recent_destinations")
        if isinstance(recents, list):
            settings.recent_destinations = [p for p in recents if isinstance(p, str) and p][
                :MAX_RECENT_DESTINATIONS]
        return settings


# --------------------------------------------------------------------------- #
# Template files shared between computers
# --------------------------------------------------------------------------- #

def export_template(template: Template, path: str) -> None:
    write_json_atomic(path, {
        "format": EXPORT_FORMAT,
        "version": FORMAT_VERSION,
        "template": template_to_dict(template),
    })


def read_template_file(path: str) -> List[Template]:
    """Read templates from an exported template file (or from a whole templates.json)."""
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        raise StorageError("That file couldn't be read as a template file (%s)." % exc) from exc
    entries: Any
    if isinstance(data, dict) and isinstance(data.get("template"), dict):
        entries = [data["template"]]
    elif isinstance(data, dict) and isinstance(data.get("templates"), list):
        entries = data["templates"]
    elif isinstance(data, dict) and "root" in data:
        entries = [data]
    elif isinstance(data, list):
        entries = data
    else:
        raise StorageError("That file doesn't look like a Folder Template Maker template.")
    found: List[Template] = []
    for entry in entries:
        try:
            found.append(template_from_dict(entry))
        except TemplateError:
            continue
    if not found:
        raise StorageError("That file doesn't contain any templates.")
    return found


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #

class Store:
    """All saved templates plus the settings, backed by files in ``directory``."""

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or osutil.app_data_dir()
        self.templates: List[Template] = []
        self.settings = Settings()
        self.warnings: List[str] = []
        self._templates_locked = False       # set if templates.json is unreadable AND can't be moved

    # -- paths ------------------------------------------------------------- #

    @property
    def templates_path(self) -> str:
        return os.path.join(self.directory, TEMPLATES_FILE)

    @property
    def settings_path(self) -> str:
        return os.path.join(self.directory, SETTINGS_FILE)

    # -- loading ----------------------------------------------------------- #

    def load(self) -> None:
        self.warnings = []
        self._load_templates()
        self._load_settings()

    def _parse_templates_file(self, path: str) -> List[Template]:
        data = read_json(path)
        entries = data.get("templates") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise ValueError("no template list found")
        templates: List[Template] = []
        for entry in entries:
            try:
                templates.append(template_from_dict(entry))
            except TemplateError:
                continue
        # Repair accidental duplicates (e.g. from hand editing) so ids and names stay unique.
        seen_ids, seen_names = set(), []
        for template in templates:
            if template.id in seen_ids:
                template.id = uuid.uuid4().hex
            seen_ids.add(template.id)
            template.name = unique_name(template.name, seen_names)
            seen_names.append(template.name)
        return templates

    def _load_templates(self) -> None:
        path = self.templates_path
        if not os.path.exists(path):
            self.templates = [sample_template()]
            try:
                self.save_templates()
            except OSError as exc:
                self.warnings.append("Templates can't be saved in %s (%s)." % (self.directory, exc))
            return
        try:
            self.templates = self._parse_templates_file(path)
            return
        except (OSError, ValueError) as exc:
            reason = str(exc)
        # The file is damaged or unreadable: keep it, then fall back to the backup.
        try:
            kept = set_aside(path)
        except OSError:
            self._templates_locked = True
            self.templates = [sample_template()]
            self.warnings.append(
                "Your templates file (%s) couldn't be read (%s) and couldn't be moved aside, so "
                "changes to templates will NOT be saved until that is fixed." % (path, reason))
            return
        backup = path + ".bak"
        try:
            self.templates = self._parse_templates_file(backup)
            self.warnings.append(
                "Your templates file was damaged (%s), so the most recent backup was loaded "
                "instead. The damaged file was kept as:\n%s" % (reason, kept))
        except (OSError, ValueError):
            self.templates = [sample_template()]
            self.warnings.append(
                "Your templates file was damaged (%s) and there was no usable backup, so the "
                "example template was loaded. The damaged file was kept as:\n%s" % (reason, kept))
        try:
            self.save_templates()
        except OSError:
            pass

    def _load_settings(self) -> None:
        path = self.settings_path
        if not os.path.exists(path):
            return
        try:
            self.settings = Settings.from_dict(read_json(path))
        except (OSError, ValueError):
            try:
                set_aside(path)
            except OSError:
                pass
            self.settings = Settings()

    # -- saving ------------------------------------------------------------ #

    def save_templates(self) -> None:
        if self._templates_locked:
            raise StorageError("Templates can't be saved because the templates file in %s is "
                               "unreadable." % self.directory)
        write_json_atomic(self.templates_path, {
            "version": FORMAT_VERSION,
            "templates": [template_to_dict(t) for t in self.templates],
        }, keep_backup=True)

    def save_settings(self) -> None:
        write_json_atomic(self.settings_path, self.settings.to_dict())

    # -- template list ------------------------------------------------------ #

    def get(self, template_id: str) -> Optional[Template]:
        for template in self.templates:
            if template.id == template_id:
                return template
        return None

    def name_taken(self, name: str, ignore_id: Optional[str] = None) -> bool:
        key = sibling_key(name.strip())
        return any(t.id != ignore_id and sibling_key(t.name) == key for t in self.templates)

    def unique_template_name(self, base: str) -> str:
        return unique_name(base, [t.name for t in self.templates])

    def add(self, template: Template, *, after_id: Optional[str] = None) -> Template:
        """Add a template (made independent of the caller's copy) and save."""
        if self.name_taken(template.name):
            raise TemplateError('There is already a template called "%s".' % template.name)
        stored = template.clone()
        position = len(self.templates)
        if after_id is not None:
            for i, existing in enumerate(self.templates):
                if existing.id == after_id:
                    position = i + 1
                    break
        self.templates.insert(position, stored)
        self.save_templates()
        return stored

    def update(self, template: Template) -> Template:
        """Replace the saved template that has the same id, and save."""
        if not template.name.strip():
            raise TemplateError("The template needs a name.")
        if self.name_taken(template.name, ignore_id=template.id):
            raise TemplateError('There is already a template called "%s".' % template.name)
        for i, existing in enumerate(self.templates):
            if existing.id == template.id:
                stored = template.clone()
                self.templates[i] = stored
                self.save_templates()
                return stored
        raise TemplateError("That template no longer exists.")

    def delete(self, template_id: str) -> None:
        self.templates = [t for t in self.templates if t.id != template_id]
        self.settings.forget_template(template_id)
        self.save_templates()
        self.save_settings()

    def import_templates(self, templates: List[Template]) -> List[Template]:
        """Add templates read from a file as new, independent templates."""
        added = []
        for template in templates:
            copy = template.clone(new_id=True)
            copy.name = self.unique_template_name(copy.name)
            added.append(self.add(copy))
        return added
