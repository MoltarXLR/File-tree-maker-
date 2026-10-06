import errno
import ntpath
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from foldertemplatemaker import builder, model
from foldertemplatemaker.builder import FolderExistsError, PlanError, PlanItem
from foldertemplatemaker.model import DocSpec, Folder, Template

TODAY = date(2026, 10, 6)


def make_template():
    """Diligence folder
         Source documents
         Work product            ({title} raw data.txt)
           Analysis
         Correspondence
    """
    root = Folder("Diligence folder")
    model.add_folder(root, "Source documents")
    work = model.add_folder(root, "Work product")
    model.add_folder(work, "Analysis")
    model.add_folder(root, "Correspondence")
    model.add_doc(work, DocSpec("{title} raw data", ".txt", "Raw data - {title}\nCreated {date_long}\n"))
    return Template("Diligence folder template", root)


def tree_of(base):
    """Sorted list of every folder/file below ``base`` as relative, '/'-separated paths."""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            out.append(os.path.relpath(os.path.join(dirpath, name), base).replace(os.sep, "/"))
    return sorted(out)


class TmpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dest = os.path.join(tmp.name, "OneDrive", "Deals")
        os.makedirs(self.dest)


class CreateTests(TmpCase):
    def test_creates_the_structure_under_the_chosen_name(self):
        result = builder.create_from_template(
            make_template(), self.dest, "Xcom Diligence", today=TODAY)
        self.assertTrue(result.ok)
        self.assertEqual(tree_of(self.dest), [
            "Xcom Diligence",
            "Xcom Diligence/Correspondence",
            "Xcom Diligence/Source documents",
            "Xcom Diligence/Work product",
            "Xcom Diligence/Work product/Analysis",
            "Xcom Diligence/Work product/Xcom Diligence raw data.txt",
        ])
        self.assertEqual(result.top_path, os.path.join(self.dest, "Xcom Diligence"))
        self.assertFalse(result.top_existed)
        self.assertEqual(len(result.folders_created), 5)
        self.assertEqual(len(result.docs_created), 1)

    def test_document_text_has_placeholders_filled_and_windows_line_endings(self):
        builder.create_from_template(make_template(), self.dest, "Xcom Diligence", today=TODAY)
        path = os.path.join(self.dest, "Xcom Diligence", "Work product", "Xcom Diligence raw data.txt")
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"Raw data - Xcom Diligence\r\nCreated October 6, 2026\r\n")

    def test_folder_placeholder_is_the_folder_the_document_sits_in(self):
        root = Folder("Top")
        sub = model.add_folder(root, "Work product")
        model.add_doc(root, DocSpec("{folder} index", ".txt", "in {folder}"))
        model.add_doc(sub, DocSpec("{folder} notes", ".txt", "in {folder} of {title}"))
        builder.create_from_template(Template("T", root), self.dest, "Deal 7", today=TODAY)
        with open(os.path.join(self.dest, "Deal 7", "Deal 7 index.txt")) as fh:
            self.assertEqual(fh.read(), "in Deal 7")   # for the top folder, {folder} is the new name
        with open(os.path.join(self.dest, "Deal 7", "Work product", "Work product notes.txt")) as fh:
            self.assertEqual(fh.read(), "in Work product of Deal 7")

    def test_default_name_works_too(self):
        template = make_template()
        builder.create_from_template(template, self.dest, template.root.name, today=TODAY)
        self.assertIn("Diligence folder/Work product/Diligence folder raw data.txt", tree_of(self.dest))

    def test_non_ascii_text_gets_a_bom_and_ascii_does_not(self):
        self.assertEqual(builder.encode_document("plain\ntext"), b"plain\r\ntext")
        self.assertTrue(builder.encode_document("caf\u00e9").startswith(b"\xef\xbb\xbf"))
        self.assertEqual(builder.encode_document("caf\u00e9").decode("utf-8-sig"), "caf\u00e9")
        self.assertEqual(builder.encode_document("a\r\nb\rc\n"), b"a\r\nb\r\nc\r\n")

    def test_empty_template_creates_just_the_top_folder(self):
        result = builder.create_from_template(Template("T", Folder("Top")), self.dest, "Solo")
        self.assertEqual(tree_of(self.dest), ["Solo"])
        self.assertEqual(result.summary(), 'Created "Solo".')

    def test_a_file_with_a_blank_content_is_still_created(self):
        root = Folder("Top")
        model.add_doc(root, DocSpec("empty", ".txt", ""))
        builder.create_from_template(Template("T", root), self.dest, "X")
        self.assertEqual(os.path.getsize(os.path.join(self.dest, "X", "empty.txt")), 0)

    def test_destination_path_text_is_cleaned_up(self):
        builder.create_from_template(make_template(), '  "%s"  ' % self.dest, "Quoted", today=TODAY)
        self.assertTrue(os.path.isdir(os.path.join(self.dest, "Quoted", "Work product")))


