"""The main window."""

from __future__ import annotations

import os
import re
import time
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import List, Optional

from . import APP_NAME, __version__, builder, model, osutil, storage
from .dialogs import TextDialog
from .editor import StructureEditor
from .icons import Icons
from .model import Folder, Template, TemplateError
from .names import clean_name, name_problem
from .storage import Store, StorageError
from .widgets import Tooltip

ERROR_FG = "#b00020"
OK_FG = "#1b6e2b"
HINT_FG = "#555555"
WARN_FG = "#8a5a00"
CREATE_BG = "#2e7d32"
CREATE_BG_ACTIVE = "#1b5e20"

HELP_TEXT = """# What this program does
Folder Template Maker lets you design a folder structure once - a top folder with as many subfolders as you like - save it as a template, and then create a fresh copy of it anywhere, with any name you like, in a single click.

# Making a template
1. Click New under "My templates" (or choose File > New template).
2. Type a Template name (how it appears in your list) and a Top folder name (the name of the folder that gets created, unless you type a different one when you use the template).
3. Select the top folder in the tree and click Add subfolder. Type a name and press Enter - keep typing names and pressing Enter to add more. Press Esc (or press Enter on an empty line) when you're done.
4. Use Move up / Move down / Move in / Move out, or drag and drop, to rearrange. Press F2 or double-click to rename. Delete removes the selected item from the template.
5. Click Save template.

Already have a folder you like? Choose File > Import template from an existing folder and it becomes a template (only the folders are imported; files inside are ignored).

# Creating folders from a template
1. Pick the template in the list.
2. Choose where the new folder should go: click Browse, use Quick places (OneDrive, Documents, Desktop and recent locations), or paste a path.
3. Type the name for the new folder - it starts out as the template's top folder name.
4. Click Create folders (or press Enter in the name box).

Nothing that already exists is ever changed or deleted. If a folder with that name is already there, you are asked whether to add the missing pieces to it.

# Documents
Select a folder and click Add document to have a text file created in that folder every time you use the template. The document's name and its text can contain placeholders, which are filled in when the folder is created:

  {title}      the name you give the new folder (e.g. Xcom Diligence)
  {folder}     the name of the folder the document sits in (e.g. Work product)
  {template}   the name of the template
  {date}       today's date, like 2026-10-06
  {date_long}  today's date, like October 6, 2026
  {year}       the year, like 2026

Example: a document named "{title} raw data" inside the "Work product" folder is created as "Xcom Diligence raw data.txt".

# Good to know
Names follow the Windows (and OneDrive) rules: they can't contain  \\ / : * ? " < > |  and can't end with a space or a period.
Two items in the same folder can't have the same name (Windows ignores capital letters).
"""


