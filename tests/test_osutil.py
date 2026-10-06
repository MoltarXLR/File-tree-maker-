import os
import tempfile
import unittest
from unittest import mock

from foldertemplatemaker import osutil


class PathTextTests(unittest.TestCase):
    def test_quotes_and_spaces_from_copy_as_path_are_removed(self):
        self.assertEqual(osutil.normalize_path_text('  "C:\\Users\\me\\OneDrive\\Deals"  '),
                         "C:\\Users\\me\\OneDrive\\Deals")
        self.assertEqual(osutil.normalize_path_text("'/tmp/x y'"), "/tmp/x y")
        self.assertEqual(osutil.normalize_path_text("   "), "")

    def test_variables_and_home_are_expanded(self):
        with mock.patch.dict(os.environ, {"MY_DEALS": "/data/deals"}):
            self.assertEqual(osutil.normalize_path_text("$MY_DEALS/x" if os.name != "nt" else "%MY_DEALS%\\x"),
                             os.path.join("/data/deals", "x") if os.name != "nt" else "/data/deals\\x")
        self.assertEqual(osutil.normalize_path_text("~"), os.path.expanduser("~"))


class DataDirTests(unittest.TestCase):
    def test_override_via_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {osutil.HOME_ENV_VAR: tmp}):
                self.assertEqual(osutil.app_data_dir(), os.path.abspath(tmp))

    def test_default_location_ends_with_the_app_folder(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(osutil.HOME_ENV_VAR, None)
            self.assertEqual(os.path.basename(osutil.app_data_dir()), osutil.APP_DIR_NAME)

    def test_windows_uses_appdata(self):
        env = {"APPDATA": "C:\\Users\\me\\AppData\\Roaming"}
        with mock.patch.dict(os.environ, env), mock.patch.object(osutil, "is_windows", lambda: True):
            os.environ.pop(osutil.HOME_ENV_VAR, None)
            self.assertTrue(osutil.app_data_dir().startswith("C:\\Users\\me\\AppData\\Roaming"))


class QuickLocationTests(unittest.TestCase):
    def test_finds_onedrive_from_the_environment_and_skips_missing_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = os.path.join(tmp, "OneDrive - Contoso")
            os.makedirs(one)
            env = {"OneDriveCommercial": one, "OneDrive": os.path.join(tmp, "nope")}
            with mock.patch.dict(os.environ, env):
                found = osutil.quick_locations()
            self.assertIn(("OneDrive - Contoso", one), found)
            self.assertNotIn(os.path.join(tmp, "nope"), [p for _, p in found])

    def test_no_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"OneDriveCommercial": tmp, "OneDrive": tmp, "OneDriveConsumer": tmp}
            with mock.patch.dict(os.environ, env):
                found = osutil.quick_locations()
            self.assertEqual([p for _, p in found].count(tmp), 1)


if __name__ == "__main__":
    unittest.main()
