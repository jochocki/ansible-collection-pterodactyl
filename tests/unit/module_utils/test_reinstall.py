"""A Fabric reinstall keeps the old vanilla server.jar, so the leftovers go first and must come back."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server

INSTALLED = ("server.jar", "fabric-server-launch.jar", "fabric-server-launcher.properties", "fabric-installer.jar")


def root(*extra):
    files = [{"name": n, "size": 1, "is_file": True} for n in INSTALLED + extra]
    return files + [{"name": "world", "size": 0, "is_file": False}, {"name": "mods", "size": 0, "is_file": False}]


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "26.3",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


def in_sync():
    return server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                             "environment": {"MC_VERSION": "26.3", "SERVER_JARFILE": "fabric-server-launch.jar"}})


class Fabric(unittest.TestCase):
    def bump(self, **kw):
        c = FakeClient(servers=[server()], state="running", files=root("server.properties"), **kw)
        c.recreate = list(INSTALLED)
        return c

    def test_stale_installer_files_are_removed_before_the_reinstall_and_world_data_is_not(self):
        c = self.bump()
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.names(), ["power", "create_backup", "delete_files", "update_startup", "reinstall", "power"])
        removed = c.calls[2]
        self.assertEqual(removed[0], "delete_files")
        self.assertEqual(sorted(removed[1]), sorted(INSTALLED))
        for kept in ("world", "mods", "server.properties"):
            self.assertNotIn(kept, removed[1])

    def test_the_backup_is_taken_before_anything_is_deleted(self):
        c = self.bump()
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertLess(c.names().index("create_backup"), c.names().index("delete_files"))

    def test_a_reinstall_that_does_not_bring_the_jar_back_fails_and_leaves_the_server_stopped(self):
        c = self.bump()
        c.recreate = []  # the installer "finished" but wrote nothing
        with self.assertRaisesRegex(PterodactylError, "did not recreate fabric-server-launch.jar, server.jar"):
            ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotIn(("power", "start"), c.calls)

    def test_only_server_jar_and_the_launcher_must_come_back(self):
        c = self.bump()
        c.recreate = ["server.jar", "fabric-server-launch.jar"]  # no properties or installer: not required
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)

    def test_no_stale_files_means_no_delete(self):
        c = FakeClient(servers=[server()], state="offline", files=[{"name": "world", "size": 0, "is_file": False}])
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotIn("delete_files", c.names())

    def test_a_custom_launcher_name_is_taken_from_the_servers_environment(self):
        s = server()
        s["container"]["environment"]["SERVER_JARFILE"] = "custom-launch.jar"
        c = FakeClient(servers=[s], state="offline", files=[{"name": "custom-launch.jar", "size": 1, "is_file": True}])
        c.recreate = ["custom-launch.jar"]
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.calls[[n for n, *_ in c.calls].index("delete_files")][1], ("custom-launch.jar",))

    def test_check_mode_reports_the_files_without_touching_them(self):
        c = self.bump()
        out = ops.ensure_minecraft_server(c, spec(), check_mode=True)
        self.assertEqual(c.calls, [])
        self.assertIn("remove server.jar", " ".join(out["actions"]))
        self.assertEqual(sorted(out["diff"]["before"]["reinstall"]["installer_files"]), sorted(INSTALLED))


class Forced(unittest.TestCase):
    def test_reinstall_true_repairs_a_server_whose_version_already_matches(self):
        c = FakeClient(servers=[in_sync()], state="running", files=root())
        c.recreate = list(INSTALLED)
        out = ops.ensure_minecraft_server(c, spec(reinstall=True), sleep=no_sleep)
        self.assertEqual(c.names(), ["power", "create_backup", "delete_files", "update_startup", "reinstall", "power"])
        self.assertTrue(out["changed"])
        self.assertIn("(forced)", " ".join(out["actions"]))

    def test_without_it_a_matching_server_is_left_alone(self):
        c = FakeClient(servers=[in_sync()], state="running", files=root())
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual((c.calls, out["changed"]), ([], False))

    def test_mods_are_installed_before_the_repaired_server_boots(self):
        from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import GOOD, GOOD_SHA, catalog
        c = FakeClient(servers=[in_sync()], state="running", files=root(), contents={"fabric-api-1.0.jar": GOOD})
        c.recreate = list(INSTALLED)
        ops.converge_minecraft(c, spec(reinstall=True), mods=["fabric-api"], fetch=catalog({"fabric-api": GOOD_SHA}),
                               sleep=no_sleep)
        names = c.names()
        self.assertLess(names.index("reinstall"), names.index("pull_file"))
        self.assertEqual(c.calls[-1], ("power", "start"))


class OtherLoaders(unittest.TestCase):
    def test_vanilla_and_paper_reinstalls_delete_nothing(self):
        for loader, env in (("vanilla", "VANILLA_VERSION"), ("paper", "MINECRAFT_VERSION")):
            s = server(egg=5 if loader == "vanilla" else 3,
                       container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                                  "environment": {env: "1.21"}})
            c = FakeClient(servers=[s], state="offline", files=root())
            c.eggs = lambda: [{"id": 15, "name": "Fabric"}, {"id": 5, "name": "Vanilla Minecraft"}, {"id": 3, "name": "Paper"}]
            ops.ensure_minecraft_server(c, spec(loader=loader, version="1.21.4"), sleep=no_sleep)
            self.assertNotIn("delete_files", c.names(), loader)
            self.assertIn("reinstall", c.names(), loader)


class FailedInstall(unittest.TestCase):
    def test_a_failed_reinstall_names_the_log_and_leaves_the_server_stopped(self):
        c = FakeClient(servers=[server()], state="running", files=root())
        c.install_status = "reinstall_failed"
        with self.assertRaisesRegex(PterodactylError,
                                    "reinstall failed.*reinstall_failed.*/var/log/pterodactyl/install/9e72677e-dba3-4ece-924c-32339960619b.log"):
            ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotIn(("power", "start"), c.calls)

    def test_it_is_caught_even_for_loaders_with_nothing_to_recreate(self):
        s = server(egg=5, container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                                     "environment": {"VANILLA_VERSION": "1.21"}})
        c = FakeClient(servers=[s], state="offline")
        c.eggs = lambda: [{"id": 5, "name": "Vanilla Minecraft"}]
        c.install_status = "reinstall_failed"
        with self.assertRaisesRegex(PterodactylError, "reinstall failed"):
            ops.ensure_minecraft_server(c, spec(loader="vanilla", version="1.21.4"), sleep=no_sleep)

    def test_a_server_that_finished_installing_is_fine(self):
        c = FakeClient(servers=[server()], state="offline")
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
