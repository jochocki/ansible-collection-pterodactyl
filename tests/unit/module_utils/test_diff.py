"""--diff: every change is reported as a before and an after."""
import json
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils import mods
from ansible_collections.jochocki.pterodactyl.plugins.module_utils import servers as srv
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import diff_result
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server
from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import GOOD, GOOD_SHA, catalog, f

IN_SYNC = {"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x", "environment": {"MC_VERSION": "26.3"}}


class Generic(unittest.TestCase):
    def test_details(self):
        d = srv.new_diff()
        srv.ensure_details(FakeClient(), server(), {"name": "Renamed", "external_id": "tiny-animals"}, diff=d)
        self.assertEqual(d, {"before": {"details": {"name": "Tiny Animals"}}, "after": {"details": {"name": "Renamed"}}})

    def test_build_limits(self):
        d = srv.new_diff()
        srv.ensure_build(FakeClient(), server(), {"memory": 4000, "backups": 3, "cpu": 300}, diff=d)
        self.assertEqual(d["before"]["build"], {"memory": 3000, "backups": 2})
        self.assertEqual(d["after"]["build"], {"memory": 4000, "backups": 3})

    def test_build_ports(self):
        d = srv.new_diff()
        srv.ensure_build(FakeClient(), server(), {"port": 25566, "additional_ports": [25567]}, diff=d)
        self.assertEqual(d["before"]["ports"], {"port": 25565, "additional_ports": []})
        self.assertEqual(d["after"]["ports"], {"port": 25566, "additional_ports": [25567]})

    def test_moving_the_primary_without_managing_extras_shows_the_old_port_as_an_extra(self):
        d = srv.new_diff()
        srv.ensure_build(FakeClient(), server(), {"port": 25566}, diff=d)
        self.assertEqual(d["after"]["ports"], {"port": 25566, "additional_ports": [25565]})

    def test_releasing_a_port(self):
        c = FakeClient()
        c.own = {9, 77}
        d = srv.new_diff()
        srv.ensure_build(c, server(), {"additional_ports": []}, diff=d)
        self.assertEqual(d["before"]["ports"]["additional_ports"], [25566])
        self.assertEqual(d["after"]["ports"]["additional_ports"], [])

    def test_startup(self):
        d = srv.new_diff()
        srv.ensure_startup(FakeClient(), server(), image="ghcr.io/pterodactyl/yolks:java_25",
                           environment={"MC_VERSION": "26.3", "NEW": "1"}, diff=d)
        self.assertEqual(d["before"]["startup"], {"docker_image": "ghcr.io/pterodactyl/yolks:java_21",
                                                  "environment.MC_VERSION": "1.21.11", "environment.NEW": None})
        self.assertEqual(d["after"]["startup"]["environment.MC_VERSION"], "26.3")

    def test_nothing_changed_nothing_recorded(self):
        d = srv.new_diff()
        srv.ensure_build(FakeClient(), server(), {"memory": 3000, "port": 25565}, diff=d)
        srv.ensure_details(FakeClient(), server(), {"name": "Tiny Animals"}, diff=d)
        srv.ensure_startup(FakeClient(), server(), environment={"MC_VERSION": "1.21.11"}, diff=d)
        self.assertEqual(d, srv.new_diff())

    def test_check_mode_still_records(self):
        d = srv.new_diff()
        c = FakeClient()
        srv.ensure_build(c, server(), {"memory": 1}, check_mode=True, diff=d)
        self.assertEqual((c.calls, d["after"]["build"]), ([], {"memory": 1}))

    def test_no_collector_is_fine(self):
        srv.ensure_build(FakeClient(), server(), {"memory": 1})


