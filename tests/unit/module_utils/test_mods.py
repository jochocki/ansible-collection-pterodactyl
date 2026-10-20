import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import mods, modrinth
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient

GOOD = b"jar-bytes"
GOOD_SHA = modrinth.sha512_hex(GOOD)


def catalog(projects):
    """fetch() serving one release per project: <project>-1.0.jar."""
    def fetch(url):
        slug = url.split("/project/")[1].split("/")[0]
        if slug not in projects:
            return []
        sha = projects[slug]
        return [{"version_number": "1.0", "version_type": "release", "date_published": "2026-01-01",
                 "game_versions": ["26.3"], "loaders": ["fabric"],
                 "files": [{"filename": slug + "-1.0.jar", "url": "https://cdn/" + slug, "size": len(GOOD),
                            "primary": True, "hashes": {"sha512": sha}}]}]
    return fetch


def f(name, size=len(GOOD)):
    return {"name": name, "size": size, "is_file": True}


class Plan(unittest.TestCase):
    def test_split(self):
        wanted = [{"filename": "a.jar", "size": 9}, {"filename": "b.jar", "size": 9}, {"filename": "c.jar", "size": 9}]
        present = [f("a.jar", 9), f("b.jar", 1), f("old.jar"), f("mod-list.json")]
        pull, keep, stale = mods.plan(wanted, present)
        self.assertEqual([p["filename"] for p in pull], ["b.jar", "c.jar"])
        self.assertEqual([k["filename"] for k in keep], ["a.jar"])
        self.assertEqual(stale, ["old.jar"])  # only .jar files are ever stale


class Sync(unittest.TestCase):
    def run_sync(self, client, projects=("fabric-api",), purge=True, check_mode=False, loader="fabric", cat=None):
        cat = cat or catalog({p: GOOD_SHA for p in projects})
        return mods.sync_mods(client, "id", "26.3", loader, list(projects), cat, purge=purge, check_mode=check_mode)

    def test_upgrade_replaces_old_jar_after_pull(self):
        c = FakeClient(files=[f("fabric-api-0.9.jar")], contents={"fabric-api-1.0.jar": GOOD})
        out = self.run_sync(c)
        self.assertEqual(c.calls, [("pull_file", "fabric-api-1.0.jar"), ("delete_files", ("fabric-api-0.9.jar",))])
        self.assertEqual(out["installed"], ["fabric-api-1.0.jar"])
        self.assertEqual(out["removed"], ["fabric-api-0.9.jar"])
        self.assertTrue(out["changed"])

    def test_purge_false_leaves_old_jar(self):
        c = FakeClient(files=[f("fabric-api-0.9.jar")], contents={"fabric-api-1.0.jar": GOOD})
        out = self.run_sync(c, purge=False)
        self.assertEqual(c.names(), ["pull_file"])
        self.assertEqual(out["left_in_place"], ["fabric-api-0.9.jar"])

    def test_already_in_sync(self):
        c = FakeClient(files=[f("fabric-api-1.0.jar")])
        out = self.run_sync(c)
        self.assertFalse(out["changed"])
        self.assertEqual(c.calls, [])

    def test_unresolvable_project_touches_nothing(self):
        c = FakeClient(files=[f("old.jar")])
        with self.assertRaisesRegex(PterodactylError, "typo-mod"):
            self.run_sync(c, projects=("fabric-api", "typo-mod"), cat=catalog({"fabric-api": GOOD_SHA}))
        self.assertEqual(c.calls, [])

    def test_unknown_slug_names_the_project_and_touches_nothing(self):
        def fetch(url):
            if "/project/fabric-exporter/" in url:
                raise HttpError(404, "not found", url)
            return catalog({"fabric-api": GOOD_SHA})(url)

        c = FakeClient(files=[f("old.jar")])
        with self.assertRaisesRegex(PterodactylError, "fabric-exporter is not a Modrinth project"):
            self.run_sync(c, projects=("fabric-api", "fabric-exporter"), cat=fetch)
        self.assertEqual(c.calls, [])

    def test_other_http_errors_are_not_swallowed(self):
        def fetch(url):
            raise HttpError(503, "down", url)

        with self.assertRaises(HttpError):
            self.run_sync(FakeClient(files=[]), cat=fetch)

    def test_sha_mismatch_removes_file_and_fails_before_purge(self):
        c = FakeClient(files=[f("old.jar")], contents={"fabric-api-1.0.jar": b"tampered"})
        with self.assertRaisesRegex(PterodactylError, "sha512 mismatch"):
            self.run_sync(c)
        self.assertEqual(c.calls, [("pull_file", "fabric-api-1.0.jar"), ("delete_files", ("fabric-api-1.0.jar",))])
        # old.jar was never deleted

    def test_pull_failure_keeps_old_mods(self):
        c = FakeClient(files=[f("old.jar")])
        c.fail_pull = True
        with self.assertRaises(PterodactylError):
            self.run_sync(c)
        self.assertNotIn(("delete_files", ("old.jar",)), c.calls)

    def test_missing_mods_dir_is_created(self):
        c = FakeClient(files=None, contents={"fabric-api-1.0.jar": GOOD})
        self.run_sync(c)
        self.assertEqual(c.calls[0], ("create_folder", "/", "mods"))

    def test_same_name_wrong_size_is_replaced(self):
        c = FakeClient(files=[f("fabric-api-1.0.jar", size=1)], contents={"fabric-api-1.0.jar": GOOD})
        self.run_sync(c)
        self.assertEqual(c.names(), ["delete_files", "pull_file"])

    def test_check_mode_changes_nothing(self):
        c = FakeClient(files=[f("old.jar")])
        out = self.run_sync(c, check_mode=True)
        self.assertTrue(out["changed"])
        self.assertEqual(c.calls, [])

    def test_vanilla_has_no_mods(self):
        with self.assertRaisesRegex(PterodactylError, "does not support mods"):
            self.run_sync(FakeClient(files=[]), loader="vanilla")

    def test_non_jar_files_survive_purge(self):
        c = FakeClient(files=[f("fabric-api-1.0.jar"), f("notes.txt"), f("config.json")])
        out = self.run_sync(c)
        self.assertEqual(out["removed"], [])