class ExistingStuffTests(TmpCase):
    def test_existing_folder_is_refused_unless_allowed(self):
        os.makedirs(os.path.join(self.dest, "Xcom Diligence"))
        with self.assertRaises(FolderExistsError) as ctx:
            builder.create_from_template(make_template(), self.dest, "Xcom Diligence")
        self.assertEqual(ctx.exception.path, os.path.join(self.dest, "Xcom Diligence"))
        self.assertEqual(tree_of(self.dest), ["Xcom Diligence"])      # untouched

    def test_merge_adds_only_what_is_missing_and_never_touches_existing_files(self):
        top = os.path.join(self.dest, "Xcom Diligence")
        os.makedirs(os.path.join(top, "Work product"))
        os.makedirs(os.path.join(top, "My own folder"))
        mine = os.path.join(top, "Work product", "Xcom Diligence raw data.txt")
        with open(mine, "w") as fh:
            fh.write("PRECIOUS")
        result = builder.create_from_template(
            make_template(), self.dest, "Xcom Diligence", allow_existing=True, today=TODAY)
        self.assertTrue(result.ok)
        self.assertTrue(result.top_existed)
        with open(mine) as fh:
            self.assertEqual(fh.read(), "PRECIOUS")
        self.assertIn("Xcom Diligence/My own folder", tree_of(self.dest))
        self.assertIn("Xcom Diligence/Source documents", tree_of(self.dest))
        self.assertEqual(result.docs_skipped, [os.sep.join(["Xcom Diligence", "Work product",
                                                             "Xcom Diligence raw data.txt"])])
        self.assertEqual(result.docs_created, [])
        self.assertEqual(len(result.folders_created), 3)     # Source documents, Analysis, Correspondence
        self.assertIn("Added 3 sub folders", result.summary())
        self.assertIn("1 document already existed", result.summary())

    def test_running_twice_adds_nothing_the_second_time(self):
        builder.create_from_template(make_template(), self.dest, "Again", today=TODAY)
        again = builder.create_from_template(
            make_template(), self.dest, "Again", allow_existing=True, today=TODAY)
        self.assertEqual(again.folders_created, [])
        self.assertEqual(again.docs_created, [])
        self.assertIn("nothing was added", again.summary())

    def test_a_file_in_the_way_is_a_problem(self):
        with open(os.path.join(self.dest, "Clash"), "w") as fh:
            fh.write("x")
        with self.assertRaises(PlanError) as ctx:
            builder.create_from_template(make_template(), self.dest, "Clash", allow_existing=True)
        self.assertIn("file named", " ".join(ctx.exception.problems))

    def test_a_folder_where_a_document_should_go_is_reported_not_overwritten(self):
        top = os.path.join(self.dest, "Odd")
        os.makedirs(os.path.join(top, "Work product", "Odd raw data.txt"))     # a *folder*
        result = builder.create_from_template(
            make_template(), self.dest, "Odd", allow_existing=True, today=TODAY)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("folder with that name", result.errors[0][1])