class App(tk.Tk):
    """The Folder Template Maker window."""

    def __init__(self, store: Optional[Store] = None):
        super().__init__()
        self.withdraw()
        if store is None:
            store = Store()
            store.load()
        self.store = store
        self.current: Optional[Template] = None          # the working copy being edited
        self.dirty = False
        self.name_is_default = True                      # "Name the folder" still follows the top folder
        self._guard = False                              # stops our own updates re-triggering traces
        self._preview_job: Optional[str] = None
        self._suppress_preview = False
        self.last_created: Optional[str] = None

        self.title(APP_NAME)
        self.report_callback_exception = self._report_exception
        self._setup_style()
        self._build_menu()
        self._build_widgets()
        self._restore_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-s>", lambda _e: self.save())
        self.bind("<Control-n>", lambda _e: self.new_template())
        self.bind("<Control-Return>", lambda _e: self.create())

        self._fill_template_list()
        wanted = self.store.settings.last_template_id
        first = self.store.get(wanted) or (self.store.templates[0] if self.store.templates else None)
        self._load_template(first)
        self.deiconify()
        self.update_idletasks()
        if self.store.warnings:
            self.after(300, lambda: self.error("Heads up", "\n\n".join(self.store.warnings)))

    # ------------------------------------------------------------------ #
    # Services the editor (and tests) use; override-friendly
    # ------------------------------------------------------------------ #

    def confirm(self, title: str, message: str, default_no: bool = True) -> bool:
        return messagebox.askyesno(title, message, parent=self, icon="warning",
                                   default="no" if default_no else "yes")

    def error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self)

    def info(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self)

    def ask_save_changes(self) -> str:
        """"save", "discard" or "cancel"."""
        name = self.current.name if self.current else "this template"
        answer = messagebox.askyesnocancel(
            "Unsaved changes", 'Save your changes to "%s"?' % name, parent=self,
            icon="warning", default="yes")
        return "cancel" if answer is None else ("save" if answer else "discard")

    def pick_directory(self, title: str, initial: str) -> str:
        path = filedialog.askdirectory(parent=self, title=title, initialdir=initial or None,
                                       mustexist=True)
        return os.path.normpath(path) if path else ""

    def pick_open_file(self, title: str) -> str:
        return filedialog.askopenfilename(
            parent=self, title=title,
            filetypes=[("Template files", "*.json"), ("All files", "*.*")])

    def pick_save_file(self, title: str, initial_name: str) -> str:
        return filedialog.asksaveasfilename(
            parent=self, title=title, initialfile=initial_name, defaultextension=".json",
            filetypes=[("Template files", "*.json"), ("All files", "*.*")])

    def template_name(self) -> str:
        return self.current.name if self.current else ""

    def sample_title(self) -> str:
        """What {title} will stand for - the name currently typed in the Create box."""
        name = clean_name(self.name_var.get())
        if name and not name_problem(name):
            return name
        return self.current.root.name if self.current else "Title"

    # ------------------------------------------------------------------ #
    # Look and feel
    # ------------------------------------------------------------------ #

    def px(self, n: int) -> int:
        return max(1, int(round(n * self.scale)))

    def _setup_style(self) -> None:
        self.scale = float(self.tk.call("tk", "scaling")) / (96.0 / 72.0)
        style = ttk.Style(self)
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(size=10)
            except tk.TclError:
                pass
        self.bold = tkfont.nametofont("TkDefaultFont").copy()
        self.bold.configure(weight="bold")
        self.big_bold = tkfont.nametofont("TkDefaultFont").copy()
        self.big_bold.configure(weight="bold", size=11)
        style.configure("Treeview", rowheight=self.px(24), indent=self.px(22))
        style.configure("Bold.TLabel", font=self.bold)
        style.configure("Hint.TLabel", foreground=HINT_FG)
        style.configure("TLabelframe.Label", font=self.bold)
        self.icons = Icons(self, self.px(16))

    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="New template", accelerator="Ctrl+N", command=self.new_template)
        file_menu.add_command(label="Save template", accelerator="Ctrl+S", command=self.save)
        file_menu.add_separator()
        file_menu.add_command(label="Import template from an existing folder…",
                              command=self.import_from_folder)
        file_menu.add_command(label="Import template file…", command=self.import_template_file)
        file_menu.add_command(label="Export this template to a file…",
                              command=self.export_template)
        file_menu.add_separator()
        file_menu.add_command(label="Open the folder where templates are kept",
                              command=self.open_data_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        bar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="How it works", command=self.show_help)
        help_menu.add_command(label="About", command=self.show_about)
        bar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=bar)

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        main = ttk.Frame(self, padding=self.px(10))
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        paned = ttk.PanedWindow(main, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")
        left = ttk.Frame(paned, padding=(0, 0, self.px(8), 0))
        right = ttk.Frame(paned, padding=(self.px(8), 0, 0, 0))
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self._build_template_list(left)
        self._build_editor(right)
        self._build_create_panel(main)

    # -- left: template list ------------------------------------------------ #

    def _build_template_list(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text="My templates", style="Bold.TLabel").grid(row=0, column=0, sticky="w")
        holder = ttk.Frame(parent)
        holder.grid(row=1, column=0, sticky="nsew", pady=(self.px(4), self.px(6)))
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.template_list = ttk.Treeview(holder, show="tree", selectmode="browse",
                                          height=8)
        self.template_list.column("#0", width=self.px(200), minwidth=self.px(140))
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.template_list.yview)
        self.template_list.configure(yscrollcommand=scroll.set)
        self.template_list.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.template_list.bind("<<TreeviewSelect>>", self._on_list_select)

        row = ttk.Frame(parent)
        row.grid(row=2, column=0, sticky="we")
        for column, (text, command, tip) in enumerate([
                ("New", self.new_template, "Start a new, empty template  (Ctrl+N)"),
                ("Copy", self.duplicate_template, "Make a copy of this template"),
                ("Delete", self.delete_template, "Delete this template (folders already created are not touched)")]):
            button = ttk.Button(row, text=text, command=command, width=7)
            button.grid(row=0, column=column, padx=(0 if column == 0 else self.px(4), 0), sticky="we")
            row.columnconfigure(column, weight=1)
            Tooltip(button, tip)
            setattr(self, "btn_" + text.lower(), button)

    # -- right: template name + structure editor ----------------------------- #

    def _build_editor(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        head = ttk.Frame(parent)
        head.grid(row=0, column=0, sticky="we")
        head.columnconfigure(1, weight=1)

        ttk.Label(head, text="Template name").grid(row=0, column=0, sticky="w")
        self.tname_var = tk.StringVar()
        self.tname_entry = ttk.Entry(head, textvariable=self.tname_var)
        self.tname_entry.grid(row=0, column=1, sticky="we", padx=self.px(8))
        self.save_button = ttk.Button(head, text="Save template", command=self.save)
        self.save_button.grid(row=0, column=2, sticky="e")
        Tooltip(self.save_button, "Save your changes  (Ctrl+S)")

        ttk.Label(head, text="Top folder name").grid(row=1, column=0, sticky="w", pady=(self.px(6), 0))
        self.rname_var = tk.StringVar()
        self.rname_entry = ttk.Entry(head, textvariable=self.rname_var)
        self.rname_entry.grid(row=1, column=1, sticky="we", padx=self.px(8), pady=(self.px(6), 0))
        self.save_state_var = tk.StringVar()
        self.save_state = ttk.Label(head, textvariable=self.save_state_var, style="Hint.TLabel")
        self.save_state.grid(row=1, column=2, sticky="e", pady=(self.px(6), 0))
        self.rname_error_var = tk.StringVar()
        self.rname_error_label = ttk.Label(head, textvariable=self.rname_error_var,
                                           foreground=ERROR_FG, wraplength=self.px(520), justify="left")
        self.rname_error_label.grid(row=2, column=1, sticky="w", padx=self.px(8))
        self.rname_error_label.grid_remove()

        ttk.Label(parent, text="Folder structure", style="Bold.TLabel").grid(
            row=2, column=0, sticky="w", pady=(self.px(10), self.px(4)))
        self.editor = StructureEditor(parent, self.icons, self, scale=self.scale,
                                      on_change=self._mark_dirty,
                                      on_root_renamed=self._on_editor_root_renamed)
        self.editor.grid(row=3, column=0, sticky="nsew")

        self.tname_var.trace_add("write", lambda *_: self._on_template_name_typed())
        self.rname_var.trace_add("write", lambda *_: self._on_root_name_typed())

    # -- bottom: create panel ------------------------------------------------ #

    def _build_create_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.LabelFrame(parent, text="Create a new folder from this template",
                               padding=self.px(10))
        panel.grid(row=1, column=0, sticky="we", pady=(self.px(10), 0))
        panel.columnconfigure(1, weight=1)
        pad = self.px(8)

        ttk.Label(panel, text="Create it in").grid(row=0, column=0, sticky="w")
        self.dest_var = tk.StringVar()
        self.dest_box = ttk.Combobox(panel, textvariable=self.dest_var,
                                     values=self.store.settings.recent_destinations)
        self.dest_box.grid(row=0, column=1, sticky="we", padx=pad)
        browse = ttk.Button(panel, text="Browse…", command=self.browse)
        browse.grid(row=0, column=2, sticky="we")
        self.places_button = ttk.Menubutton(panel, text="Quick places ▾")
        self.places_menu = tk.Menu(self.places_button, tearoff=False,
                                   postcommand=self._fill_places_menu)
        self.places_button.configure(menu=self.places_menu)
        self.places_button.grid(row=0, column=3, sticky="we", padx=(self.px(6), 0))
        Tooltip(self.places_button, "Jump to OneDrive, Documents, Desktop or a recent location")

        ttk.Label(panel, text="Name the new folder").grid(row=1, column=0, sticky="w",
                                                          pady=(self.px(8), 0))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(panel, textvariable=self.name_var)
        self.name_entry.grid(row=1, column=1, sticky="we", padx=pad, pady=(self.px(8), 0))
        self.name_entry.bind("<Return>", lambda _e: self.create())

        self.info_var = tk.StringVar()
        self.info_label = ttk.Label(panel, textvariable=self.info_var, justify="left")
        self.info_label.grid(row=2, column=1, sticky="w", padx=pad, pady=(self.px(6), 0))
        self.name_entry.bind("<Configure>", lambda e: self.info_label.configure(
            wraplength=max(self.px(200), e.width)), add="+")

        self.open_after_var = tk.BooleanVar(value=self.store.settings.open_after_create)
        ttk.Checkbutton(panel, text="Open the new folder when it has been created",
                        variable=self.open_after_var).grid(
            row=3, column=1, sticky="w", padx=pad, pady=(self.px(6), 0))

        self.create_button = tk.Button(
            panel, text="Create folders", command=self.create, font=self.big_bold,
            background=CREATE_BG, foreground="white", activebackground=CREATE_BG_ACTIVE,
            activeforeground="white", relief="flat", borderwidth=0, cursor="hand2",
            padx=self.px(22), pady=self.px(8))
        self.create_button.grid(row=1, column=2, columnspan=2, rowspan=3, sticky="nswe",
                                padx=(self.px(6), 0), pady=(self.px(8), 0))

        self.result_var = tk.StringVar()
        self.result_label = ttk.Label(panel, textvariable=self.result_var, justify="left",
                                      font=self.bold)
        self.result_label.grid(row=4, column=1, columnspan=2, sticky="w", padx=pad, pady=(self.px(8), 0))
        panel.bind("<Configure>", lambda e: self.result_label.configure(
            wraplength=max(self.px(240), e.width - self.px(200))), add="+")
        self.open_button = ttk.Button(panel, text="Open folder", command=self.open_result)
        self.open_button.grid(row=4, column=3, sticky="e", pady=(self.px(8), 0))
        self.open_button.grid_remove()

        self.dest_var.trace_add("write", lambda *_: self._on_destination_typed())
        self.name_var.trace_add("write", lambda *_: self._on_name_typed())
        self.open_after_var.trace_add("write", lambda *_: self._remember_open_after())

    # ------------------------------------------------------------------ #
    # Template list and loading
    # ------------------------------------------------------------------ #

    def _fill_template_list(self, select_id: Optional[str] = None) -> None:
        listing = self.template_list
        self._guard = True
        try:
            listing.delete(*listing.get_children(""))
            for template in self.store.templates:
                listing.insert("", "end", iid=template.id, text=template.name,
                               image=self.icons.folder)
            if select_id and listing.exists(select_id):
                listing.selection_set(select_id)
                listing.see(select_id)
        finally:
            self._guard = False

    def _list_label(self, template: Template) -> str:
        return template.name + (" *" if self.dirty else "")

    def _refresh_list_label(self) -> None:
        if self.current is not None and self.template_list.exists(self.current.id):
            self.template_list.item(self.current.id, text=self._list_label(self.current))

    def _on_list_select(self, _event: object = None) -> None:
        if self._guard:
            return
        selection = self.template_list.selection()
        if not selection:
            return
        wanted = selection[0]
        if self.current is not None and wanted == self.current.id:
            return
        if not self._confirm_leave():
            self._guard = True
            try:
                if self.current is not None:
                    self.template_list.selection_set(self.current.id)
            finally:
                self._guard = False
            return
        self._load_template(self.store.get(wanted))

    def _confirm_leave(self) -> bool:
        """Deal with unsaved changes before something replaces the template on screen."""
        if not self.dirty:
            return True
        choice = self.ask_save_changes()
        if choice == "cancel":
            return False
        if choice == "save":
            return self.save()
        self.dirty = False
        return True

    def _load_template(self, stored: Optional[Template]) -> None:
        self.editor.cancel_edit()
        self.dirty = False
        self.result_var.set("")
        self.open_button.grid_remove()
        self.last_created = None
        if stored is None:
            self.current = None
            self._guard = True
            self.tname_var.set("")
            self.rname_var.set("")
            self.name_var.set("")
            self._guard = False
            self.editor.set_root(None)
            for widget in (self.tname_entry, self.rname_entry, self.name_entry, self.dest_box,
                           self.create_button, self.save_button):
                widget.configure(state="disabled")
            self.info_var.set("There are no templates yet. Click New (under My templates) to make one.")
            self.info_label.configure(foreground=HINT_FG)
            self._update_save_state()
            return
        for widget in (self.tname_entry, self.rname_entry, self.name_entry):
            widget.configure(state="normal")
        self.dest_box.configure(state="normal")
        self.create_button.configure(state="normal")
        self.current = stored.clone()
        self.store.settings.last_template_id = stored.id
        self._guard = True
        self.tname_var.set(self.current.name)
        self.rname_var.set(self.current.root.name)
        self.name_var.set(self.current.root.name)
        self.dest_var.set(self.store.settings.destination_for(stored.id))
        self._guard = False
        self.name_is_default = True
        self._set_root_error("")
        self.editor.set_root(self.current.root)
        self._fill_template_list(select_id=stored.id)
        self._update_save_state()
        self._update_preview()

    # ------------------------------------------------------------------ #
    # Editing state
    # ------------------------------------------------------------------ #

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_save_state()
        self._refresh_list_label()
        self._suppress_preview = False
        self._schedule_preview()

    def _update_save_state(self) -> None:
        if self.current is None:
            self.save_state_var.set("")
            self.save_button.configure(state="disabled")
            return
        self.save_button.configure(state="normal" if self.dirty else "disabled")
        self.save_state_var.set("Unsaved changes" if self.dirty else "All changes saved")
        self.save_state.configure(foreground=WARN_FG if self.dirty else HINT_FG)
        self.title(("* " if self.dirty else "") + APP_NAME)

    def _on_template_name_typed(self) -> None:
        if self._guard or self.current is None:
            return
        self.current.name = clean_name(self.tname_var.get())
        self._mark_dirty()

    def _on_root_name_typed(self) -> None:
        if self._guard or self.current is None:
            return
        text = clean_name(self.rname_var.get())
        problem = name_problem(text)
        self._set_root_error(problem or "")
        if problem:
            return
        self.editor.commit_edit()
        self.current.root.name = text
        self.editor.retitle_root()
        if self.name_is_default:
            self._guard = True
            self.name_var.set(text)
            self._guard = False
        self._mark_dirty()

    def _set_root_error(self, text: str) -> None:
        self.rname_error_var.set(text)
        if text:
            self.rname_error_label.grid()
        else:
            self.rname_error_label.grid_remove()

    def _on_editor_root_renamed(self, name: str) -> None:
        self._guard = True
        self.rname_var.set(name)
        self._set_root_error("")
        if self.name_is_default:
            self.name_var.set(name)
        self._guard = False

    def _on_name_typed(self) -> None:
        if not self._guard:
            self.name_is_default = False
        self._inputs_changed()

    def _on_destination_typed(self) -> None:
        self._inputs_changed()

    def _inputs_changed(self) -> None:
        """Something that decides what Create would do was edited: drop the last result."""
        if self.last_created is not None and not self._guard:
            self.result_var.set("")
            self.open_button.grid_remove()
            self.last_created = None
        self._suppress_preview = False
        self._schedule_preview()

    def _remember_open_after(self) -> None:
        self.store.settings.open_after_create = bool(self.open_after_var.get())
        self._save_settings_quietly()

    def _save_settings_quietly(self) -> None:
        try:
            self.store.save_settings()
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Template commands
    # ------------------------------------------------------------------ #

    def save(self) -> bool:
        if self.current is None:
            return True
        self.editor.commit_edit()
        if not clean_name(self.tname_var.get()):
            self.error("Can't save", "The template needs a name.")
            return False
        problem = name_problem(clean_name(self.rname_var.get()))
        if problem:
            self.error("Can't save", "The top folder name isn't valid:\n%s" % problem)
            return False
        self.current.name = clean_name(self.tname_var.get())
        try:
            self.store.update(self.current)
        except TemplateError as exc:
            self.error("Can't save", str(exc))
            return False
        except (OSError, StorageError) as exc:
            self.error("Can't save", "The template couldn't be written to disk:\n%s" % exc)
            return False
        self.dirty = False
        self._update_save_state()
        self._refresh_list_label()
        self._save_settings_quietly()
        return True

    def new_template(self) -> None:
        if not self._confirm_leave():
            return
        root = Folder("New folder")
        template = Template(self.store.unique_template_name("New template"), root)
        try:
            stored = self.store.add(template)
        except (OSError, StorageError, TemplateError) as exc:
            self.error("Can't create the template", str(exc))
            return
        self._load_template(stored)
        self.tname_entry.focus_set()
        self.tname_entry.selection_range(0, "end")

    def duplicate_template(self) -> None:
        if self.current is None or not self._confirm_leave():
            return
        source = self.store.get(self.current.id)
        if source is None:
            return
        copy = source.clone(new_id=True)
        copy.name = self.store.unique_template_name("Copy of " + source.name)
        try:
            stored = self.store.add(copy, after_id=source.id)
        except (OSError, StorageError, TemplateError) as exc:
            self.error("Can't copy the template", str(exc))
            return
        self._load_template(stored)

    def delete_template(self) -> None:
        if self.current is None:
            return
        name = self.current.name
        if not self.confirm(
                "Delete template",
                'Delete the template "%s"?\n\nThis can\'t be undone. Folders already created from '
                "it are not affected." % name):
            return
        index = next((i for i, t in enumerate(self.store.templates) if t.id == self.current.id), 0)
        try:
            self.store.delete(self.current.id)
        except (OSError, StorageError) as exc:
            self.error("Can't delete the template", str(exc))
            return
        self.dirty = False
        self._fill_template_list()
        remaining = self.store.templates
        self._load_template(remaining[min(index, len(remaining) - 1)] if remaining else None)

    def import_from_folder(self) -> None:
        if not self._confirm_leave():
            return
        path = self.pick_directory("Choose a folder to turn into a template",
                                   self._browse_start())
        if not path:
            return
        try:
            root, report = model.folder_from_disk(path)
        except TemplateError as exc:
            self.error("Can't import", str(exc))
            return
        template = Template(self.store.unique_template_name(root.name), root)
        try:
            stored = self.store.add(template)
        except (OSError, StorageError, TemplateError) as exc:
            self.error("Can't import", str(exc))
            return
        self._load_template(stored)
        notes = ["Imported %d folder%s from \"%s\"." % (
            report.folders, "" if report.folders == 1 else "s", root.name)]
        if report.files_ignored:
            notes.append("Ignored %d file%s (only folders are imported)." % (
                report.files_ignored, "" if report.files_ignored == 1 else "s"))
        if report.skipped:
            notes.append("Skipped (hidden, system, or names Windows doesn't allow): %s." %
                         ", ".join(report.skipped[:6]) + ("…" if len(report.skipped) > 6 else ""))
        if report.truncated:
            notes.append("The folder was very large, so only the first part was imported.")
        self.info("Template created", "\n".join(notes))

    def import_template_file(self) -> None:
        if not self._confirm_leave():
            return
        path = self.pick_open_file("Choose a template file to import")
        if not path:
            return
        try:
            found = storage.read_template_file(path)
            added = self.store.import_templates(found)
        except (StorageError, OSError, TemplateError) as exc:
            self.error("Can't import", str(exc))
            return
        self._load_template(added[-1])
        self.info("Imported", "Imported %d template%s." % (len(added), "" if len(added) == 1 else "s"))

    def export_template(self) -> None:
        if self.current is None:
            return
        if self.dirty and not self.save():
            return
        stored = self.store.get(self.current.id)
        if stored is None:
            return
        safe = re.sub(r'[<>:"/\\|?*]', "-", stored.name).strip() or "template"
        path = self.pick_save_file("Export this template", safe + ".json")
        if not path:
            return
        try:
            storage.export_template(stored, path)
        except OSError as exc:
            self.error("Can't export", str(exc))
            return
        self.info("Exported", "The template was saved to:\n%s\n\nOn another computer, use File > "
                  "Import template file to add it." % path)

    def open_data_folder(self) -> None:
        try:
            os.makedirs(self.store.directory, exist_ok=True)
            osutil.open_in_file_manager(self.store.directory)
        except OSError as exc:
            self.error("Can't open the folder", str(exc))

    def show_help(self) -> None:
        text = HELP_TEXT + "\n# Where your templates are kept\n" + self.store.directory
        TextDialog(self, "How Folder Template Maker works", text).show()

    def show_about(self) -> None:
        TextDialog(self, "About", "%s  version %s\n\nYour templates and settings are kept in:\n%s"
                   % (APP_NAME, __version__, self.store.directory), width=60, height=7).show()

    # ------------------------------------------------------------------ #
    # Choosing the destination
    # ------------------------------------------------------------------ #

    def _browse_start(self) -> str:
        current = osutil.normalize_path_text(self.dest_var.get()) if hasattr(self, "dest_var") else ""
        candidates: List[str] = [current] + list(self.store.settings.recent_destinations)
        candidates += [path for _label, path in osutil.quick_locations()]
        candidates.append(os.path.expanduser("~"))
        for candidate in candidates:
            if candidate and os.path.isdir(candidate):
                return candidate
        return ""

    def browse(self) -> None:
        path = self.pick_directory("Choose where the new folder should be created",
                                   self._browse_start())
        if path:
            self.dest_var.set(path)

    def _fill_places_menu(self) -> None:
        menu = self.places_menu
        menu.delete(0, "end")
        places = osutil.quick_locations()
        for label, path in places:
            menu.add_command(label="%s    (%s)" % (label, path),
                             command=lambda p=path: self.dest_var.set(p))
        recents = [p for p in self.store.settings.recent_destinations if os.path.isdir(p)]
        if places and recents:
            menu.add_separator()
        for path in recents:
            menu.add_command(label=path, command=lambda p=path: self.dest_var.set(p))
        if not places and not recents:
            menu.add_command(label="(nothing to show yet)", state="disabled")

    # ------------------------------------------------------------------ #
    # The live "what will happen" line
    # ------------------------------------------------------------------ #

    def _schedule_preview(self) -> None:
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
        self._preview_job = self.after(250, self._run_scheduled_preview)

    def _run_scheduled_preview(self) -> None:
        self._preview_job = None
        self._update_preview()

    def _update_preview(self) -> None:
        if self.current is None:
            return
        if self._suppress_preview:             # right after creating: the result line says it all
            self.info_var.set("")
            return
        info = builder.preview(self.current, self.dest_var.get(), self.name_var.get())
        sub, docs = builder.template_stats(self.current)
        counts = "%d sub folder%s" % (sub, "" if sub == 1 else "s")
        if docs:
            counts += ", %d document%s" % (docs, "" if docs == 1 else "s")
        if info.ok:
            if info.top_state == "folder":
                self.info_var.set('A folder with that name already exists there. Only anything missing '
                                  'will be added (%s in the template).' % counts)
                self.info_label.configure(foreground=WARN_FG)
            else:
                self.info_var.set("Will create: %s   (%s)" % (info.top_path, counts))
                self.info_label.configure(foreground=HINT_FG)
        elif info.destination_problem and not self.dest_var.get().strip():
            self.info_var.set("Choose where the new folder should be created.")
            self.info_label.configure(foreground=HINT_FG)
        else:
            self.info_var.set(info.problems[0])
            self.info_label.configure(foreground=ERROR_FG)

    # ------------------------------------------------------------------ #
    # Creating
    # ------------------------------------------------------------------ #

    def create(self) -> None:
        if self.current is None:
            return
        self.editor.commit_edit()
        destination = osutil.normalize_path_text(self.dest_var.get())
        name = clean_name(self.name_var.get())
        info = builder.preview(self.current, destination, name)
        if not info.ok:
            self.result_var.set("")
            self.open_button.grid_remove()
            self.error("The folder can't be created yet", "\n\n".join(info.problems))
            return
        if info.top_state == "folder" and not self.confirm(
                "That folder already exists",
                'A folder named "%s" already exists in:\n%s\n\nAdd any missing folders and documents '
                "to it?\n\n(Nothing that is already there will be changed or deleted.)"
                % (name, destination)):
            return
        try:
            result = builder.create_from_template(self.current, destination, name,
                                                  allow_existing=True)
        except builder.PlanError as exc:
            self.error("The folder can't be created yet", "\n\n".join(exc.problems))
            return
        except OSError as exc:
            self.error("Something went wrong", builder.describe_os_error(exc))
            return
        self._after_create(result, destination)

    def _after_create(self, result: builder.CreationResult, destination: str) -> None:
        assert self.current is not None
        if self.dest_var.get() != destination:          # show the tidied-up path (no quotes etc.)
            self._guard = True
            self.dest_var.set(destination)
            self._guard = False
        self.store.settings.remember_destination(self.current.id, destination)
        self.dest_box.configure(values=self.store.settings.recent_destinations)
        self._save_settings_quietly()
        self.last_created = result.top_path
        if result.ok:
            self.result_var.set("✓ " + result.summary())
            self.result_label.configure(foreground=OK_FG)
        else:
            self.result_var.set("Finished with problems. " + result.summary())
            self.result_label.configure(foreground=ERROR_FG)
        self.open_button.grid()
        self._suppress_preview = True
        self.info_var.set("")
        if result.errors:
            lines = ["%s\n    %s" % (item, reason) for item, reason in result.errors[:12]]
            more = "\n…and %d more." % (len(result.errors) - 12) if len(result.errors) > 12 else ""
            self.error("Some items couldn't be created",
                       result.summary() + "\n\nThese weren't created:\n\n" + "\n".join(lines) + more)
        elif self.open_after_var.get():
            self.open_result()

    def open_result(self) -> None:
        if not self.last_created:
            return
        try:
            osutil.open_in_file_manager(self.last_created)
        except OSError as exc:
            self.error("Can't open the folder", str(exc))

    # ------------------------------------------------------------------ #
    # Window housekeeping
    # ------------------------------------------------------------------ #

    def _restore_geometry(self) -> None:
        """Size and place the window; the minimum size is whatever the layout really needs."""
        self.update_idletasks()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        min_w = min(max(self.winfo_reqwidth(), self.px(820)), screen_w)
        min_h = min(max(self.winfo_reqheight(), self.px(560)), screen_h)
        width, height = self.px(1020), self.px(720)
        x = y = None
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.store.settings.geometry or "")
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            x, y = int(match.group(3)), int(match.group(4))
        width, height = min(max(width, min_w), screen_w), min(max(height, min_h), screen_h)
        if x is None or y is None or x < -50 or y < -10 or x > screen_w - 120 or y > screen_h - 120:
            x, y = (screen_w - width) // 2, max((screen_h - height) // 3, 0)
        self.geometry("%dx%d+%d+%d" % (width, height, x, y))
        self.minsize(min_w, min_h)

    def destroy(self) -> None:
        if self._preview_job is not None:                # don't leave timers firing at a dead window
            try:
                self.after_cancel(self._preview_job)
            except tk.TclError:
                pass
            self._preview_job = None
        super().destroy()

    def on_close(self) -> None:
        if not self._confirm_leave():
            return
        try:
            self.store.settings.geometry = self.geometry()
            self.store.save_settings()
        except (OSError, tk.TclError):
            pass
        self.destroy()

    def _report_exception(self, exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log = os.path.join(self.store.directory, "error.log")
        try:
            os.makedirs(self.store.directory, exist_ok=True)
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("%s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except OSError:
            log = "(couldn't write a log file)"
        try:
            messagebox.showerror(
                APP_NAME, "Something unexpected went wrong:\n\n%s\n\nDetails were saved to:\n%s"
                % (exc, log), parent=self)
        except tk.TclError:
            pass
