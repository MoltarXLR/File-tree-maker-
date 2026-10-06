import json
import os
import tempfile
import unittest
from unittest import mock

from foldertemplatemaker import model, storage
from foldertemplatemaker.model import DocSpec, Folder, Template, TemplateError
from foldertemplatemaker.storage import Settings, StorageError, Store


def simple_template(name="Litigation", root_name="Matter"):
    root = Folder(root_name)
    model.add_folder(root, "Pleadings")
    model.add_doc(root, DocSpec("{title} notes", ".txt", "hello {title}"))
    return Template(name, root)


class TmpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "data")          # doesn't exist yet on purpose

    def store(self):
        s = Store(self.dir)
        s.load()
        return s


class FirstRunTests(TmpCase):
    def test_first_run_creates_the_example_template_and_saves_it(self):
        s = self.store()
        self.assertEqual([t.name for t in s.templates], ["Diligence folder template"])
        self.assertEqual(s.warnings, [])
        self.assertTrue(os.path.isfile(s.templates_path))
        again = self.store()
        self.assertEqual(model.template_to_dict(again.templates[0]),
                         model.template_to_dict(s.templates[0]))

    def test_deleting_every_template_does_not_bring_the_example_back(self):
        s = self.store()
        s.delete(s.templates[0].id)
        self.assertEqual(self.store().templates, [])

    def test_unwritable_data_folder_is_a_warning_not_a_crash(self):
        s = Store(self.dir)
        with mock.patch.object(storage, "write_json_atomic", side_effect=OSError("read-only")):
            s.load()
        self.assertEqual(len(s.templates), 1)
        self.assertEqual(len(s.warnings), 1)


class TemplateListTests(TmpCase):
    def test_add_update_delete_round_trip(self):
        s = self.store()
        added = s.add(simple_template())
        self.assertIsNotNone(s.get(added.id))
        reloaded = self.store()
        self.assertEqual([t.name for t in reloaded.templates],
                         ["Diligence folder template", "Litigation"])
        self.assertEqual(model.template_to_dict(reloaded.get(added.id)), model.template_to_dict(added))

        edited = added.clone()
        model.add_folder(edited.root, "Discovery")
        edited.name = "Litigation v2"
        s.update(edited)
        reloaded = self.store()
        self.assertEqual(reloaded.get(added.id).name, "Litigation v2")
        self.assertEqual([f.name for f in reloaded.get(added.id).root.folders], ["Pleadings", "Discovery"])

        s.delete(added.id)
        self.assertIsNone(self.store().get(added.id))

    def test_the_store_keeps_its_own_copy(self):
        s = self.store()
        mine = simple_template()
        stored = s.add(mine)
        mine.root.name = "Changed afterwards"
        self.assertEqual(stored.root.name, "Matter")

    def test_names_must_be_unique_ignoring_case(self):
        s = self.store()
        s.add(simple_template("Alpha"))
        with self.assertRaises(TemplateError):
            s.add(simple_template("ALPHA"))
        other = s.add(simple_template("Beta"))
        renamed = other.clone()
        renamed.name = "alpha"
        with self.assertRaises(TemplateError):
            s.update(renamed)
        same = other.clone()
        same.name = "BETA"                                   # only the case changes: fine
        s.update(same)
        self.assertEqual(s.get(other.id).name, "BETA")

    def test_blank_name_is_rejected(self):
        s = self.store()
        t = s.templates[0].clone()
        t.name = "  "
        with self.assertRaises(TemplateError):
            s.update(t)

    def test_update_of_a_vanished_template(self):
        s = self.store()
        with self.assertRaises(TemplateError):
            s.update(simple_template())

    def test_add_after_a_given_template(self):
        s = self.store()
        first = s.add(simple_template("One"))
        s.add(simple_template("Three"))
        s.add(simple_template("Two"), after_id=first.id)
        self.assertEqual([t.name for t in s.templates][1:], ["One", "Two", "Three"])

    def test_unique_template_name(self):
        s = self.store()
        self.assertEqual(s.unique_template_name("Diligence folder template"),
                         "Diligence folder template (2)")


