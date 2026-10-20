"""A reinstall is judged by its effect: the jar the server starts must have been rewritten."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server
from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import GOOD, GOOD_SHA, catalog

LAUNCHER = "fabric-server-launch.jar"


def root(stamp="old"):
    return [{"name": LAUNCHER, "size": 1, "is_file": True, "modified_at": stamp},
            {"name": "server.jar", "size": 1, "is_file": True, "modified_at": stamp},
            {"name": "world", "size": 0, "is_file": False}]


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "26.3",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


def in_sync():
    return server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                             "environment": {"MC_VERSION": "26.3", "SERVER_JARFILE": LAUNCHER}})


class Flow(unittest.TestCase):
    def test_a_version_bump_deletes_nothing_in_the_servers_root(self):
        c = FakeClient(servers=[server()], state="running", root=root())
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.names(), ["power", "create_backup", "update_startup", "reinstall", "power"])
        self.assertNotIn("delete_files", c.names())

    def test_the_jar_is_rewritten_when_the_install_ran(self):
        c = FakeClient(servers=[server()], state="offline", root=root())
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotEqual(next(f for f in c.root if f["name"] == LAUNCHER)["modified_at"], "old")

    def test_a_server_whose_jar_is_missing_is_repaired_by_an_install_that_recreates_it(self):
        # The state `test` was left in: the launcher is gone.
        c = FakeClient(servers=[server()], state="offline", root=[{"name": "world", "size": 0, "is_file": False}])
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertIn(LAUNCHER, [f["name"] for f in c.root])


class InstallDidNotRun(unittest.TestCase):
    """A failed image pull leaves the panel saying the install is fine."""

    def run_it(self, c, **kw):
        c.rewrites = []
        return ops.ensure_minecraft_server(c, spec(**kw), sleep=no_sleep)

    def test_an_untouched_jar_fails_the_run_and_names_wings_log(self):
        c = FakeClient(servers=[server()], state="running", root=root())
        with self.assertRaisesRegex(PterodactylError, "fabric-server-launch.jar was not rewritten.*"
                                    "/var/log/pterodactyl/install/9e72677e-dba3-4ece-924c-32339960619b.log"):
            self.run_it(c)

    def test_the_server_is_left_stopped(self):
        c = FakeClient(servers=[server()], state="running", root=root())
        with self.assertRaises(PterodactylError):
            self.run_it(c)
        self.assertNotIn(("power", "start"), c.calls)

    def test_a_missing_jar_that_stays_missing_fails_too(self):
        c = FakeClient(servers=[server()], state="offline", root=[])
        with self.assertRaisesRegex(PterodactylError, "was not rewritten"):
            self.run_it(c)

    def test_the_message_does_not_point_at_a_panel_log_viewer(self):
        c = FakeClient(servers=[server()], state="offline", root=root())
        with self.assertRaises(PterodactylError) as ctx:
            self.run_it(c)
        self.assertNotIn("in the panel", str(ctx.exception))

    def test_nothing_to_check_without_a_jar_variable(self):
        s = server()
        del s["container"]["environment"]["SERVER_JARFILE"]
        c = FakeClient(servers=[s], state="offline", root=root())
        self.run_it(c)  # cannot tell, so it does not guess

    def test_vanilla_checks_its_own_jar(self):
        s = server(egg=5, container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                                     "environment": {"VANILLA_VERSION": "1.21", "SERVER_JARFILE": "server.jar"}})
        for rewrites, ok in (([], False), (["server.jar"], True)):
            c = FakeClient(servers=[s], state="offline", root=root())
            c.eggs = lambda: [{"id": 5, "name": "Vanilla Minecraft"}]
            c.rewrites = rewrites
            if ok:
                ops.ensure_minecraft_server(c, spec(loader="vanilla", version="1.21.4"), sleep=no_sleep)
            else:
                with self.assertRaisesRegex(PterodactylError, "server.jar was not rewritten"):
                    ops.ensure_minecraft_server(c, spec(loader="vanilla", version="1.21.4"), sleep=no_sleep)


class Forced(unittest.TestCase):
    def test_reinstall_true_runs_the_whole_sequence_for_a_matching_server(self):
        c = FakeClient(servers=[in_sync()], state="running", root=root())
        out = ops.ensure_minecraft_server(c, spec(reinstall=True), sleep=no_sleep)
        self.assertEqual(c.names(), ["power", "create_backup", "update_startup", "reinstall", "power"])
        self.assertTrue(out["changed"])
        self.assertIn("(forced)", " ".join(out["actions"]))

    def test_without_it_a_matching_server_is_left_alone(self):
        c = FakeClient(servers=[in_sync()], state="running", root=root())
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual((c.calls, out["changed"]), ([], False))

    def test_check_mode_makes_no_calls(self):
        c = FakeClient(servers=[in_sync()], state="running", root=root())
        out = ops.ensure_minecraft_server(c, spec(reinstall=True), check_mode=True)
        self.assertEqual(c.calls, [])
        self.assertTrue(out["changed"])

    def test_mods_go_in_after_the_reinstall_and_before_the_server_boots(self):
        c = FakeClient(servers=[in_sync()], state="running", root=root(), files=[], contents={"fabric-api-1.0.jar": GOOD})
        ops.converge_minecraft(c, spec(reinstall=True), mods=["fabric-api"], fetch=catalog({"fabric-api": GOOD_SHA}),
                               sleep=no_sleep)
        names = c.names()
        self.assertLess(names.index("reinstall"), names.index("pull_file"))
        self.assertEqual(c.calls[-1], ("power", "start"))


class FailedStatus(unittest.TestCase):
    """When the panel does notice the failure, say where the log is."""

    def test_a_reinstall_failed_status_names_the_log(self):
        c = FakeClient(servers=[server()], state="running", root=root())
        c.install_status = "reinstall_failed"
        with self.assertRaisesRegex(PterodactylError, "reinstall failed.*reinstall_failed.*/var/log/pterodactyl/install/"):
            ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotIn(("power", "start"), c.calls)
