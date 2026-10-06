import os
import tempfile
import unittest

from foldertemplatemaker import model
from foldertemplatemaker.model import DocSpec, Folder, Template, TemplateError


def names_of(folders):
    return [f.name for f in folders]


def build():
    """Diligence
         Legal
           Contracts
         Financial
         Tax
    """
    root = Folder("Diligence")
    legal = model.add_folder(root, "Legal")
    contracts = model.add_folder(legal, "Contracts")
    financial = model.add_folder(root, "Financial")
    tax = model.add_folder(root, "Tax")
    return root, legal, contracts, financial, tax


class AddRenameRemoveTests(unittest.TestCase):
    def test_add_folder_default_names_are_unique(self):
        root = Folder("Top")
        a = model.add_folder(root)
        b = model.add_folder(root)
        c = model.add_folder(root)
        self.assertEqual([a.name, b.name, c.name],
                         ["New folder", "New folder (2)", "New folder (3)"])

    def test_add_folder_before(self):
        root = Folder("Top")
        a = model.add_folder(root, "A")
        c = model.add_folder(root, "C")
        model.add_folder(root, "B", before=c)
        self.assertEqual(names_of(root.folders), ["A", "B", "C"])
        self.assertIs(root.folders[0], a)

    def test_add_folder_validates(self):
        root = Folder("Top")
        with self.assertRaises(TemplateError):
            model.add_folder(root, "bad/name")
        with self.assertRaises(TemplateError):
            model.add_folder(root, "   ")
        model.add_folder(root, "Legal")
        with self.assertRaises(TemplateError):
            model.add_folder(root, "legal")      # same name, different case
        self.assertEqual(len(root.folders), 1)

    def test_add_folder_trims_whitespace(self):
        root = Folder("Top")
        self.assertEqual(model.add_folder(root, "  Legal \t").name, "Legal")

    def test_rename(self):
        root, legal, contracts, financial, tax = build()
        model.rename_folder(root, legal, "Legal & Compliance")
        self.assertEqual(legal.name, "Legal & Compliance")
        model.rename_folder(root, legal, "LEGAL & COMPLIANCE")   # only the case changes
        self.assertEqual(legal.name, "LEGAL & COMPLIANCE")
        with self.assertRaises(TemplateError):
            model.rename_folder(root, legal, "tax")              # clashes with sibling
        with self.assertRaises(TemplateError):
            model.rename_folder(root, legal, "CON")
        self.assertEqual(legal.name, "LEGAL & COMPLIANCE")
        model.rename_folder(root, root, "New top")               # the root can be renamed
        self.assertEqual(root.name, "New top")

    def test_remove(self):
        root, legal, contracts, financial, tax = build()
        model.remove_node(root, legal)                           # takes its sub folders along
        self.assertEqual(names_of(root.folders), ["Financial", "Tax"])
        self.assertFalse(model.contains(root, contracts))
        with self.assertRaises(TemplateError):
            model.remove_node(root, root)

    def test_remove_document(self):
        root = Folder("Top")
        doc = model.add_doc(root, DocSpec("Notes", ".txt", ""))
        model.remove_node(root, doc)
        self.assertEqual(root.docs, [])