class ValidationTests(TmpCase):
    def assertNothingCreated(self):
        self.assertEqual(os.listdir(self.dest), [])

    def test_bad_title(self):
        for bad in ["", "   ", "a/b", "Deal: One", "CON", "Ends with.", "x" * 300]:
            with self.assertRaises(PlanError, msg=bad):
                builder.create_from_template(make_template(), self.dest, bad)
        self.assertNothingCreated()

    def test_title_is_trimmed(self):
        builder.create_from_template(make_template(), self.dest, "  Padded  ", today=TODAY)
        self.assertEqual(os.listdir(self.dest), ["Padded"])

    def test_bad_names_inside_the_template_block_everything(self):
        root = Folder("Top", folders=[Folder("fine"), Folder("bad|name")])
        with self.assertRaises(PlanError) as ctx:
            builder.create_from_template(Template("T", root), self.dest, "Deal")
        self.assertIn("bad|name", " ".join(ctx.exception.problems))
        self.assertNothingCreated()

    def test_duplicate_names_ignoring_case_block_everything(self):
        root = Folder("Top", folders=[Folder("Legal"), Folder("LEGAL")])
        with self.assertRaises(PlanError) as ctx:
            builder.create_from_template(Template("T", root), self.dest, "Deal")
        self.assertIn("twice", " ".join(ctx.exception.problems))
        self.assertNothingCreated()

    def test_document_and_folder_may_not_share_a_name(self):
        root = Folder("Top", folders=[Folder("Notes.txt")], docs=[DocSpec("Notes", ".txt")])
        with self.assertRaises(PlanError):
            builder.create_from_template(Template("T", root), self.dest, "Deal")
        self.assertNothingCreated()

    def test_document_names_that_resolve_badly_are_caught(self):
        root = Folder("Top", docs=[DocSpec("{title}", ".txt")])
        with self.assertRaises(PlanError):                      # "CON" + ".txt" is reserved
            builder.create_from_template(Template("T", root), self.dest, "CON")
        root = Folder("Top", docs=[DocSpec("x", "txt")])
        with self.assertRaises(PlanError):
            builder.create_from_template(Template("T", root), self.dest, "Fine")
        self.assertNothingCreated()

    def test_template_name_with_bad_characters_is_made_safe_in_file_names(self):
        root = Folder("Top", docs=[DocSpec("{template} checklist", ".txt")])
        builder.create_from_template(Template("M&A: Deal / Standard", root), self.dest, "Fine")
        self.assertEqual(os.listdir(os.path.join(self.dest, "Fine")), ["M&A- Deal - Standard checklist.txt"])

    def test_missing_destination(self):
        gone = os.path.join(self.dest, "does not exist")
        with self.assertRaises(PlanError) as ctx:
            builder.create_from_template(make_template(), gone, "X")
        self.assertIn("doesn't exist", " ".join(ctx.exception.problems))
        with self.assertRaises(PlanError):
            builder.create_from_template(make_template(), "   ", "X")
        self.assertFalse(os.path.exists(gone))                  # never invents the destination

    def test_destination_that_is_a_file(self):
        path = os.path.join(self.dest, "afile")
        with open(path, "w") as fh:
            fh.write("x")
        with self.assertRaises(PlanError):
            builder.create_from_template(make_template(), path, "X")

    def test_preview_reports_state_and_counts(self):
        info = builder.preview(make_template(), self.dest, "New one", today=TODAY)
        self.assertTrue(info.ok)
        self.assertEqual((info.top_state, info.folder_count, info.doc_count), ("new", 5, 1))
        os.makedirs(os.path.join(self.dest, "New one"))
        self.assertEqual(builder.preview(make_template(), self.dest, "New one").top_state, "folder")
        bad = builder.preview(make_template(), self.dest, "a:b")
        self.assertFalse(bad.ok)
        self.assertEqual(bad.top_state, "unknown")
        nodest = builder.preview(make_template(), "", "x")
        self.assertIsNotNone(nodest.destination_problem)

    def test_template_stats(self):
        self.assertEqual(builder.template_stats(make_template()), (4, 1))


