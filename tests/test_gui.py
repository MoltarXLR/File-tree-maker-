"""Tests that drive the real window.  They need tkinter and a display (the CI machine has one;
on Linux run them under ``xvfb-run``) and are skipped when there isn't one."""

import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

try:
    import tkinter as tk
    _probe = tk.Tk()
    _probe.destroy()
    HAVE_TK = True
except Exception:                      # no tkinter, or no display
    HAVE_TK = False

if HAVE_TK:
    from foldertemplatemaker import app as app_module
    from foldertemplatemaker import editor as editor_module
    from foldertemplatemaker import model
    from foldertemplatemaker.gui import App
    from foldertemplatemaker.storage import Store


class FakeDocumentDialog:
    """Stands in for the pop-up: 'types' ``submit`` and presses OK."""
    submit = ("", ".txt", "")
    last_error = "never shown"
    kwargs: dict = {}

    def __init__(self, parent, **kwargs):
        type(self).kwargs = kwargs

    def show(self):
        cls = type(self)
        cls.last_error = cls.kwargs["apply"](*cls.submit)
        return cls.last_error is None


class FakeOutlineDialog:
    submit = ("",)
    last_error = "never shown"
    kwargs: dict = {}

    def __init__(self, parent, **kwargs):
        type(self).kwargs = kwargs

    def show(self):
        cls = type(self)
        cls.last_error = cls.kwargs["apply"](*cls.submit)
        return cls.last_error is None