class MoveTests(unittest.TestCase):
    def test_move_into_other_folder(self):
        root, legal, contracts, financial, tax = build()
        model.move_node(root, tax, financial)
        self.assertEqual(names_of(root.folders), ["Legal", "Financial"])
        self.assertEqual(names_of(financial.folders), ["Tax"])

    def test_move_before_sibling(self):
        root, legal, contracts, financial, tax = build()
        model.move_node(root, tax, root, before=legal)
        self.assertEqual(names_of(root.folders), ["Tax", "Legal", "Financial"])

    def test_move_to_end(self):
        root, legal, contracts, financial, tax = build()
        model.move_node(root, legal, root)
        self.assertEqual(names_of(root.folders), ["Financial", "Tax", "Legal"])

    def test_move_before_itself_is_a_no_op(self):
        root, legal, contracts, financial, tax = build()
        model.move_node(root, legal, root, before=legal)
        self.assertEqual(names_of(root.folders), ["Legal", "Financial", "Tax"])

    def test_cannot_move_into_itself_or_descendant(self):
        root, legal, contracts, financial, tax = build()
        with self.assertRaises(TemplateError):
            model.move_node(root, legal, legal)
        with self.assertRaises(TemplateError):
            model.move_node(root, legal, contracts)
        self.assertEqual(names_of(root.folders), ["Legal", "Financial", "Tax"])

    def test_cannot_move_root(self):
        root, *_ = build()
        with self.assertRaises(TemplateError):
            model.move_node(root, root, root)

    def test_name_clash_in_new_parent(self):
        root, legal, contracts, financial, tax = build()
        model.add_folder(financial, "Contracts")
        with self.assertRaises(TemplateError):
            model.move_node(root, contracts, financial)
        self.assertIn(contracts, legal.folders)

    def test_move_document_between_folders(self):
        root, legal, contracts, financial, tax = build()
        doc = model.add_doc(legal, DocSpec("Index", ".txt", ""))
        model.move_node(root, doc, financial)
        self.assertEqual(legal.docs, [])
        self.assertEqual(financial.docs, [doc])

    def test_move_up_and_down(self):
        root, legal, contracts, financial, tax = build()
        self.assertFalse(model.move_up(root, legal))             # already first
        self.assertTrue(model.move_down(root, legal))
        self.assertEqual(names_of(root.folders), ["Financial", "Legal", "Tax"])
        self.assertTrue(model.move_up(root, tax))
        self.assertEqual(names_of(root.folders), ["Financial", "Tax", "Legal"])
        self.assertFalse(model.move_down(root, legal))           # already last
        self.assertFalse(model.move_up(root, root))              # root has no siblings

    def test_move_up_and_down_for_documents(self):
        root = Folder("Top")
        a = model.add_doc(root, DocSpec("A", ".txt"))
        b = model.add_doc(root, DocSpec("B", ".txt"))
        self.assertTrue(model.move_down(root, a))
        self.assertEqual(root.docs, [b, a])

    def test_indent(self):
        root, legal, contracts, financial, tax = build()
        self.assertFalse(model.indent(root, legal))              # nothing above it
        self.assertTrue(model.indent(root, tax))                 # becomes a child of Financial
        self.assertEqual(names_of(financial.folders), ["Tax"])
        self.assertEqual(names_of(root.folders), ["Legal", "Financial"])

    def test_indent_name_clash(self):
        root, legal, contracts, financial, tax = build()
        model.add_folder(legal, "Financial")
        with self.assertRaises(TemplateError):
            model.indent(root, financial)                        # Legal already has "Financial"

    def test_outdent(self):
        root, legal, contracts, financial, tax = build()
        self.assertTrue(model.outdent(root, contracts))
        self.assertEqual(names_of(root.folders), ["Legal", "Contracts", "Financial", "Tax"])
        self.assertFalse(model.outdent(root, legal))             # already top level
        self.assertFalse(model.outdent(root, root))

    def test_outdent_a_document(self):
        root, legal, contracts, financial, tax = build()
        doc = model.add_doc(legal, DocSpec("Index", ".txt"))
        self.assertTrue(model.outdent(root, doc))
        self.assertEqual(root.docs, [doc])
        self.assertEqual(legal.docs, [])


class DocumentTests(unittest.TestCase):
    def test_default_document_is_valid(self):
        self.assertIsNone(model.doc_problem(DocSpec()))

    def test_problems(self):
        self.assertIn("needs a name", model.doc_problem(DocSpec("  ", ".txt")))
        self.assertIsNotNone(model.doc_problem(DocSpec("ok", "txt")))
        self.assertIsNotNone(model.doc_problem(DocSpec("a/b", ".txt")))
        self.assertIsNotNone(model.doc_problem(DocSpec("CON", ".txt")))
        self.assertIsNotNone(model.doc_problem(DocSpec("{title}:x", ".txt")))
        self.assertIsNone(model.doc_problem(DocSpec("{title} raw data", ".md")))
        self.assertIsNone(model.doc_problem(DocSpec("README", "")))

    def test_add_doc_rejects_duplicates_ignoring_case(self):
        root = Folder("Top")
        model.add_doc(root, DocSpec("Notes", ".txt"))
        with self.assertRaises(TemplateError):
            model.add_doc(root, DocSpec("NOTES", ".TXT"))
        model.add_doc(root, DocSpec("Notes", ".md"))             # different type is fine
        self.assertEqual(len(root.docs), 2)

    def test_update_doc(self):
        root = Folder("Top")
        doc = model.add_doc(root, DocSpec("Notes", ".txt", "old"))
        model.update_doc(root, doc, "Raw", ".md", "line1\r\nline2\rline3")
        self.assertEqual((doc.name, doc.ext, doc.content), ("Raw", ".md", "line1\nline2\nline3"))
        with self.assertRaises(TemplateError):
            model.update_doc(root, doc, "x/y", ".md", "")
        self.assertEqual(doc.name, "Raw")

    def test_update_doc_can_keep_its_own_name(self):
        root = Folder("Top")
        doc = model.add_doc(root, DocSpec("Notes", ".txt"))
        model.update_doc(root, doc, "Notes", ".txt", "now with text")   # must not clash with itself
        self.assertEqual(doc.content, "now with text")


