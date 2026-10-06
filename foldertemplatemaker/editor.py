"""The folder-structure editor: a tree with buttons, inline renaming and drag & drop."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Set, Tuple

from . import model
from .dialogs import DocumentDialog, OutlineDialog
from .icons import Icons
from .model import DocSpec, Folder, Node, TemplateError
from .names import PlaceholderContext, clean_name, resolve, unique_name
from .widgets import Tooltip

NEW_IID = "__new__"
ERROR_FG = "#b00020"
HINT_FG = "#555555"
DROP_BG = "#cfe3ff"
DEFAULT_TIP = "Tip: select a folder and click Add subfolder.  Double-click to rename.  Drag to rearrange."


def _iid(node: Node) -> str:
    return ("f%d" if isinstance(node, Folder) else "d%d") % node.uid


def _truthy(value: object) -> bool:
    return str(value).lower() in ("1", "true", "yes")


class _Edit:
    """An inline name edit that is in progress."""

    def __init__(self, entry: tk.Entry, kind: str, node: Optional[Folder] = None,
                 parent: Optional[Folder] = None, before: Optional[Folder] = None,
                 chain: bool = False):
        self.entry = entry
        self.kind = kind              # "new" or "rename"
        self.node = node
        self.parent = parent
        self.before = before
        self.chain = chain
        self.closing = False


class _Drag:
    def __init__(self, node: Node, x: int, y: int):
        self.node = node
        self.start = (x, y)
        self.active = False
        self.target: Optional[Tuple[Folder, Optional[Node]]] = None
        self.highlight: Optional[str] = None


class StructureEditor(ttk.Frame):
    """Edits one template's folder tree.

    ``host`` supplies a few services: ``confirm(title, message) -> bool``,
    ``template_name() -> str`` and ``sample_title() -> str``.
    """

    def __init__(self, master: tk.Misc, icons: Icons, host, *, scale: float = 1.0,
                 on_change: Optional[Callable[[], None]] = None,
                 on_root_renamed: Optional[Callable[[str], None]] = None):
        super().__init__(master)
        self.icons = icons
        self.host = host
        self.scale = scale
        self.on_change = on_change or (lambda: None)
        self.on_root_renamed = on_root_renamed or (lambda name: None)
        self.root_folder: Optional[Folder] = None
        self._open: Set[int] = set()
        self._nodes: Dict[str, Node] = {}
        self._editing: Optional[_Edit] = None
        self._drag: Optional[_Drag] = None
        self._message_job: Optional[str] = None
        self._line: Optional[tk.Frame] = None
        self._build()

    # ------------------------------------------------------------------ #
    # Building the widgets
    # ------------------------------------------------------------------ #

    def px(self, n: int) -> int:
        return max(1, int(round(n * self.scale)))

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        holder = ttk.Frame(self)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, show="tree", selectmode="browse", height=7)
        self.tree.tag_configure("doc", foreground="#3b4a63")
        self.tree.tag_configure("drop", background=DROP_BG)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        side = ttk.Frame(self)
        side.grid(row=0, column=1, sticky="n", padx=(self.px(10), 0))
        self.buttons: Dict[str, ttk.Button] = {}

        def add_button(parent: tk.Misc, key: str, text: str, command: Callable[[], None],
                       tip: str, width: int = 16) -> ttk.Button:
            button = ttk.Button(parent, text=text, command=command, width=width)
            Tooltip(button, tip)
            self.buttons[key] = button
            return button

        for key, text, command, tip in [
                ("add", "Add subfolder", self.add_subfolder,
                 "Add a folder inside the selected folder  (Insert)"),
                ("several", "Add several…", self.add_several,
                 "Type or paste a list of folders in one go"),
                ("doc", "Add document…", self.add_document,
                 "Add a text document that is created inside the selected folder")]:
            add_button(side, key, text, command, tip).pack(fill="x", pady=self.px(2))
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=self.px(6))
        for key, text, command, tip in [
                ("rename", "Rename", self.rename_selected,
                 "Rename the selected folder, or edit the selected document  (F2 or double-click)"),
                ("delete", "Delete", self.delete_selected,
                 "Remove the selected item from this template  (Delete key)")]:
            add_button(side, key, text, command, tip).pack(fill="x", pady=self.px(2))
        ttk.Separator(side, orient="horizontal").pack(fill="x", pady=self.px(6))
        ttk.Label(side, text="Rearrange", foreground=HINT_FG).pack(anchor="w")
        moves = ttk.Frame(side)
        moves.pack(fill="x", pady=(self.px(2), 0))
        moves.columnconfigure((0, 1), weight=1, uniform="moves")
        for key, text, command, tip, row, column in [
                ("up", "↑ Up", self.move_up, "Move it up in the list  (Alt+Up)", 0, 0),
                ("down", "↓ Down", self.move_down, "Move it down in the list  (Alt+Down)", 0, 1),
                ("out", "← Out", self.outdent,
                 "Move it out of its folder, up one level  (Alt+Left)", 1, 0),
                ("in", "→ In", self.indent,
                 "Make it a subfolder of the folder above it  (Alt+Right)", 1, 1)]:
            add_button(moves, key, text, command, tip, width=7).grid(
                row=row, column=column, sticky="we", padx=self.px(1), pady=self.px(2))

        self.message_var = tk.StringVar(value=DEFAULT_TIP)
        self.message = ttk.Label(self, textvariable=self.message_var, foreground=HINT_FG,
                                 wraplength=self.px(560), justify="left")
        self.message.grid(row=1, column=0, columnspan=2, sticky="we", pady=(self.px(6), 0))
        self.bind("<Configure>", self._on_resize)

        tree = self.tree
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Double-1>", self._on_double_click)
        tree.bind("<F2>", lambda _e: self.rename_selected())
        tree.bind("<Delete>", lambda _e: self.delete_selected())
        tree.bind("<Insert>", lambda _e: self.add_subfolder())
        tree.bind("<Alt-Up>", lambda _e: self.move_up())
        tree.bind("<Alt-Down>", lambda _e: self.move_down())
        tree.bind("<Alt-Left>", lambda _e: self.outdent())
        tree.bind("<Alt-Right>", lambda _e: self.indent())
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<ButtonPress-1>", self._drag_press, add="+")
        tree.bind("<B1-Motion>", self._drag_motion, add="+")
        tree.bind("<ButtonRelease-1>", self._drag_release, add="+")
        self._update_buttons()

    def destroy(self) -> None:
        if self._message_job is not None:
            try:
                self.after_cancel(self._message_job)
            except tk.TclError:
                pass
            self._message_job = None
        super().destroy()

    def _on_resize(self, event: tk.Event) -> None:
        self.message.configure(wraplength=max(self.px(200), event.width - self.px(12)))

    # ------------------------------------------------------------------ #
    # Loading and drawing
    # ------------------------------------------------------------------ #

    def set_root(self, root: Optional[Folder]) -> None:
        """Show a (new) folder tree.  The editor edits this object directly."""
        self._cancel_edit()
        self.root_folder = root
        self._open = {f.uid for f in model.iter_folders(root)} if root else set()
        self._nodes.clear()
        self.tree.delete(*self.tree.get_children(""))
        self.refresh(select=root)
        self.say(DEFAULT_TIP)

    def refresh(self, select: Optional[Node] = None) -> None:
        self._cancel_edit()
        tree = self.tree
        keep = select if select is not None else self.selected_node()
        for iid, node in self._nodes.items():
            if isinstance(node, Folder) and tree.exists(iid):
                if _truthy(tree.item(iid, "open")):
                    self._open.add(node.uid)
                else:
                    self._open.discard(node.uid)
        tree.delete(*tree.get_children(""))
        self._nodes.clear()
        if self.root_folder is not None:
            self._insert_folder("", self.root_folder, is_root=True)
            target = keep if keep is not None and _iid(keep) in self._nodes else self.root_folder
            self.select(target)
        self._update_buttons()

    def _insert_folder(self, parent_iid: str, folder: Folder, is_root: bool = False) -> None:
        iid = _iid(folder)
        self.tree.insert(parent_iid, "end", iid=iid, text=folder.name, image=self.icons.folder,
                         open=folder.uid in self._open, tags=("folder",))
        self._nodes[iid] = folder
        for child in folder.folders:
            self._insert_folder(iid, child)
        for doc in folder.docs:
            doc_iid = _iid(doc)
            self.tree.insert(iid, "end", iid=doc_iid, text=doc.file_pattern,
                             image=self.icons.document, tags=("doc",))
            self._nodes[doc_iid] = doc

    def retitle_root(self) -> None:
        """The root folder was renamed elsewhere (the 'top folder name' box)."""
        if self.root_folder is not None and _iid(self.root_folder) in self._nodes:
            self.tree.item(_iid(self.root_folder), text=self.root_folder.name)

    def say(self, text: str, error: bool = False) -> None:
        try:
            self.message_var.set(text)
            self.message.configure(foreground=ERROR_FG if error else HINT_FG)
            if self._message_job is not None:
                self.after_cancel(self._message_job)
                self._message_job = None
            if error:
                self._message_job = self.after(9000, lambda: self.say(DEFAULT_TIP))
        except tk.TclError:
            self._message_job = None          # the window is already gone

    # ------------------------------------------------------------------ #
    # Selection
    # ------------------------------------------------------------------ #

    def selected_node(self) -> Optional[Node]:
        selection = self.tree.selection()
        return self._nodes.get(selection[0]) if selection else None

    def select(self, node: Optional[Node]) -> None:
        if node is None or _iid(node) not in self._nodes:
            return
        iid = _iid(node)
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def _on_select(self, _event: object = None) -> None:
        self._update_buttons()

    def _target_folder(self) -> Optional[Folder]:
        """The folder that "add" actions apply to: the selected folder, or a document's folder."""
        node = self.selected_node()
        if node is None:
            return self.root_folder
        if isinstance(node, Folder):
            return node
        return model.find_parent(self.root_folder, node) if self.root_folder else None

    def _siblings_of(self, node: Node) -> Tuple[Optional[Folder], List[Node]]:
        parent = model.find_parent(self.root_folder, node) if self.root_folder else None
        if parent is None:
            return None, []
        return parent, (parent.folders if isinstance(node, Folder) else parent.docs)  # type: ignore[return-value]

    def _can(self, action: str, node: Optional[Node]) -> bool:
        if self.root_folder is None:
            return False
        if action in ("add", "several", "doc"):
            return True
        if node is None:
            return False
        if action == "rename":
            return True
        parent, items = self._siblings_of(node)
        if action == "delete":
            return node is not self.root_folder
        if parent is None:
            return False
        index = next((i for i, item in enumerate(items) if item is node), -1)
        if action == "up":
            return index > 0
        if action == "down":
            return 0 <= index < len(items) - 1
        if action == "in":
            return isinstance(node, Folder) and index > 0
        if action == "out":
            return model.find_parent(self.root_folder, parent) is not None
        return False

    def _update_buttons(self) -> None:
        node = self.selected_node()
        for key, button in self.buttons.items():
            button.state(["!disabled"] if self._can(key, node) else ["disabled"])

    # ------------------------------------------------------------------ #
    # Inline editing
    # ------------------------------------------------------------------ #

    def _text_box(self, iid: str) -> Optional[Tuple[int, int, int, int]]:
        """Where an item's text is drawn: (x, y, width, height), found by looking at the widget."""
        tree = self.tree
        tree.update_idletasks()
        box = tree.bbox(iid, "#0")
        if not box:
            return None
        bx, by, bw, bh = box
        middle = by + bh // 2
        for x in range(bx, bx + bw):
            try:
                if tree.identify_element(x, middle) == "text":
                    return x, by, bx + bw - x, bh
            except tk.TclError:
                break
        offset = self.px(40)
        return bx + offset, by, max(bw - offset, self.px(80)), bh

    def _start_entry(self, iid: str, text: str, kind: str, node: Optional[Folder] = None,
                     parent: Optional[Folder] = None, before: Optional[Folder] = None,
                     chain: bool = False) -> None:
        box = self._text_box(iid)
        if box is None:
            return
        x, y, w, h = box
        entry = tk.Entry(self.tree, relief="solid", borderwidth=1, highlightthickness=0,
                         font="TkDefaultFont")
        entry.insert(0, text)
        room = self.tree.winfo_width() - x - self.px(6)
        entry.place(x=x - 2, y=y, width=max(self.px(100), min(max(w, self.px(220)), room)), height=h)
        entry.focus_set()
        entry.selection_range(0, "end")
        entry.icursor("end")
        edit = _Edit(entry, kind, node, parent, before, chain)
        self._editing = edit
        entry.bind("<Return>", lambda _e: self._commit_edit(via_return=True))
        entry.bind("<KP_Enter>", lambda _e: self._commit_edit(via_return=True))
        entry.bind("<Escape>", lambda _e: self._abort_edit())
        entry.bind("<FocusOut>", lambda _e: self._commit_edit(via_return=False))
        entry.bind("<Key>", lambda _e: entry.configure(foreground="#000000"), add="+")

    def _end_edit(self) -> None:
        edit = self._editing
        if edit is None:
            return
        edit.closing = True
        self._editing = None
        try:
            edit.entry.destroy()
        except tk.TclError:
            pass
        if self.tree.exists(NEW_IID):
            self.tree.delete(NEW_IID)

    def _cancel_edit(self) -> None:
        if self._editing is not None:
            self._end_edit()

    def cancel_edit(self) -> None:
        """Throw away a name that is still being typed."""
        self._cancel_edit()

    def _abort_edit(self) -> str:
        self._end_edit()
        self.tree.focus_set()
        return "break"

    def commit_edit(self) -> None:
        """Apply a name that is still being typed (called before saving)."""
        if self._editing is not None:
            self._commit_edit(via_return=False)

    def _edit_error(self, edit: _Edit, message: str, via_return: bool) -> None:
        self.say(message, error=True)
        if via_return:                       # stay open so the name can be corrected
            edit.entry.configure(foreground=ERROR_FG)
            edit.entry.focus_set()
        else:
            self._end_edit()

    def _commit_edit(self, via_return: bool) -> Optional[str]:
        edit = self._editing
        if edit is None or edit.closing:
            return "break"
        text = clean_name(edit.entry.get())
        root = self.root_folder
        if root is None:
            self._end_edit()
            return "break"

        if edit.kind == "new":
            parent = edit.parent
            assert parent is not None
            if not text:                      # nothing typed: that's the end of adding folders
                self._end_edit()
                self.tree.focus_set()
                return "break"
            try:
                folder = model.add_folder(parent, text, before=edit.before)
            except TemplateError as exc:
                self._edit_error(edit, str(exc), via_return)
                return "break"
            chain, before = edit.chain, edit.before
            self._end_edit()
            self._open.add(parent.uid)
            self._changed()
            self.refresh(select=folder)
            self.say('Added "%s".' % folder.name)
            if via_return and chain:
                self._begin_new_folder(parent, before=before, chain=True, initial="")
            else:
                self.tree.focus_set()
            return "break"

        folder = edit.node
        assert folder is not None
        if text == folder.name:
            self._end_edit()
            self.tree.focus_set()
            return "break"
        try:
            model.rename_folder(root, folder, text)
        except TemplateError as exc:
            self._edit_error(edit, str(exc), via_return)
            return "break"
        self._end_edit()
        self._changed()
        self.refresh(select=folder)
        if folder is root:
            self.on_root_renamed(folder.name)
        self.tree.focus_set()
        return "break"

    def _begin_new_folder(self, parent: Folder, before: Optional[Folder], chain: bool,
                          initial: Optional[str] = None) -> None:
        self._cancel_edit()
        if initial is None:
            initial = unique_name("New folder", [f.name for f in parent.folders])
        self._open.add(parent.uid)
        parent_iid = _iid(parent)
        self.tree.item(parent_iid, open=True)
        if before is not None and before in parent.folders:
            index = next(i for i, f in enumerate(parent.folders) if f is before)
        else:
            index = len(parent.folders)
        self.tree.insert(parent_iid, index, iid=NEW_IID, text="", image=self.icons.folder)
        self.tree.selection_set(NEW_IID)
        self.tree.see(NEW_IID)
        self._start_entry(NEW_IID, initial, "new", parent=parent, before=before, chain=chain)

    # ------------------------------------------------------------------ #
    # Actions (the buttons, keys and menu items all come through here)
    # ------------------------------------------------------------------ #

    def _changed(self) -> None:
        self.on_change()

    def add_subfolder(self) -> None:
        parent = self._target_folder()
        if parent is not None:
            self._begin_new_folder(parent, before=None, chain=True)

    def add_sibling(self) -> None:
        node = self.selected_node()
        if not isinstance(node, Folder) or node is self.root_folder:
            return self.add_subfolder()
        parent, items = self._siblings_of(node)
        if parent is None:
            return
        index = next(i for i, f in enumerate(items) if f is node)
        before = items[index + 1] if index + 1 < len(items) else None
        self._begin_new_folder(parent, before=before, chain=True)  # type: ignore[arg-type]

    def rename_selected(self) -> None:
        node = self.selected_node()
        if isinstance(node, Folder):
            self._cancel_edit()
            self.tree.see(_iid(node))
            self._start_entry(_iid(node), node.name, "rename", node=node)
        elif isinstance(node, DocSpec):
            self.edit_document(node)

    def delete_selected(self) -> None:
        node = self.selected_node()
        root = self.root_folder
        if node is None or root is None:
            return
        if node is root:
            self.say("The top folder can't be deleted - rename it instead.", error=True)
            return
        if isinstance(node, Folder) and (node.folders or node.docs):
            if not self.host.confirm(
                    "Delete folder",
                    'Remove "%s" and everything inside it from this template?\n\n'
                    "(Folders that were already created on your computer are not affected.)"
                    % node.name):
                return
        parent, items = self._siblings_of(node)
        neighbour: Optional[Node] = parent
        index = next((i for i, item in enumerate(items) if item is node), -1)
        if index > 0:
            neighbour = items[index - 1]
        elif index == 0 and len(items) > 1:
            neighbour = items[1]
        try:
            model.remove_node(root, node)
        except TemplateError as exc:
            self.say(str(exc), error=True)
            return
        self._changed()
        self.refresh(select=neighbour)
        self.say("Removed.")

    def _move(self, operation: Callable[[Folder, Node], bool]) -> None:
        node = self.selected_node()
        root = self.root_folder
        if node is None or root is None:
            return
        try:
            moved = operation(root, node)
        except TemplateError as exc:
            self.say(str(exc), error=True)
            return
        if moved:
            parent = model.find_parent(root, node)
            if parent is not None:
                self._open.add(parent.uid)
            self._changed()
            self.refresh(select=node)

    def move_up(self) -> None:
        self._move(model.move_up)

    def move_down(self) -> None:
        self._move(model.move_down)

    def indent(self) -> None:
        self._move(model.indent)

    def outdent(self) -> None:
        self._move(model.outdent)

    # -- dialogs ----------------------------------------------------------- #

    def _context_for(self, folder: Folder) -> PlaceholderContext:
        title = self.host.sample_title()
        on_disk = title if folder is self.root_folder else folder.name
        return PlaceholderContext(title, on_disk, self.host.template_name(), date.today())

    def add_several(self) -> None:
        parent = self._target_folder()
        if parent is None:
            return

        def apply(text: str) -> Optional[str]:
            folders, problems = model.parse_outline(text)
            if problems:
                return "\n".join(problems[:6]) + ("\n…" if len(problems) > 6 else "")
            if not folders:
                return "Type at least one folder name."
            try:
                model.add_outline(parent, folders)
            except TemplateError as exc:
                return str(exc)
            return None

        dialog = OutlineDialog(self.winfo_toplevel(), parent_name=parent.name, apply=apply)
        if dialog.show():
            self._open.add(parent.uid)
            self._changed()
            self.refresh(select=parent)
            self.say("Folders added.")

    def add_document(self) -> None:
        folder = self._target_folder()
        if folder is None:
            return
        ctx = self._context_for(folder)

        def preview(name: str, ext: str) -> str:
            return resolve(name, ctx, for_filename=True).strip() + ext

        created: List[DocSpec] = []

        def apply(name: str, ext: str, content: str) -> Optional[str]:
            try:
                created.append(model.add_doc(
                    folder, DocSpec(name, ext, model.normalize_newlines(content))))
            except TemplateError as exc:
                return str(exc)
            return None

        dialog = DocumentDialog(
            self.winfo_toplevel(), title="Add a document", folder_name=ctx.folder,
            name="{title} raw data", ext=".txt",
            content="Raw data - {title}\nCreated {date_long}\n\n",
            preview=preview, apply=apply, ok_text="Add document")
        if dialog.show():
            self._open.add(folder.uid)
            self._changed()
            self.refresh(select=created[-1])
            self.say("Document added.  It is created fresh each time you use this template.")

    def edit_document(self, doc: Optional[DocSpec] = None) -> None:
        doc = doc or self.selected_node()  # type: ignore[assignment]
        if not isinstance(doc, DocSpec) or self.root_folder is None:
            return
        folder = model.find_parent(self.root_folder, doc)
        if folder is None:
            return
        ctx = self._context_for(folder)

        def preview(name: str, ext: str) -> str:
            return resolve(name, ctx, for_filename=True).strip() + ext

        def apply(name: str, ext: str, content: str) -> Optional[str]:
            try:
                model.update_doc(folder, doc, name, ext, content)
            except TemplateError as exc:
                return str(exc)
            return None

        dialog = DocumentDialog(
            self.winfo_toplevel(), title="Edit document", folder_name=ctx.folder, name=doc.name,
            ext=doc.ext, content=doc.content, preview=preview, apply=apply)
        if dialog.show():
            self._changed()
            self.refresh(select=doc)

    # -- mouse ------------------------------------------------------------- #

    def _on_double_click(self, event: tk.Event) -> Optional[str]:
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self._nodes:
            return None
        try:
            if self.tree.identify_element(event.x, event.y) == "indicator":
                return None                      # let the little arrow expand/collapse as usual
        except tk.TclError:
            pass
        self.tree.selection_set(iid)
        self.rename_selected()
        return "break"

    def _on_right_click(self, event: tk.Event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid in self._nodes:
            self.tree.selection_set(iid)
        node = self.selected_node()
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Add subfolder", command=self.add_subfolder)
        if isinstance(node, Folder) and node is not self.root_folder:
            menu.add_command(label="Add folder after this one", command=self.add_sibling)
        menu.add_command(label="Add several…", command=self.add_several)
        menu.add_command(label="Add document…", command=self.add_document)
        menu.add_separator()
        menu.add_command(label="Rename" if isinstance(node, Folder) else "Edit document…",
                         command=self.rename_selected, state=self._state("rename", node))
        menu.add_command(label="Delete", command=self.delete_selected, state=self._state("delete", node))
        menu.add_separator()
        for key, label, command in (("up", "Move up", self.move_up), ("down", "Move down", self.move_down),
                                    ("in", "Move in", self.indent), ("out", "Move out", self.outdent)):
            menu.add_command(label=label, command=command, state=self._state(key, node))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _state(self, action: str, node: Optional[Node]) -> str:
        return "normal" if self._can(action, node) else "disabled"

    # -- drag and drop ------------------------------------------------------ #

    def _drag_press(self, event: tk.Event) -> None:
        self._drag = None
        if self._editing is not None:
            return
        iid = self.tree.identify_row(event.y)
        node = self._nodes.get(iid)
        if node is None or node is self.root_folder:
            return
        try:
            if self.tree.identify_element(event.x, event.y) == "indicator":
                return
        except tk.TclError:
            pass
        self._drag = _Drag(node, event.x, event.y)

    def _drag_motion(self, event: tk.Event) -> None:
        drag = self._drag
        if drag is None:
            return
        if not drag.active:
            if abs(event.x - drag.start[0]) + abs(event.y - drag.start[1]) < self.px(6):
                return
            drag.active = True
            self.tree.configure(cursor="hand2")
        found = self._drop_target(drag.node, event.y)
        self._clear_indicator()
        drag.target = None
        if found is None:
            return
        new_parent, before, zone, row_iid = found
        drag.target = (new_parent, before)
        if zone == "into":
            drag.highlight = row_iid
            tags = tuple(self.tree.item(row_iid, "tags"))
            self.tree.item(row_iid, tags=tags + ("drop",))
        else:
            self._show_line(row_iid, at_top=(zone == "before"))

    def _drag_release(self, _event: tk.Event) -> None:
        drag, self._drag = self._drag, None
        self._clear_indicator()
        self.tree.configure(cursor="")
        if drag is None or not drag.active or drag.target is None or self.root_folder is None:
            return
        new_parent, before = drag.target
        try:
            model.move_node(self.root_folder, drag.node, new_parent, before)
        except TemplateError as exc:
            self.say(str(exc), error=True)
            return
        self._open.add(new_parent.uid)
        self._changed()
        self.refresh(select=drag.node)

    def _clear_indicator(self) -> None:
        drag = self._drag
        if drag is not None and drag.highlight and self.tree.exists(drag.highlight):
            tags = tuple(t for t in self.tree.item(drag.highlight, "tags") if t != "drop")
            self.tree.item(drag.highlight, tags=tags)
        if drag is not None:
            drag.highlight = None
        if self._line is not None:
            self._line.place_forget()

    def _show_line(self, iid: str, at_top: bool) -> None:
        box = self.tree.bbox(iid, "#0")
        if not box:
            return
        x, y, w, h = box
        if self._line is None:
            self._line = tk.Frame(self.tree, height=2, background="#1a73e8")
        self._line.place(x=x, y=y if at_top else y + h - 1, width=max(w, 20), height=2)
        self._line.lift()

    def _drop_target(self, dragged: Node, y: int
                     ) -> Optional[Tuple[Folder, Optional[Node], str, str]]:
        """Where would dropping at height ``y`` put the dragged item?

        Returns (new parent, insert-before item, zone, row to mark) or None.
        """
        found = self._raw_drop_target(dragged, y)
        if found is not None and isinstance(dragged, Folder) and model.contains(dragged, found[0]):
            return None                      # a folder can't go inside itself
        return found

    def _raw_drop_target(self, dragged: Node, y: int
                         ) -> Optional[Tuple[Folder, Optional[Node], str, str]]:
        root = self.root_folder
        if root is None:
            return None
        iid = self.tree.identify_row(y)
        target = self._nodes.get(iid)
        if target is None or target is dragged:
            return None
        box = self.tree.bbox(iid)
        if not box:
            return None
        _x, top, _w, height = box
        position = (y - top) / float(height or 1)
        zone = "before" if position < 0.25 else "after" if position > 0.75 else "into"

        def following(node: Node) -> Optional[Node]:
            parent, items = self._siblings_of(node)
            for i, item in enumerate(items):
                if item is node:
                    return items[i + 1] if i + 1 < len(items) else None
            return None

        if isinstance(dragged, Folder):
            if isinstance(target, DocSpec):
                parent = model.find_parent(root, target)
                return (parent, None, "into", _iid(parent)) if parent else None
            if target is root or zone == "into":
                return target, None, "into", iid
            parent = model.find_parent(root, target)
            if parent is None:
                return None
            if zone == "before":
                return parent, target, "before", iid
            if _truthy(self.tree.item(iid, "open")) and target.folders:
                return target, target.folders[0], "after", iid
            return parent, following(target), "after", iid

        if isinstance(target, Folder):
            return target, None, "into", iid
        parent = model.find_parent(root, target)
        if parent is None:
            return None
        if zone == "before":
            return parent, target, "before", iid
        return parent, following(target), "after", iid