@unittest.skipUnless(HAVE_TK, "needs tkinter and a display")
class GuiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, "data"))
        self.store.load()
        self.dest = os.path.join(self.tmp.name, "OneDrive", "Deals")
        os.makedirs(self.dest)

        self.app = App(self.store)
        self.addCleanup(self._destroy)
        self.errors, self.infos, self.confirms = [], [], []
        self.confirm_answer = True
        self.save_choice = "cancel"
        self.app.error = lambda title, message: self.errors.append((title, message))
        self.app.info = lambda title, message: self.infos.append((title, message))
        self.app.confirm = self._confirm
        self.app.ask_save_changes = lambda: self.save_choice
        self.editor = self.app.editor
        self.pump()

    def _destroy(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass

    def _confirm(self, title, message, default_no=True):
        self.confirms.append((title, message))
        return self.confirm_answer

    def pump(self):
        for _ in range(3):
            self.app.update()

    # -- small helpers ------------------------------------------------------- #

    @property
    def root(self):
        return self.app.current.root

    def folder(self, *path):
        node = self.root
        for name in path:
            node = next(f for f in node.folders if f.name == name)
        return node

    def names(self, folder=None):
        return [f.name for f in (folder or self.root).folders]

    def iid(self, node):
        return ("f%d" if isinstance(node, model.Folder) else "d%d") % node.uid

    def type_name(self, text):
        entry = self.editor._editing.entry
        entry.delete(0, "end")
        entry.insert(0, text)

    def select_in_list(self, template_id):
        self.app.template_list.selection_set(template_id)
        self.pump()


class StartupTests(GuiCase):
    def test_opens_on_the_example_template(self):
        app = self.app
        self.assertEqual(app.current.name, "Diligence folder template")
        self.assertEqual(self.names(), ["Source documents", "Work product", "Correspondence"])
        self.assertEqual(app.tname_var.get(), "Diligence folder template")
        self.assertEqual(app.rname_var.get(), "Diligence folder")
        self.assertEqual(app.name_var.get(), "Diligence folder")
        self.assertEqual(len(self.editor._nodes), 5)          # top folder, 3 folders, 1 document
        self.assertFalse(app.dirty)
        self.assertEqual(app.title(), "Folder Template Maker")
        self.assertEqual(app.open_button.winfo_manager(), "")

    def test_the_selftest_used_by_the_build_passes(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            report = os.path.join(tmp, "report.txt")
            code = app_module.run_selftest(report)
            with open(report, encoding="utf-8") as handle:
                text = handle.read()
        self.assertEqual(code, 0, text)
        self.assertIn("SELFTEST PASSED", text)


class CreateTests(GuiCase):
    def create(self, name, dest=None):
        self.app.dest_var.set(dest or self.dest)
        self.app.name_var.set(name)
        self.app.create()

    def test_create_builds_the_folders_in_the_chosen_place_with_the_chosen_name(self):
        self.create("Xcom Diligence")
        top = os.path.join(self.dest, "Xcom Diligence")
        for sub in ("Source documents", "Work product", "Correspondence"):
            self.assertTrue(os.path.isdir(os.path.join(top, sub)), sub)
        self.assertTrue(os.path.isfile(os.path.join(top, "Work product", "Xcom Diligence raw data.txt")))
        self.assertEqual(self.errors, [])
        self.assertIn("Created", self.app.result_var.get())
        self.assertEqual(self.app.open_button.winfo_manager(), "grid")
        self.assertEqual(self.app.last_created, top)
        again = Store(self.store.directory)
        again.load()
        self.assertEqual(again.settings.destination, self.dest)
        self.assertEqual(again.settings.recent_destinations[0], self.dest)

    def test_the_stale_already_exists_notice_is_not_shown_right_after_creating(self):
        self.create("Fresh")
        self.app._update_preview()
        self.assertEqual(self.app.info_var.get(), "")
        self.app.name_var.set("Fresh 2")                        # typing again brings the preview back
        self.app._update_preview()
        self.assertIn("Will create", self.app.info_var.get())
        self.assertEqual(self.app.result_var.get(), "")
        self.assertEqual(self.app.open_button.winfo_manager(), "")

    def test_existing_folder_asks_before_anything_is_added(self):
        self.create("Again")
        shutil.rmtree(os.path.join(self.dest, "Again", "Correspondence"))
        self.confirm_answer = False
        self.app.create()
        self.assertFalse(os.path.exists(os.path.join(self.dest, "Again", "Correspondence")))
        self.confirm_answer = True
        self.app.create()
        self.assertTrue(os.path.isdir(os.path.join(self.dest, "Again", "Correspondence")))
        self.assertEqual(len(self.confirms), 2)
        self.assertIn("already exists", self.confirms[0][0])

    def test_a_bad_name_is_reported_and_nothing_is_created(self):
        self.create("Bad: name")
        self.assertEqual(len(self.errors), 1)
        self.assertIn("can't be used", self.errors[0][1])
        self.assertEqual(os.listdir(self.dest), [])
        self.assertEqual(self.app.open_button.winfo_manager(), "")

    def test_a_missing_destination_is_reported(self):
        self.create("Deal", dest=os.path.join(self.tmp.name, "nope"))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("doesn't exist", self.errors[0][1])

    def test_open_after_create_opens_the_new_folder(self):
        opened = []
        with mock.patch("foldertemplatemaker.osutil.open_in_file_manager", opened.append):
            self.app.open_after_var.set(True)
            self.create("Opened")
            self.assertEqual(opened, [os.path.join(self.dest, "Opened")])
            self.app.open_result()
            self.assertEqual(len(opened), 2)

    def test_unsaved_edits_are_used_for_creating_what_you_see_is_what_you_get(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.type_name("Tax")
        self.editor._commit_edit(via_return=False)
        self.assertTrue(self.app.dirty)
        self.create("WYSIWYG")
        self.assertTrue(os.path.isdir(os.path.join(self.dest, "WYSIWYG", "Tax")))

    def test_preview_line(self):
        app = self.app
        app.dest_var.set(self.dest)
        app.name_var.set("Deal 1")
        app._update_preview()
        self.assertIn(os.path.join(self.dest, "Deal 1"), app.info_var.get())
        self.assertIn("3 sub folders, 1 document", app.info_var.get())
        app.name_var.set("a/b")
        app._update_preview()
        self.assertIn("can't be used", app.info_var.get())
        os.makedirs(os.path.join(self.dest, "Deal 1"))
        app.name_var.set("Deal 1")
        app._update_preview()
        self.assertIn("already exists", app.info_var.get())
        app.dest_var.set("")
        app._update_preview()
        self.assertIn("Choose where", app.info_var.get())

    def test_destination_is_remembered_for_each_template(self):
        first = self.app.current.id
        self.create("One")
        self.app.new_template()
        second = self.app.current.id
        self.assertNotEqual(first, second)
        self.assertEqual(self.app.dest_var.get(), self.dest)         # falls back to the last one used
        other = os.path.join(self.tmp.name, "Other")
        os.makedirs(other)
        self.create("Two", dest=other)
        self.select_in_list(first)
        self.assertEqual(self.app.current.id, first)
        self.assertEqual(self.app.dest_var.get(), self.dest)
        self.select_in_list(second)
        self.assertEqual(self.app.dest_var.get(), other)

    def test_enter_in_the_name_box_creates(self):
        self.app.dest_var.set(self.dest)
        self.app.name_var.set("ByEnter")
        self.app.name_entry.focus_force()
        self.pump()
        self.app.name_entry.event_generate("<Return>")
        self.pump()
        self.assertTrue(os.path.isdir(os.path.join(self.dest, "ByEnter")))


class InlineEditingTests(GuiCase):
    def test_add_subfolder_by_typing_names_and_pressing_enter(self):
        ed = self.editor
        ed.select(self.root)
        ed.add_subfolder()
        self.assertEqual(ed._editing.entry.get(), "New folder")      # starts with a usable name
        self.type_name("Tax")
        ed._commit_edit(via_return=True)
        self.assertEqual(self.names()[-1], "Tax")
        self.assertTrue(self.app.dirty)
        self.assertTrue(self.app.title().startswith("* "))
        self.assertEqual(ed._editing.entry.get(), "")                # ready for the next name
        self.type_name("Insurance")
        ed._commit_edit(via_return=True)
        self.assertEqual(self.names()[-2:], ["Tax", "Insurance"])
        ed._commit_edit(via_return=True)                              # Enter on an empty line: done
        self.assertIsNone(ed._editing)
        self.assertFalse(ed.tree.exists(editor_module.NEW_IID))
        self.assertEqual(len(self.root.folders), 5)

    def test_escape_cancels_a_new_folder(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.editor._abort_edit()
        self.assertEqual(len(self.root.folders), 3)
        self.assertFalse(self.app.dirty)
        self.assertFalse(self.editor.tree.exists(editor_module.NEW_IID))

    def test_clicking_away_keeps_the_suggested_name_without_chaining(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.editor._commit_edit(via_return=False)
        self.assertEqual(self.names()[-1], "New folder")
        self.assertIsNone(self.editor._editing)

    def test_clicking_away_from_the_blank_follow_up_adds_nothing(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.type_name("Tax")
        self.editor._commit_edit(via_return=True)
        self.editor._commit_edit(via_return=False)                    # focus lost on the empty entry
        self.assertEqual(len(self.root.folders), 4)

    def test_add_to_a_nested_folder_and_it_opens(self):
        work = self.folder("Work product")
        self.editor.select(work)
        self.editor.add_subfolder()
        self.type_name("Analysis")
        self.editor._commit_edit(via_return=False)
        self.assertEqual(self.names(work), ["Analysis"])
        self.assertTrue(self.editor.tree.item(self.iid(work), "open"))

    def test_add_sibling_goes_right_after_the_selected_folder(self):
        self.editor.select(self.folder("Source documents"))
        self.editor.add_sibling()
        self.type_name("Insurance")
        self.editor._commit_edit(via_return=False)
        self.assertEqual(self.names(), ["Source documents", "Insurance", "Work product", "Correspondence"])

    def test_adding_with_a_document_selected_adds_to_its_folder(self):
        doc = self.folder("Work product").docs[0]
        self.editor.select(doc)
        self.editor.add_subfolder()
        self.type_name("Analysis")
        self.editor._commit_edit(via_return=False)
        self.assertEqual(self.names(self.folder("Work product")), ["Analysis"])

    def test_rename_a_folder_inline(self):
        node = self.folder("Correspondence")
        self.editor.select(node)
        self.editor.rename_selected()
        self.assertEqual(self.editor._editing.entry.get(), "Correspondence")
        self.type_name("Emails & letters")
        self.editor._commit_edit(via_return=True)
        self.assertEqual(node.name, "Emails & letters")
        self.assertIsNone(self.editor._editing)
        self.assertEqual(self.editor.tree.item(self.iid(node), "text"), "Emails & letters")
        self.assertTrue(self.app.dirty)

    def test_a_bad_name_keeps_the_editor_open_on_enter_but_is_dropped_on_focus_loss(self):
        node = self.folder("Correspondence")
        self.editor.select(node)
        self.editor.rename_selected()
        self.type_name("a/b")
        self.editor._commit_edit(via_return=True)
        self.assertIsNotNone(self.editor._editing)
        self.assertIn("Names can't contain", self.editor.message_var.get())
        self.editor._commit_edit(via_return=False)
        self.assertIsNone(self.editor._editing)
        self.assertEqual(node.name, "Correspondence")
        self.assertFalse(self.app.dirty)

    def test_renaming_to_a_sibling_name_is_refused(self):
        node = self.folder("Correspondence")
        self.editor.select(node)
        self.editor.rename_selected()
        self.type_name("source DOCUMENTS")
        self.editor._commit_edit(via_return=True)
        self.assertIn("already contains", self.editor.message_var.get())
        self.assertEqual(node.name, "Correspondence")
        self.editor._abort_edit()

    def test_renaming_the_top_folder_updates_the_boxes_and_the_default_name(self):
        self.editor.select(self.root)
        self.editor.rename_selected()
        self.type_name("Matter folder")
        self.editor._commit_edit(via_return=True)
        self.assertEqual(self.app.rname_var.get(), "Matter folder")
        self.assertEqual(self.app.name_var.get(), "Matter folder")
        self.assertEqual(self.root.name, "Matter folder")

    def test_double_click_on_a_name_starts_renaming_and_on_a_document_opens_it(self):
        self.pump()
        node = self.folder("Correspondence")
        x, y, w, h = self.editor._text_box(self.iid(node))
        event = types.SimpleNamespace(x=x + 3, y=y + h // 2)
        self.assertEqual(self.editor._on_double_click(event), "break")
        self.assertIsNotNone(self.editor._editing)
        self.assertEqual(self.editor.selected_node(), node)
        self.editor._abort_edit()
        with mock.patch.object(editor_module, "DocumentDialog", FakeDocumentDialog):
            FakeDocumentDialog.submit = ("{title} raw data", ".txt", "x")
            doc = self.folder("Work product").docs[0]
            x, y, w, h = self.editor._text_box(self.iid(doc))
            self.editor._on_double_click(types.SimpleNamespace(x=x + 3, y=y + h // 2))
        self.assertEqual(FakeDocumentDialog.kwargs["title"], "Edit document")
        self.assertEqual(doc.content, "x")

    def test_the_inline_box_sits_over_the_text_of_the_row(self):
        node = self.folder("Correspondence")
        self.editor.select(node)
        self.editor.rename_selected()
        entry = self.editor._editing.entry
        self.pump()
        text_x = self.editor._text_box(self.iid(node))[0]
        self.assertLessEqual(abs(entry.winfo_x() - (text_x - 2)), 2)
        self.assertGreater(entry.winfo_width(), 50)
        self.editor._abort_edit()


class StructureOperationTests(GuiCase):
    def test_delete_asks_only_when_the_folder_has_content(self):
        ed = self.editor
        ed.select(self.folder("Source documents"))
        ed.delete_selected()
        self.assertEqual(self.confirms, [])
        self.assertEqual(self.names(), ["Work product", "Correspondence"])
        work = self.folder("Work product")
        ed.select(work)
        self.confirm_answer = False
        ed.delete_selected()
        self.assertIn(work, self.root.folders)
        self.confirm_answer = True
        ed.delete_selected()
        self.assertNotIn(work, self.root.folders)
        self.assertTrue(self.app.dirty)
        self.assertEqual(ed.selected_node().name, "Correspondence")

    def test_the_top_folder_cannot_be_deleted(self):
        ed = self.editor
        ed.select(self.root)
        self.pump()
        self.assertTrue(ed.buttons["delete"].instate(["disabled"]))
        ed.delete_selected()
        self.assertEqual(len(self.root.folders), 3)
        self.assertIn("can't be deleted", ed.message_var.get())

    def test_move_buttons_follow_the_selection(self):
        ed = self.editor
        ed.select(self.folder("Source documents"))
        self.pump()
        self.assertTrue(ed.buttons["up"].instate(["disabled"]))
        self.assertTrue(ed.buttons["down"].instate(["!disabled"]))
        self.assertTrue(ed.buttons["in"].instate(["disabled"]))       # nothing above to move into
        self.assertTrue(ed.buttons["out"].instate(["disabled"]))      # already top level
        ed.move_down()
        self.assertEqual(self.names()[:2], ["Work product", "Source documents"])
        self.assertTrue(ed.buttons["in"].instate(["!disabled"]))
        ed.indent()                                                    # into "Work product"
        self.assertEqual(self.names(self.folder("Work product")), ["Source documents"])
        self.assertTrue(ed.buttons["out"].instate(["!disabled"]))
        ed.outdent()
        self.assertEqual(self.names(), ["Work product", "Source documents", "Correspondence"])
        self.assertEqual(ed.selected_node().name, "Source documents")

    def test_keyboard_shortcuts_are_wired(self):
        tree = self.editor.tree
        for sequence in ("<F2>", "<Delete>", "<Insert>", "<Alt-Up>", "<Alt-Down>", "<Alt-Left>",
                         "<Alt-Right>", "<Double-1>", "<Button-3>"):
            self.assertTrue(tree.bind(sequence), sequence)

    def test_add_several_folders_through_the_dialog(self):
        with mock.patch.object(editor_module, "OutlineDialog", FakeOutlineDialog):
            self.editor.select(self.root)
            FakeOutlineDialog.submit = ("Legal\n  Contracts\nTax\n",)
            self.editor.add_several()
            self.assertIsNone(FakeOutlineDialog.last_error)
            self.assertEqual(self.names()[-2:], ["Legal", "Tax"])
            self.assertEqual(self.names(self.folder("Legal")), ["Contracts"])
            FakeOutlineDialog.submit = ("Legal\n",)                    # clashes with the one just added
            self.editor.select(self.root)
            self.editor.add_several()
            self.assertIn("already contains", FakeOutlineDialog.last_error)
            FakeOutlineDialog.submit = ("fine\nbad/name\n",)
            self.editor.add_several()
            self.assertTrue(FakeOutlineDialog.last_error.startswith("Line 2"))
            FakeOutlineDialog.submit = ("  \n",)
            self.editor.add_several()
            self.assertIn("at least one", FakeOutlineDialog.last_error)
        self.assertNotIn("fine", self.names())                         # all or nothing

    def test_add_and_edit_a_document_through_the_dialog(self):
        self.app.name_var.set("Xcom Diligence")
        with mock.patch.object(editor_module, "DocumentDialog", FakeDocumentDialog):
            self.editor.select(self.folder("Correspondence"))
            FakeDocumentDialog.submit = ("{title} checklist", ".md", "Checklist for {title}\r\n")
            self.editor.add_document()
            doc = self.folder("Correspondence").docs[0]
            self.assertEqual((doc.name, doc.ext, doc.content), ("{title} checklist", ".md", "Checklist for {title}\n"))
            self.assertEqual(FakeDocumentDialog.kwargs["folder_name"], "Correspondence")
            self.assertEqual(FakeDocumentDialog.kwargs["preview"]("{title} checklist", ".md"),
                             "Xcom Diligence checklist.md")
            self.assertEqual(FakeDocumentDialog.kwargs["preview"]("{folder} notes", ".txt"),
                             "Correspondence notes.txt")
            self.assertEqual(self.editor.selected_node(), doc)
            FakeDocumentDialog.submit = ("{TITLE} CHECKLIST", ".MD", "")     # same name ignoring case
            self.editor.select(self.folder("Correspondence"))
            self.editor.add_document()
            self.assertIn("already contains", FakeDocumentDialog.last_error)
            self.assertEqual(len(self.folder("Correspondence").docs), 1)
            FakeDocumentDialog.submit = ("Renamed", ".txt", "new text")
            self.editor.select(doc)
            self.editor.edit_document()
            self.assertEqual((doc.name, doc.ext, doc.content), ("Renamed", ".txt", "new text"))
        self.assertTrue(self.app.dirty)

    def test_documents_added_to_the_top_folder_use_the_new_name_for_folder(self):
        self.app.name_var.set("Deal Room")
        with mock.patch.object(editor_module, "DocumentDialog", FakeDocumentDialog):
            self.editor.select(self.root)
            FakeDocumentDialog.submit = ("{folder} index", ".txt", "")
            self.editor.add_document()
            self.assertEqual(FakeDocumentDialog.kwargs["preview"]("{folder} index", ".txt"),
                             "Deal Room index.txt")


class DragAndDropTests(GuiCase):
    def drag(self, source, target, where="into"):
        ed = self.editor
        self.pump()
        sx, sy, sw, sh = ed._text_box(self.iid(source))
        tx, ty, tw, th = ed.tree.bbox(self.iid(target))
        y = {"before": ty + 2, "into": ty + th // 2, "after": ty + th - 3}[where]
        at = lambda yy: types.SimpleNamespace(x=sx + 4, y=yy)
        ed._drag_press(at(sy + sh // 2))
        ed._drag_motion(at(sy + sh // 2 + ed.px(10)))
        ed._drag_motion(at(y))
        ed._drag_release(at(y))
        self.pump()

    def test_drop_onto_the_middle_of_a_folder_moves_it_inside(self):
        src, dst = self.folder("Correspondence"), self.folder("Source documents")
        self.drag(src, dst, "into")
        self.assertEqual(self.names(dst), ["Correspondence"])
        self.assertEqual(self.names(), ["Source documents", "Work product"])
        self.assertEqual(self.editor.selected_node(), src)
        self.assertTrue(self.app.dirty)

    def test_drop_on_the_top_edge_of_a_row_moves_it_before(self):
        self.drag(self.folder("Correspondence"), self.folder("Source documents"), "before")
        self.assertEqual(self.names(), ["Correspondence", "Source documents", "Work product"])

    def test_drop_on_the_bottom_edge_of_a_row_moves_it_after(self):
        self.drag(self.folder("Source documents"), self.folder("Work product"), "after")
        self.assertEqual(self.names(), ["Work product", "Source documents", "Correspondence"])

    def test_drop_after_an_open_folder_with_subfolders_goes_in_as_its_first_child(self):
        work = self.folder("Work product")
        model.add_folder(work, "Analysis")
        self.editor.refresh()
        self.drag(self.folder("Correspondence"), work, "after")
        self.assertEqual(self.names(work), ["Correspondence", "Analysis"])

    def test_a_document_can_be_dragged_into_another_folder(self):
        doc = self.folder("Work product").docs[0]
        self.drag(doc, self.folder("Correspondence"), "into")
        self.assertEqual(self.folder("Work product").docs, [])
        self.assertEqual(self.folder("Correspondence").docs, [doc])

    def test_a_folder_cannot_be_dropped_into_itself_or_what_is_inside_it(self):
        work = self.folder("Work product")
        sub = model.add_folder(work, "Analysis")
        self.editor.refresh()
        self.drag(work, sub, "into")
        self.assertEqual(self.names(), ["Source documents", "Work product", "Correspondence"])
        self.assertEqual(self.names(work), ["Analysis"])
        self.drag(work, work.docs[0], "into")
        self.assertEqual(self.names(), ["Source documents", "Work product", "Correspondence"])

    def test_dropping_on_empty_space_changes_nothing(self):
        ed = self.editor
        self.pump()
        src = self.folder("Correspondence")
        sx, sy, sw, sh = ed._text_box(self.iid(src))
        at = lambda yy: types.SimpleNamespace(x=sx + 4, y=yy)
        ed._drag_press(at(sy + sh // 2))
        ed._drag_motion(at(sy + 40))
        ed._drag_motion(at(ed.tree.winfo_height() - 2))
        ed._drag_release(at(ed.tree.winfo_height() - 2))
        self.assertEqual(self.names(), ["Source documents", "Work product", "Correspondence"])
        self.assertFalse(self.app.dirty)

    def test_a_plain_click_is_not_a_drag(self):
        ed = self.editor
        self.pump()
        src = self.folder("Correspondence")
        sx, sy, sw, sh = ed._text_box(self.iid(src))
        at = types.SimpleNamespace(x=sx + 4, y=sy + sh // 2)
        ed._drag_press(at)
        ed._drag_release(at)
        self.assertFalse(self.app.dirty)

    def test_a_name_clash_at_the_destination_is_reported(self):
        model.add_folder(self.folder("Source documents"), "Correspondence")
        self.editor.refresh()
        self.drag(self.folder("Correspondence"), self.folder("Source documents"), "into")
        self.assertIn("already contains", self.editor.message_var.get())
        self.assertIn("Correspondence", self.names())

    def test_the_top_folder_cannot_be_dragged(self):
        ed = self.editor
        self.pump()
        x, y, w, h = ed._text_box(self.iid(self.root))
        ed._drag_press(types.SimpleNamespace(x=x + 4, y=y + h // 2))
        self.assertIsNone(ed._drag)


class TemplateManagementTests(GuiCase):
    def test_save_persists_and_clears_the_unsaved_marker(self):
        self.app.tname_var.set("Renamed template")
        self.assertTrue(self.app.dirty)
        self.assertEqual(self.app.save_state_var.get(), "Unsaved changes")
        self.assertEqual(self.app.template_list.item(self.app.current.id, "text"), "Renamed template *")
        self.assertTrue(self.app.save())
        self.assertFalse(self.app.dirty)
        self.assertEqual(self.app.title(), "Folder Template Maker")
        self.assertEqual(self.app.template_list.item(self.app.current.id, "text"), "Renamed template")
        again = Store(self.store.directory)
        again.load()
        self.assertEqual(again.templates[0].name, "Renamed template")

    def test_structure_changes_are_saved_too(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.type_name("Tax")
        self.editor._commit_edit(via_return=False)
        self.app.save()
        again = Store(self.store.directory)
        again.load()
        self.assertEqual(self.names(again.templates[0].root)[-1], "Tax")

    def test_saving_commits_a_name_that_is_still_being_typed(self):
        self.editor.select(self.root)
        self.editor.add_subfolder()
        self.type_name("Typed but not entered")
        self.assertTrue(self.app.save())
        self.assertEqual(self.names()[-1], "Typed but not entered")

    def test_a_clashing_or_blank_template_name_cannot_be_saved(self):
        self.app.new_template()
        self.app.tname_var.set("diligence FOLDER template")
        self.assertFalse(self.app.save())
        self.assertTrue(self.app.dirty)
        self.assertEqual(len(self.errors), 1)
        self.app.tname_var.set("   ")
        self.assertFalse(self.app.save())
        self.assertEqual(len(self.errors), 2)

    def test_a_bad_top_folder_name_cannot_be_saved(self):
        self.app.rname_var.set("bad/name")
        self.assertEqual(self.app.rname_error_label.winfo_manager(), "grid")
        self.assertEqual(self.root.name, "Diligence folder")          # the tree keeps the last good name
        self.assertFalse(self.app.save())
        self.app.rname_var.set("Good name")
        self.assertEqual(self.app.rname_error_label.winfo_manager(), "")
        self.assertTrue(self.app.save())

    def test_typing_the_top_folder_name_updates_the_tree_and_follows_into_the_create_box(self):
        self.app.rname_var.set("Deal room")
        self.assertEqual(self.root.name, "Deal room")
        self.assertEqual(self.editor.tree.item(self.iid(self.root), "text"), "Deal room")
        self.assertEqual(self.app.name_var.get(), "Deal room")
        self.app.name_var.set("Custom name")                           # the user takes over this box...
        self.app.rname_var.set("Deal room 2")
        self.assertEqual(self.app.name_var.get(), "Custom name")       # ...so it stops following

    def test_switching_with_unsaved_changes_asks(self):
        self.app.new_template()
        other = self.app.current.id
        first = self.store.templates[0].id
        self.app.tname_var.set("Edited")
        self.save_choice = "cancel"
        self.select_in_list(first)
        self.assertEqual(self.app.current.id, other)
        self.assertEqual(self.app.template_list.selection(), (other,))
        self.assertTrue(self.app.dirty)
        self.save_choice = "discard"
        self.select_in_list(first)
        self.assertEqual(self.app.current.id, first)
        self.assertEqual(self.store.get(other).name, "New template")   # the edit was thrown away
        self.app.tname_var.set("Kept")
        self.save_choice = "save"
        self.select_in_list(other)
        self.assertEqual(self.app.current.id, other)
        self.assertEqual(self.store.get(first).name, "Kept")

    def test_new_copy_and_delete(self):
        app = self.app
        app.new_template()
        self.assertEqual(app.current.name, "New template")
        self.assertEqual(self.root.name, "New folder")
        app.tname_var.set("Litigation")
        app.save()
        app.duplicate_template()
        self.assertEqual(app.current.name, "Copy of Litigation")
        self.assertEqual([t.name for t in self.store.templates],
                         ["Diligence folder template", "Litigation", "Copy of Litigation"])
        self.assertEqual(len(app.template_list.get_children()), 3)
        self.confirm_answer = False
        app.delete_template()
        self.assertEqual(len(self.store.templates), 3)
        self.confirm_answer = True
        app.delete_template()
        self.assertEqual(len(self.store.templates), 2)
        self.assertEqual(app.current.name, "Litigation")

    def test_deleting_the_last_template_leaves_a_usable_empty_window(self):
        app = self.app
        app.delete_template()
        self.assertIsNone(app.current)
        self.assertIsNone(self.editor.root_folder)
        self.assertEqual(str(app.create_button.cget("state")), "disabled")
        self.assertIn("no templates", app.info_var.get())
        app.create()                                                  # does nothing, doesn't crash
        app.save()
        app.new_template()
        self.assertEqual(app.current.name, "New template")
        self.assertEqual(str(app.create_button.cget("state")), "normal")

    def test_closing_with_unsaved_changes_can_be_cancelled(self):
        self.app.tname_var.set("Edited")
        self.save_choice = "cancel"
        self.app.on_close()
        self.assertTrue(self.app.winfo_exists())
        self.save_choice = "discard"
        self.app.on_close()
        with self.assertRaises(tk.TclError):
            self.app.winfo_exists()

    def test_window_size_and_position_are_remembered(self):
        self.app.on_close()
        again = Store(self.store.directory)
        again.load()
        self.assertRegex(again.settings.geometry, r"^\d+x\d+\+-?\d+\+-?\d+$")

    def test_import_a_folder_as_a_template(self):
        base = os.path.join(self.tmp.name, "Old template")
        os.makedirs(os.path.join(base, "A", "A1"))
        os.makedirs(os.path.join(base, "B"))
        with open(os.path.join(base, "note.txt"), "w") as handle:
            handle.write("x")
        self.app.pick_directory = lambda title, initial: base
        self.app.import_from_folder()
        self.assertEqual(self.app.current.name, "Old template")
        self.assertEqual(self.names(), ["A", "B"])
        self.assertEqual(self.names(self.folder("A")), ["A1"])
        self.assertEqual(len(self.infos), 1)
        self.assertIn("3 folders", self.infos[0][1])
        self.assertIn("1 file", self.infos[0][1])
        self.assertEqual(len(self.store.templates), 2)

    def test_cancelling_the_folder_chooser_does_nothing(self):
        self.app.pick_directory = lambda title, initial: ""
        self.app.import_from_folder()
        self.assertEqual(len(self.store.templates), 1)

    def test_export_then_import_a_template_file(self):
        path = os.path.join(self.tmp.name, "shared.json")
        self.app.pick_save_file = lambda title, initial: path
        self.app.export_template()
        self.assertTrue(os.path.isfile(path))
        self.app.pick_open_file = lambda title: path
        self.app.import_template_file()
        self.assertEqual(self.app.current.name, "Diligence folder template (2)")
        self.assertEqual(len(self.store.templates), 2)
        self.assertEqual(self.errors, [])

    def test_importing_something_that_is_not_a_template_is_reported(self):
        path = os.path.join(self.tmp.name, "junk.json")
        with open(path, "w") as handle:
            handle.write("not json at all")
        self.app.pick_open_file = lambda title: path
        self.app.import_template_file()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(len(self.store.templates), 1)

    def test_quick_places_menu_lists_recent_destinations(self):
        self.app.dest_var.set(self.dest)
        self.app.name_var.set("Menu")
        self.app.create()
        self.app._fill_places_menu()
        labels = [self.app.places_menu.entrycget(i, "label")
                  for i in range(self.app.places_menu.index("end") + 1)
                  if self.app.places_menu.type(i) == "command"]
        self.assertIn(self.dest, labels)

    def test_help_and_about_open(self):
        for opener in (self.app.show_help, self.app.show_about):
            with mock.patch("foldertemplatemaker.gui.TextDialog") as dialog:
                opener()
                self.assertTrue(dialog.return_value.show.called)


if __name__ == "__main__":
    unittest.main()