class OutlineTests(unittest.TestCase):
    def test_flat_list(self):
        folders, problems = model.parse_outline("Legal\nFinancial\n\nTax\n")
        self.assertEqual(problems, [])
        self.assertEqual(names_of(folders), ["Legal", "Financial", "Tax"])

    def test_nesting_by_indentation(self):
        text = "Legal\n  Contracts\n    Signed\n  Disputes\nTax\n"
        folders, problems = model.parse_outline(text)
        self.assertEqual(problems, [])
        self.assertEqual(names_of(folders), ["Legal", "Tax"])
        self.assertEqual(names_of(folders[0].folders), ["Contracts", "Disputes"])
        self.assertEqual(names_of(folders[0].folders[0].folders), ["Signed"])

    def test_tabs_and_four_spaces_work_too(self):
        folders, problems = model.parse_outline("A\n\tB\n\t\tC\nD\n    E\n")
        self.assertEqual(problems, [])
        self.assertEqual(names_of(folders), ["A", "D"])
        self.assertEqual(names_of(folders[0].folders[0].folders), ["C"])
        self.assertEqual(names_of(folders[1].folders), ["E"])

    def test_bullets_are_ignored(self):
        text = "- Legal\n  * Contracts\n• Tax\n"
        folders, problems = model.parse_outline(text)
        self.assertEqual(problems, [])
        self.assertEqual(names_of(folders), ["Legal", "Tax"])
        self.assertEqual(names_of(folders[0].folders), ["Contracts"])

    def test_numbered_names_are_kept(self):
        folders, problems = model.parse_outline("01 Corporate\n02 Financial\n")
        self.assertEqual(names_of(folders), ["01 Corporate", "02 Financial"])

    def test_uneven_dedent(self):
        folders, problems = model.parse_outline("A\n    B\n  C\nD\n")
        self.assertEqual(problems, [])
        self.assertEqual(names_of(folders), ["A", "D"])
        self.assertEqual(names_of(folders[0].folders), ["B", "C"])

    def test_first_line_indented(self):
        folders, problems = model.parse_outline("    A\n    B\n")
        self.assertEqual(names_of(folders), ["A", "B"])

    def test_problems_report_line_numbers(self):
        folders, problems = model.parse_outline("Good\nbad:name\nGood\nCON\n")
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("Line 2"))
        self.assertTrue(problems[1].startswith("Line 3") and "twice" in problems[1])
        self.assertTrue(problems[2].startswith("Line 4"))

    def test_empty_text(self):
        self.assertEqual(model.parse_outline("  \n\n"), ([], []))