class BackupAndDamageTests(TmpCase):
    def test_previous_version_is_kept_as_a_backup(self):
        s = self.store()
        s.add(simple_template("Second"))
        s.add(simple_template("Third"))
        with open(s.templates_path + ".bak", encoding="utf-8") as fh:
            names = [t["name"] for t in json.load(fh)["templates"]]
        self.assertEqual(names, ["Diligence folder template", "Second"])

    def test_damaged_file_is_set_aside_and_the_backup_restored(self):
        s = self.store()
        s.add(simple_template("Second"))
        s.add(simple_template("Third"))
        with open(s.templates_path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not json")
        again = self.store()
        self.assertEqual([t.name for t in again.templates], ["Diligence folder template", "Second"])
        self.assertEqual(len(again.warnings), 1)
        self.assertIn("backup", again.warnings[0])
        kept = [n for n in os.listdir(self.dir) if ".damaged-" in n]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.dir, kept[0]), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{ this is not json")      # the evidence is preserved
        self.assertEqual(self.store().warnings, [])                # and the repaired file is fine

    def test_damaged_file_without_backup_falls_back_to_the_example(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "templates.json"), "w", encoding="utf-8") as fh:
            fh.write("garbage")
        s = self.store()
        self.assertEqual([t.name for t in s.templates], ["Diligence folder template"])
        self.assertIn("damaged", s.warnings[0])
        self.assertTrue(any(".damaged-" in n for n in os.listdir(self.dir)))

    def test_unreadable_and_unmovable_file_locks_saving_rather_than_overwriting(self):
        os.makedirs(self.dir)
        path = os.path.join(self.dir, "templates.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("garbage")
        s = Store(self.dir)
        with mock.patch.object(storage, "set_aside", side_effect=OSError("locked")):
            s.load()
        self.assertIn("NOT be saved", s.warnings[0])
        with self.assertRaises(StorageError):
            s.save_templates()
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "garbage")                 # untouched

    def test_a_byte_order_mark_is_tolerated(self):
        os.makedirs(self.dir)
        data = {"templates": [model.template_to_dict(simple_template("Edited in Notepad"))]}
        with open(os.path.join(self.dir, "templates.json"), "w", encoding="utf-8-sig") as fh:
            json.dump(data, fh)
        self.assertEqual([t.name for t in self.store().templates], ["Edited in Notepad"])

    def test_duplicate_ids_and_names_are_repaired(self):
        os.makedirs(self.dir)
        one = model.template_to_dict(simple_template("Same"))
        two = dict(one)
        data = {"templates": [one, two, "junk", 5]}
        with open(os.path.join(self.dir, "templates.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        s = self.store()
        self.assertEqual([t.name for t in s.templates], ["Same", "Same (2)"])
        self.assertEqual(len({t.id for t in s.templates}), 2)

    def test_atomic_write_leaves_no_temp_file(self):
        s = self.store()
        s.save_templates()
        s.save_settings()
        self.assertEqual(sorted(os.listdir(self.dir)),
                         ["settings.json", "templates.json", "templates.json.bak"])


class SettingsTests(TmpCase):
    def test_round_trip(self):
        s = self.store()
        s.settings.remember_destination("abc", "C:\\Users\\me\\OneDrive\\Deals")
        s.settings.open_after_create = True
        s.settings.geometry = "900x600+10+10"
        s.settings.last_template_id = "abc"
        s.save_settings()
        again = self.store().settings
        self.assertEqual(again.destination_for("abc"), "C:\\Users\\me\\OneDrive\\Deals")
        self.assertEqual(again.destination, "C:\\Users\\me\\OneDrive\\Deals")
        self.assertTrue(again.open_after_create)
        self.assertEqual(again.geometry, "900x600+10+10")
        self.assertEqual(again.last_template_id, "abc")

    def test_destination_falls_back_to_the_last_one_used(self):
        st = Settings()
        st.remember_destination("a", "/x/a")
        self.assertEqual(st.destination_for("a"), "/x/a")
        self.assertEqual(st.destination_for("never-used"), "/x/a")
        st.remember_destination("b", "/x/b")
        self.assertEqual(st.destination_for("a"), "/x/a")
        self.assertEqual(st.destination_for("c"), "/x/b")

    def test_recents_are_most_recent_first_deduplicated_and_capped(self):
        st = Settings()
        for i in range(20):
            st.remember_destination("t", "/p/%d" % i)
        st.remember_destination("t", "/p/15")
        self.assertEqual(st.recent_destinations[0], "/p/15")
        self.assertEqual(len(st.recent_destinations), storage.MAX_RECENT_DESTINATIONS)
        self.assertEqual(len(set(st.recent_destinations)), len(st.recent_destinations))

    def test_garbage_settings_are_ignored_safely(self):
        for bad in [None, [], "x", {"destination": 5, "recent_destinations": "no",
                                    "destination_by_template": [1], "open_after_create": "yes"}]:
            st = Settings.from_dict(bad)
            self.assertEqual((st.destination, st.recent_destinations, st.destination_by_template,
                              st.open_after_create), ("", [], {}, False))

    def test_unreadable_settings_file_resets_to_defaults_and_is_kept(self):
        s = self.store()
        with open(s.settings_path, "w", encoding="utf-8") as fh:
            fh.write("not json")
        again = self.store()
        self.assertEqual(again.settings.destination, "")
        self.assertTrue(any(".damaged-" in n for n in os.listdir(self.dir)))

    def test_deleting_a_template_forgets_its_destination(self):
        s = self.store()
        t = s.add(simple_template())
        s.settings.remember_destination(t.id, "/somewhere")
        s.settings.last_template_id = t.id
        s.delete(t.id)
        self.assertNotIn(t.id, s.settings.destination_by_template)
        self.assertEqual(s.settings.last_template_id, "")


class ImportExportTests(TmpCase):
    def test_export_then_import_as_a_new_template(self):
        s = self.store()
        original = s.add(simple_template("Shared"))
        path = os.path.join(self.dir, "Shared.json")
        storage.export_template(original, path)
        (loaded,) = storage.read_template_file(path)
        self.assertEqual(model.folder_to_dict(loaded.root), model.folder_to_dict(original.root))
        (added,) = s.import_templates([loaded])
        self.assertNotEqual(added.id, original.id)
        self.assertEqual(added.name, "Shared (2)")
        self.assertEqual(len(s.templates), 3)

    def test_import_accepts_a_whole_templates_file(self):
        s = self.store()
        s.add(simple_template("Extra"))
        found = storage.read_template_file(s.templates_path)
        self.assertEqual([t.name for t in found], ["Diligence folder template", "Extra"])

    def test_import_rejects_things_that_are_not_templates(self):
        os.makedirs(self.dir)
        for i, content in enumerate(["not json", "{}", "[]", '{"templates": []}', "42"]):
            path = os.path.join(self.dir, "bad%d.json" % i)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            with self.assertRaises(StorageError, msg=content):
                storage.read_template_file(path)
        with self.assertRaises(StorageError):
            storage.read_template_file(os.path.join(self.dir, "missing.json"))


if __name__ == "__main__":
    unittest.main()