class Mods(unittest.TestCase):
    def test_before_and_after_file_lists(self):
        c = FakeClient(files=[f("old.jar"), f("keep.jar"), f("notes.txt")], contents={"fabric-api-1.0.jar": GOOD})
        d = srv.new_diff()
        wanted = mods.resolve_mods("26.3", "fabric", ["fabric-api"], catalog({"fabric-api": GOOD_SHA}))
        mods.apply_mods(c, "id", wanted, diff=d)
        self.assertEqual(d["before"]["mods"]["files"], ["keep.jar", "old.jar"])
        self.assertEqual(d["after"]["mods"]["files"], ["fabric-api-1.0.jar"])  # purge removed both

    def test_purge_false_keeps_unlisted_jars_in_the_after(self):
        c = FakeClient(files=[f("old.jar")], contents={"fabric-api-1.0.jar": GOOD})
        d = srv.new_diff()
        wanted = mods.resolve_mods("26.3", "fabric", ["fabric-api"], catalog({"fabric-api": GOOD_SHA}))
        mods.apply_mods(c, "id", wanted, purge=False, diff=d)
        self.assertEqual(d["after"]["mods"]["files"], ["fabric-api-1.0.jar", "old.jar"])

    def test_unchanged_mods_record_nothing(self):
        d = srv.new_diff()
        wanted = mods.resolve_mods("26.3", "fabric", ["fabric-api"], catalog({"fabric-api": GOOD_SHA}))
        mods.apply_mods(FakeClient(files=[f("fabric-api-1.0.jar")]), "id", wanted, diff=d)
        self.assertEqual(d, srv.new_diff())


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "26.3",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


class Minecraft(unittest.TestCase):
    def test_version_bump_shows_the_version_and_the_image(self):
        c = FakeClient(servers=[server()], state="offline")
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(out["diff"]["before"]["startup"],
                         {"docker_image": "ghcr.io/pterodactyl/yolks:java_21", "MC_VERSION": "1.21.11"})
        self.assertEqual(out["diff"]["after"]["startup"],
                         {"docker_image": "ghcr.io/pterodactyl/yolks:java_25", "MC_VERSION": "26.3"})

    def test_in_sync_has_an_empty_diff(self):
        s = server(container=dict(IN_SYNC))
        out = ops.ensure_minecraft_server(FakeClient(servers=[s], state="running"), spec(limits={"memory": 3000}), sleep=no_sleep)
        self.assertEqual(out["diff"], srv.new_diff())
        self.assertFalse(out["changed"])

    def test_create_describes_the_new_server(self):
        out = ops.ensure_minecraft_server(FakeClient(servers=[]), spec(limits={"memory": 2000}), check_mode=True)
        self.assertEqual(out["diff"]["before"], {})
        self.assertEqual(out["diff"]["after"]["server"]["version"], "26.3")
        self.assertEqual(out["diff"]["after"]["server"]["limits"], {"memory": 2000})

    def test_converge_merges_server_and_mods(self):
        s = server(container=dict(IN_SYNC), limits=dict(server()["limits"], memory=1000))
        c = FakeClient(servers=[s], state="offline", files=[f("old.jar")], contents={"fabric-api-1.0.jar": GOOD})
        out = ops.converge_minecraft(c, spec(limits={"memory": 3000}), mods=["fabric-api"],
                                     fetch=catalog({"fabric-api": GOOD_SHA}), sleep=no_sleep)
        self.assertEqual(out["diff"]["before"], {"build": {"memory": 1000}, "mods": {"files": ["old.jar"]}})
        self.assertEqual(out["diff"]["after"], {"build": {"memory": 3000}, "mods": {"files": ["fabric-api-1.0.jar"]}})


class Rendering(unittest.TestCase):
    def test_renders_line_oriented_json_with_headers(self):
        out = diff_result("test", {"before": {"build": {"memory": 1}}, "after": {"build": {"memory": 2}}})["diff"]
        self.assertEqual(json.loads(out["before"]), {"build": {"memory": 1}})
        self.assertIn('"memory": 2', out["after"])
        self.assertIn("test", out["before_header"])
        self.assertTrue(out["before"].endswith("\n"))
        self.assertEqual(out["before"].count("\n"), 5)  # one line per key, so the diff is readable

    def test_an_empty_diff_adds_nothing(self):
        self.assertEqual(diff_result("test", srv.new_diff()), {})
        self.assertEqual(diff_result("test", None), {})