class SerializationTests(unittest.TestCase):
    def test_round_trip(self):
        root, legal, contracts, financial, tax = build()
        model.add_doc(legal, DocSpec("{title} index", ".md", "# {title}\nline two\n"))
        template = Template("My template", root)
        data = model.template_to_dict(template)
        back = model.template_from_dict(data)
        self.assertEqual(back.id, template.id)
        self.assertEqual(back.name, "My template")
        self.assertEqual(model.folder_to_dict(back.root), model.folder_to_dict(root))

    def test_lenient_loading(self):
        data = {"name": "T", "root": {"name": 5, "folders": [None, "x", {"name": "ok"}],
                                      "documents": ["bad", {"name": "d", "ext": "md", "content": "a\r\nb"}]}}
        template = model.template_from_dict(data)
        self.assertEqual(template.root.name, "5")
        self.assertEqual(names_of(template.root.folders), ["ok"])
        self.assertEqual(template.root.docs[0].ext, ".md")
        self.assertEqual(template.root.docs[0].content, "a\nb")

    def test_template_without_root_gets_one_named_after_it(self):
        template = model.template_from_dict({"name": "Only a name"})
        self.assertEqual(template.name, "Only a name")
        self.assertEqual(template.root.name, "Only a name")

    def test_not_a_template(self):
        with self.assertRaises(TemplateError):
            model.template_from_dict([])

    def test_excessive_depth_is_cut_off(self):
        node = {"name": "leaf"}
        for _ in range(model.MAX_DEPTH + 20):
            node = {"name": "n", "folders": [node]}
        root = model.folder_from_dict(node)
        depth, cur = 0, root
        while cur.folders:
            cur, depth = cur.folders[0], depth + 1
        self.assertLessEqual(depth, model.MAX_DEPTH + 1)

    def test_clone_is_independent(self):
        root, legal, *_ = build()
        template = Template("T", root)
        copy = template.clone()
        self.assertEqual(copy.id, template.id)
        self.assertEqual(model.folder_to_dict(copy.root), model.folder_to_dict(root))
        copy.root.folders[0].name = "Changed"
        self.assertEqual(legal.name, "Legal")
        self.assertNotEqual(copy.clone(new_id=True).id, template.id)

    def test_sample_template_is_valid(self):
        sample = model.sample_template()
        for folder in model.iter_folders(sample.root):
            self.assertIsNone(model.name_problem(folder.name), folder.name)
        for doc in model.iter_docs(sample.root):
            self.assertIsNone(model.doc_problem(doc))
        self.assertEqual(model.count_docs(sample.root), 1)


class WalkTests(unittest.TestCase):
    def test_counts_and_lookup(self):
        root, legal, contracts, financial, tax = build()
        model.add_doc(tax, DocSpec("x", ".txt"))
        self.assertEqual(model.count_folders(root), 5)
        self.assertEqual(model.count_docs(root), 1)
        self.assertEqual([f.name for f in model.iter_folders(root)],
                         ["Diligence", "Legal", "Contracts", "Financial", "Tax"])
        self.assertIs(model.find_parent(root, contracts), legal)
        self.assertIsNone(model.find_parent(root, root))
        self.assertIs(model.find_by_uid(root, tax.uid), tax)
        self.assertIsNone(model.find_by_uid(root, -1))


class FolderFromDiskTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def mk(self, *parts, file=False):
        path = os.path.join(self.base, *parts)
        if file:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("x")
        else:
            os.makedirs(path, exist_ok=True)

    def test_imports_structure_naturally_sorted_and_counts_ignored_files(self):
        self.mk("Deal", "10 Misc")
        self.mk("Deal", "2 Tax", "Returns")
        self.mk("Deal", "1 Legal")
        self.mk("Deal", "readme.txt", file=True)
        self.mk("Deal", "1 Legal", "contract.pdf", file=True)
        root, report = model.folder_from_disk(os.path.join(self.base, "Deal"))
        self.assertEqual(root.name, "Deal")
        self.assertEqual(names_of(root.folders), ["1 Legal", "2 Tax", "10 Misc"])
        self.assertEqual(names_of(root.folders[1].folders), ["Returns"])
        self.assertEqual(report.folders, 4)
        self.assertEqual(report.files_ignored, 2)
        self.assertFalse(report.truncated)
        self.assertEqual(root.docs, [])

    def test_skips_unusable_names(self):
        self.mk("Deal", "ok")
        self.mk("Deal", "bad:name")
        self.mk("Deal", "$RECYCLE.BIN")
        root, report = model.folder_from_disk(os.path.join(self.base, "Deal"))
        self.assertEqual(names_of(root.folders), ["ok"])
        self.assertCountEqual(report.skipped, ["bad:name", "$RECYCLE.BIN"])

    def test_limits(self):
        for i in range(10):
            self.mk("Deal", "f%02d" % i)
        root, report = model.folder_from_disk(os.path.join(self.base, "Deal"), max_folders=4)
        self.assertEqual(len(root.folders), 4)
        self.assertTrue(report.truncated)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlinks_are_not_followed(self):
        self.mk("Deal", "real")
        os.symlink(os.path.join(self.base, "Deal"), os.path.join(self.base, "Deal", "loop"))
        root, report = model.folder_from_disk(os.path.join(self.base, "Deal"))
        self.assertEqual(names_of(root.folders), ["real"])

    def test_not_a_folder(self):
        self.mk("a.txt", file=True)
        with self.assertRaises(TemplateError):
            model.folder_from_disk(os.path.join(self.base, "a.txt"))
        with self.assertRaises(TemplateError):
            model.folder_from_disk(os.path.join(self.base, "missing"))


if __name__ == "__main__":
    unittest.main()
