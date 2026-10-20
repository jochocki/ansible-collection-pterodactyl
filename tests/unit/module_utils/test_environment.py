"""Egg variables: the egg names them and sets their defaults; the module only sets the version."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server

OLD_JAR = "fabric-server-launch.jar"


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "26.3",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


def root(*names):
    return [{"name": n, "size": 1, "is_file": True, "modified_at": "old"} for n in names]


class Update(unittest.TestCase):
    def test_only_the_version_changes_and_every_other_value_is_kept(self):
        s = server()
        s["container"]["environment"].update({"SERVER_JARFILE": "my-launch.jar", "FABRIC_VERSION": "1.0.1",
                                              "LOADER_VERSION": "0.16.10"})
        c = FakeClient(servers=[s], state="offline", root=root("my-launch.jar"))
        c.rewrites = ["my-launch.jar"]
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        env = next(call[1] for call in c.calls if call[0] == "update_startup")["environment"]
        self.assertEqual(env, {"SERVER_JARFILE": "my-launch.jar", "MC_VERSION": "26.3",
                               "FABRIC_VERSION": "1.0.1", "LOADER_VERSION": "0.16.10"})

    def test_the_maintained_egg_is_not_pushed_back_to_the_old_launcher_name(self):
        # After re-importing the maintained egg the default is server.jar. A server that already
        # has that value must keep it, whatever an older version of this module hardcoded.
        s = server()
        s["container"]["environment"]["SERVER_JARFILE"] = "server.jar"
        c = FakeClient(servers=[s], state="offline", root=root("server.jar"))
        c.egg_defaults["SERVER_JARFILE"] = "server.jar"
        c.rewrites = ["server.jar"]
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        env = next(call[1] for call in c.calls if call[0] == "update_startup")["environment"]
        self.assertEqual(env["SERVER_JARFILE"], "server.jar")

    def test_a_variable_the_egg_gained_gets_its_default_and_one_it_dropped_is_not_sent(self):
        s = server()
        s["container"]["environment"]["OLD_ONLY"] = "x"
        c = FakeClient(servers=[s], state="offline", root=root(OLD_JAR))
        c.egg_defaults["NEW_VARIABLE"] = "dflt"
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        env = next(call[1] for call in c.calls if call[0] == "update_startup")["environment"]
        self.assertEqual(env["NEW_VARIABLE"], "dflt")
        self.assertNotIn("OLD_ONLY", env)


class Create(unittest.TestCase):
    def test_a_new_server_gets_the_eggs_own_defaults(self):
        c = FakeClient(servers=[])
        c.egg_defaults.update({"SERVER_JARFILE": "server.jar", "BUILD_NUMBER": "latest"})
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        env = c.calls[0][1]["environment"]
        self.assertEqual(env, {"SERVER_JARFILE": "server.jar", "MC_VERSION": "26.3", "FABRIC_VERSION": "latest",
                               "LOADER_VERSION": "latest", "BUILD_NUMBER": "latest"})

    def test_extra_variables_override_the_eggs_defaults(self):
        c = FakeClient(servers=[])
        ops.ensure_minecraft_server(c, spec(environment={"SERVER_JARFILE": "other.jar"}), sleep=no_sleep)
        self.assertEqual(c.calls[0][1]["environment"]["SERVER_JARFILE"], "other.jar")

    def test_the_startup_command_comes_from_the_egg_when_it_has_one(self):
        c = FakeClient(servers=[])
        eggs = c.eggs()
        eggs[0]["startup"] = "java -jar {{SERVER_JARFILE}} nogui"
        c.eggs = lambda: eggs
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.calls[0][1]["startup"], "java -jar {{SERVER_JARFILE}} nogui")


class ExplicitEnvironment(unittest.TestCase):
    def migrate(self, rewrites, **extra):
        # A server on the old egg's launcher name, being moved to the maintained egg's server.jar.
        c = FakeClient(servers=[server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                                                   "environment": {"MC_VERSION": "26.3", "SERVER_JARFILE": OLD_JAR}})],
                       state="running", root=root(OLD_JAR, "server.jar"))
        c.egg_defaults["SERVER_JARFILE"] = "server.jar"
        c.rewrites = rewrites
        out = ops.ensure_minecraft_server(c, spec(environment={"SERVER_JARFILE": "server.jar"}, **extra), sleep=no_sleep)
        return c, out

    def test_changing_a_variable_updates_the_startup_without_a_reinstall(self):
        c, out = self.migrate([])
        self.assertEqual(c.names(), ["update_startup"])
        self.assertEqual(c.calls[0][1]["environment"]["SERVER_JARFILE"], "server.jar")
        self.assertTrue(out["changed"])

    def test_the_same_value_is_a_noop(self):
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                              "environment": {"MC_VERSION": "26.3", "SERVER_JARFILE": "server.jar"}})
        c = FakeClient(servers=[s], state="running")
        out = ops.ensure_minecraft_server(c, spec(environment={"SERVER_JARFILE": "server.jar"}), sleep=no_sleep)
        self.assertEqual((c.calls, out["changed"]), ([], False))

    def test_the_install_check_looks_for_the_new_jar_name(self):
        c, _ = self.migrate(["server.jar"], reinstall=True)
        self.assertEqual(c.names(), ["power", "create_backup", "update_startup", "reinstall", "power"])

    def test_and_fails_if_only_the_old_name_was_rewritten(self):
        with self.assertRaisesRegex(PterodactylError, "server.jar was not rewritten"):
            self.migrate([OLD_JAR], reinstall=True)

    def test_the_diff_shows_the_variable(self):
        _, out = self.migrate([])
        self.assertEqual(out["diff"]["before"]["startup"]["environment.SERVER_JARFILE"], OLD_JAR)
        self.assertEqual(out["diff"]["after"]["startup"]["environment.SERVER_JARFILE"], "server.jar")
