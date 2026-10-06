import unittest
from datetime import date

from foldertemplatemaker import names
from foldertemplatemaker.names import PlaceholderContext


class NameProblemTests(unittest.TestCase):
    def test_ordinary_names_are_fine(self):
        for name in ["Diligence folder", "01 Corporate", "A.B", "résumé",
                     "名前", "Q3 (draft)", "M&A", "a" * 255, "CONSOLE", "COM10",
                     "Comet", "AUXILIARY", "LPT", "COM", "Notes.v2", "{title}", "x~y"]:
            self.assertIsNone(names.name_problem(name), name)

    def test_empty_and_blank(self):
        self.assertIn("empty", names.name_problem(""))
        self.assertIn("empty", names.name_problem("   "))

    def test_invalid_characters(self):
        for ch in '<>:"/\\|?*':
            problem = names.name_problem("a%sb" % ch)
            self.assertIsNotNone(problem, ch)
            self.assertIn(ch, problem)
        self.assertIsNotNone(names.name_problem("tab\there"))
        self.assertIsNotNone(names.name_problem("line\nbreak"))

    def test_leading_trailing_space_and_trailing_period(self):
        self.assertIn("space", names.name_problem("name "))
        self.assertIn("space", names.name_problem(" name"))
        self.assertIn("period", names.name_problem("name."))
        self.assertIsNotNone(names.name_problem("."))
        self.assertIsNotNone(names.name_problem(".."))

    def test_reserved_names(self):
        for name in ["CON", "con", "Con.txt", "PRN", "AUX", "NUL", "COM1", "com9",
                     "LPT9.log", "COM0", "LPT0", "COM²", "nul.tar.gz"]:
            self.assertIn("reserved", names.name_problem(name) or "", name)

    def test_onedrive_restrictions(self):
        for name in ["desktop.ini", "Desktop.INI", ".lock", "~$temp", "x_vti_y"]:
            self.assertIn("OneDrive", names.name_problem(name) or "", name)

    def test_too_long(self):
        self.assertIn("too long", names.name_problem("a" * 256))


class CleanAndSanitizeTests(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(names.clean_name("  a\tb \n"), "a b")
        self.assertEqual(names.clean_name("plain"), "plain")

    def test_sanitize_for_filename(self):
        self.assertEqual(names.sanitize_for_filename("M&A: Deal / 2026"), "M&A- Deal - 2026")
        self.assertEqual(names.sanitize_for_filename("Report."), "Report")
        self.assertEqual(names.sanitize_for_filename("a|b"), "a-b")

    def test_extension_problem(self):
        for ok in ["", ".txt", ".md", ".csv", ".tar-gz"]:
            self.assertIsNone(names.extension_problem(ok), ok)
        for bad in ["txt", ".", ".t xt", ".a.b", ".t/x", "..txt"]:
            self.assertIsNotNone(names.extension_problem(bad), bad)


class UniqueNameTests(unittest.TestCase):
    def test_free_name_is_unchanged(self):
        self.assertEqual(names.unique_name("New folder", []), "New folder")
        self.assertEqual(names.unique_name("New folder", ["Other"]), "New folder")

    def test_clash_gets_a_number(self):
        self.assertEqual(names.unique_name("New folder", ["New folder"]), "New folder (2)")
        self.assertEqual(
            names.unique_name("New folder", ["New folder", "New folder (2)"]), "New folder (3)")

    def test_comparison_ignores_case(self):
        self.assertEqual(names.unique_name("Legal", ["legal"]), "Legal (2)")


class PlaceholderTests(unittest.TestCase):
    def setUp(self):
        self.ctx = PlaceholderContext(
            title="Xcom Diligence", folder="Work product",
            template="Diligence folder template", today=date(2026, 10, 6))

    def test_known_placeholders(self):
        r = names.resolve
        self.assertEqual(r("{title} raw data", self.ctx), "Xcom Diligence raw data")
        self.assertEqual(r("{folder}", self.ctx), "Work product")
        self.assertEqual(r("{template}", self.ctx), "Diligence folder template")
        self.assertEqual(r("{date}", self.ctx), "2026-10-06")
        self.assertEqual(r("{date_long}", self.ctx), "October 6, 2026")
        self.assertEqual(r("{year}", self.ctx), "2026")

    def test_case_insensitive_and_repeated(self):
        self.assertEqual(names.resolve("{TITLE}/{Title}", self.ctx),
                         "Xcom Diligence/Xcom Diligence")

    def test_unknown_placeholders_and_stray_braces_are_left_alone(self):
        self.assertEqual(names.resolve("{nope} {", self.ctx), "{nope} {")
        self.assertEqual(names.resolve("{ title }", self.ctx), "{ title }")
        self.assertEqual(names.resolve("a { b } c", self.ctx), "a { b } c")

    def test_filename_mode_sanitizes_values_only(self):
        ctx = PlaceholderContext("T", "F", "M&A: Deal / Template", date(2026, 1, 2))
        self.assertEqual(names.resolve("{template}", ctx, for_filename=True),
                         "M&A- Deal - Template")
        self.assertEqual(names.resolve("{template}", ctx), "M&A: Deal / Template")
        # Literal text typed by the user is not touched (validation catches it).
        self.assertEqual(names.resolve("a:b {title}", ctx, for_filename=True), "a:b T")

    def test_unknown_placeholders_are_reported(self):
        self.assertEqual(names.unknown_placeholders("{titel} and {title} and {x_y}"),
                         ["{titel}", "{x_y}"])
        self.assertEqual(names.unknown_placeholders("{TITLE}"), [])


if __name__ == "__main__":
    unittest.main()