class PathLengthTests(unittest.TestCase):
    BASE = "C:\\x"                                           # 4 characters

    def test_limits_for_folders_and_files(self):
        def problems(kind, name_len):
            item = PlanItem(kind, ("d" * name_len,))
            return builder.path_length_problems([item], self.BASE, windows=True)
        self.assertEqual(problems("dir", 242), [])           # 4 + 1 + 242 = 247
        self.assertEqual(len(problems("dir", 243)), 1)       # 248
        self.assertEqual(problems("file", 254), [])          # 259
        self.assertEqual(len(problems("file", 255)), 1)      # 260

    def test_message_names_the_worst_path_and_counts_the_rest(self):
        items = [PlanItem("dir", ("a" * 250,)), PlanItem("dir", ("b" * 251,)), PlanItem("dir", ("c",))]
        (message,) = builder.path_length_problems(items, self.BASE, windows=True)
        self.assertIn("256 characters", message)
        self.assertIn("and 1 more", message)

    def test_not_checked_on_other_systems(self):
        item = PlanItem("dir", ("d" * 400,))
        self.assertEqual(builder.path_length_problems([item], self.BASE, windows=False), [])

    def test_preview_applies_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Folder("Top")
            deep = root
            for _ in range(6):
                deep = model.add_folder(deep, "n" * 50)
            info = builder.preview(Template("T", root), tmp, "Deal", windows=True)
            self.assertFalse(info.ok)
            self.assertIn("characters", info.problems[0])
            self.assertTrue(builder.preview(Template("T", root), tmp, "Deal", windows=False).ok)


class FailureHandlingTests(TmpCase):
    def test_a_folder_that_cant_be_made_is_reported_and_its_children_skipped(self):
        real_makedirs = os.makedirs

        def fake_makedirs(path, *args, **kwargs):
            if os.path.basename(path) == "Work product":
                raise PermissionError(errno.EACCES, "Access is denied", path)
            return real_makedirs(path, *args, **kwargs)

        with mock.patch("os.makedirs", fake_makedirs):
            result = builder.create_from_template(make_template(), self.dest, "Partial", today=TODAY)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.errors), 1)               # Analysis + the document: no extra noise
        item, reason = result.errors[0]
        self.assertTrue(item.endswith("Work product"))
        self.assertIn("permission", reason)
        self.assertEqual(tree_of(self.dest), [
            "Partial", "Partial/Correspondence", "Partial/Source documents"])

    def test_error_descriptions_are_readable(self):
        d = builder.describe_os_error
        self.assertIn("permission", d(PermissionError(errno.EACCES, "x")))
        self.assertIn("too long", d(OSError(errno.ENAMETOOLONG, "x")))
        self.assertIn("full", d(OSError(errno.ENOSPC, "x")))
        self.assertIn("couldn't be found", d(FileNotFoundError(errno.ENOENT, "x")))
        self.assertIn("already exists", d(FileExistsError(errno.EEXIST, "x")))
        self.assertEqual(d(OSError(errno.EIO, "Input/output error")), "Input/output error")


class SummaryTests(unittest.TestCase):
    def test_summary_wording(self):
        r = builder.CreationResult(os.path.join("d", "Deal"), False,
                                   folders_created=["Deal", "Deal/a"], docs_created=["Deal/a/x.txt"])
        self.assertEqual(r.summary(), 'Created "Deal" with 1 sub folder and 1 document.')
        r = builder.CreationResult(os.path.join("d", "Deal"), False,
                                   folders_created=["Deal", "Deal/a", "Deal/b"])
        self.assertEqual(r.summary(), 'Created "Deal" with 2 sub folders.')


if __name__ == "__main__":
    unittest.main()
