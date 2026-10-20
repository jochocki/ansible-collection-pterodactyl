import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils import servers as srv
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric",
            "version": "26.3", "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


class Find(unittest.TestCase):
    def test_external_id_beats_name(self):
        a, b = server(id=1, name="A", external_id="x"), server(id=2, name="B", external_id="y")
        self.assertEqual(srv.find_server([a, b], external_id="y", name="A")["id"], 2)

    def test_falls_back_to_name(self):
        a = server(id=1, name="A", external_id=None)
        self.assertEqual(srv.find_server([a], external_id="zzz", name="A")["id"], 1)

    def test_duplicate_names_refused(self):
        a, b = server(id=1, name="A", external_id=None), server(id=2, name="A", external_id=None)
        with self.assertRaisesRegex(PterodactylError, "2 servers are named"):
            srv.find_server([a, b], name="A")

    def test_none(self):
        self.assertIsNone(srv.find_server([], name="A"))


def bk(uuid, created, locked=False):
    return {"uuid": uuid, "created_at": created, "is_locked": locked, "is_successful": True, "completed_at": "x"}


class Backups(unittest.TestCase):
    def test_limit_zero_is_skipped(self):
        c = FakeClient()
        self.assertIn("skipped", srv.rotate_and_backup(c, "id", 0, sleep=no_sleep))
        self.assertEqual(c.names(), [])

    def test_oldest_by_created_at_not_list_order(self):
        c = FakeClient(backups=[bk("newer", "2026-02"), bk("oldest", "2026-01")])
        srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertEqual(c.calls[0], ("delete_backup", "oldest"))

    def test_locked_backups_are_skipped(self):
        c = FakeClient(backups=[bk("locked-old", "2026-01", True), bk("free", "2026-02")])
        srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertEqual(c.calls[0], ("delete_backup", "free"))

    def test_all_locked_fails_before_creating(self):
        c = FakeClient(backups=[bk("a", "1", True), bk("b", "2", True)])
        with self.assertRaisesRegex(PterodactylError, "locked"):
            srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertNotIn("create_backup", c.names())

    def test_over_the_limit_deletes_until_there_is_room(self):
        c = FakeClient(backups=[bk("c", "3"), bk("a", "1"), bk("b", "2")])
        srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertEqual(c.calls[:2], [("delete_backup", "a"), ("delete_backup", "b")])
        self.assertEqual(c.names()[-1], "create_backup")

    def test_over_the_limit_with_too_many_locked_fails_without_creating(self):
        c = FakeClient(backups=[bk("a", "1", True), bk("b", "2", True), bk("c", "3")])
        with self.assertRaisesRegex(PterodactylError, "locked"):
            srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertNotIn("create_backup", c.names())

    def test_failed_backups_do_not_count_against_the_limit(self):
        failed = dict(bk("bad", "1"), is_successful=False, completed_at="x")
        c = FakeClient(backups=[failed, bk("a", "2")])
        srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertEqual(c.names(), ["create_backup"])

    def test_room_available_deletes_nothing(self):
        c = FakeClient(backups=[bk("a", "1")])
        srv.rotate_and_backup(c, "id", 2, sleep=no_sleep)
        self.assertEqual(c.names(), ["create_backup"])


class Power(unittest.TestCase):
    def test_start_when_running_is_noop(self):
        c = FakeClient(state="running")
        self.assertFalse(srv.set_power(c, "id", "started", sleep=no_sleep))
        self.assertEqual(c.names(), [])

    def test_stop_when_offline_is_noop(self):
        self.assertFalse(srv.set_power(FakeClient(state="offline"), "id", "stopped", sleep=no_sleep))

    def test_stop_sends_signal(self):
        c = FakeClient(state="running")
        self.assertTrue(srv.set_power(c, "id", "stopped", sleep=no_sleep))
        self.assertEqual(c.calls, [("power", "stop")])

    def test_label(self):
        self.assertEqual(srv.power_label("starting"), "started")
        self.assertEqual(srv.power_label("offline"), "stopped")
        self.assertEqual(srv.power_label("stopping"), "stopped")


class Create(unittest.TestCase):
    def test_creates_with_java_25_for_year_release(self):
        c = FakeClient(servers=[])
        out = ops.ensure_minecraft_server(c, spec(limits={"memory": 3000, "backups": 2}), sleep=no_sleep)
        payload = c.calls[0][1]
        self.assertTrue(out["changed"])
        self.assertEqual(payload["docker_image"], "ghcr.io/pterodactyl/yolks:java_25")
        self.assertEqual(payload["egg"], 15)
        self.assertEqual(payload["external_id"], "tiny-animals")
        self.assertEqual(payload["environment"]["MC_VERSION"], "26.3")
        self.assertEqual(payload["allocation"], {"default": 77})
        self.assertEqual(payload["limits"]["memory"], 3000)

    def test_create_waits_for_install(self):
        c = FakeClient(servers=[])
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertGreaterEqual(c.installing, 2)  # polled until the fake reported done

    def test_check_mode_creates_nothing(self):
        c = FakeClient(servers=[])
        out = ops.ensure_minecraft_server(c, spec(), check_mode=True)
        self.assertTrue(out["changed"])
        self.assertEqual(c.calls, [])

    def test_unknown_node_fails(self):
        with self.assertRaisesRegex(PterodactylError, "node named 'nope'"):
            ops.ensure_minecraft_server(FakeClient(), spec(node="nope"))


class Converge(unittest.TestCase):
    def test_in_sync_changes_nothing(self):
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                              "environment": {"MC_VERSION": "26.3"}})
        c = FakeClient(servers=[s])
        out = ops.ensure_minecraft_server(c, spec(limits={"memory": 3000, "cpu": 300}), sleep=no_sleep)
        self.assertFalse(out["changed"])
        self.assertEqual(c.calls, [])

    def test_version_bump_order_of_operations(self):
        c = FakeClient(servers=[server()], state="running", backups=[bk("a", "1"), bk("b", "2")])
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        order = c.names()
        self.assertEqual(order, ["power", "delete_backup", "create_backup", "update_startup", "reinstall", "power"])
        self.assertEqual(c.calls[0], ("power", "stop"))
        self.assertEqual(c.calls[-1], ("power", "start"))
        self.assertEqual(out["previous_power"], "started")
        startup = c.calls[3][1]
        self.assertEqual(startup["image"], "ghcr.io/pterodactyl/yolks:java_25")
        self.assertEqual(startup["environment"]["MC_VERSION"], "26.3")
        self.assertEqual(startup["startup"], "java -jar {{SERVER_JARFILE}}")  # existing command kept

    def test_restore_power_false_leaves_server_stopped_and_reports_it(self):
        c = FakeClient(servers=[server()], state="running", backups=[])
        out = ops.ensure_minecraft_server(c, spec(), restore_power=False, sleep=no_sleep)
        self.assertNotIn(("power", "start"), c.calls)
        self.assertEqual((out["previous_power"], out["power_after"]), ("started", "stopped"))

    def test_restore_power_true_reports_started_after(self):
        c = FakeClient(servers=[server()], state="running", backups=[])
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual((out["previous_power"], out["power_after"]), ("started", "started"))

    def test_no_change_reports_the_real_power_state(self):
        # A no-op run must not tell the playbook the server was stopped.
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                              "environment": {"MC_VERSION": "26.3"}})
        for state, label in (("running", "started"), ("offline", "stopped")):
            out = ops.ensure_minecraft_server(FakeClient(servers=[s], state=state), spec(), sleep=no_sleep)
            self.assertFalse(out["changed"])
            self.assertEqual((out["previous_power"], out["power_after"]), (label, label))

    def test_check_mode_reports_real_power_state(self):
        c = FakeClient(servers=[server()], state="running")
        out = ops.ensure_minecraft_server(c, spec(), check_mode=True)
        self.assertEqual(out["previous_power"], "started")

    def test_stopped_server_stays_stopped(self):
        c = FakeClient(servers=[server()], state="offline", backups=[])
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertNotIn("power", c.names())
        self.assertEqual(out["previous_power"], "stopped")

    def test_backup_can_be_disabled(self):
        c = FakeClient(servers=[server()], state="offline")
        ops.ensure_minecraft_server(c, spec(), backup=False, sleep=no_sleep)
        self.assertNotIn("create_backup", c.names())

    def test_image_only_change_does_not_reinstall_or_stop(self):
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                              "environment": {"MC_VERSION": "26.3"}})
        c = FakeClient(servers=[s], state="running")
        ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.names(), ["update_startup"])

    def test_limits_patch_keeps_other_fields(self):
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x",
                              "environment": {"MC_VERSION": "26.3"}})
        c = FakeClient(servers=[s])
        ops.ensure_minecraft_server(c, spec(limits={"memory": 4000}), sleep=no_sleep)
        body = c.calls[0][1]
        self.assertEqual((body["memory"], body["cpu"], body["disk"]), (4000, 300, 500))
        self.assertEqual(body["feature_limits"]["backups"], 2)
        self.assertEqual(body["allocation"], 9)

    def test_adopts_unkeyed_server_by_name(self):
        s = server(external_id=None, container={"image": "ghcr.io/pterodactyl/yolks:java_25",
                                                "startup_command": "x", "environment": {"MC_VERSION": "26.3"}})
        c = FakeClient(servers=[s])
        out = ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)
        self.assertEqual(c.calls[0][0], "update_details")
        self.assertEqual(c.calls[0][1]["external_id"], "tiny-animals")
        self.assertTrue(out["changed"])

    def test_check_mode_makes_no_calls(self):
        c = FakeClient(servers=[server()], state="running")
        out = ops.ensure_minecraft_server(c, spec(limits={"memory": 9}), check_mode=True)
        self.assertTrue(out["changed"])
        self.assertEqual(c.calls, [])

    def test_wrong_egg_is_refused(self):
        c = FakeClient(servers=[server(egg=5)])
        with self.assertRaisesRegex(PterodactylError, "different egg"):
            ops.ensure_minecraft_server(c, spec(), sleep=no_sleep)


# -- converge_minecraft: server and mods together ---------------------------
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError  # noqa: E402
from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import (  # noqa: E402
    GOOD,
    GOOD_SHA,
    catalog,
    f,
)

IN_SYNC = {"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x", "environment": {"MC_VERSION": "26.3"}}
CATALOG = catalog({"fabric-api": GOOD_SHA})
JAR = {"fabric-api-1.0.jar": GOOD}


def converge(client, mods=("fabric-api",), fetch=CATALOG, **kw):
    mods = list(mods) if mods is not None else None
    return ops.converge_minecraft(client, spec(), mods=mods, fetch=fetch, sleep=no_sleep, **kw)


class ConvergeWithMods(unittest.TestCase):
    def test_mods_none_leaves_files_alone_and_restores_power_itself(self):
        c = FakeClient(servers=[server()], state="running", files=[f("hand-installed.jar")])
        converge(c, mods=None, unlisted="ignore")
        self.assertNotIn("pull_file", c.names())
        self.assertNotIn("delete_files", c.names())
        self.assertEqual(c.calls[-1], ("power", "start"))

    def test_version_bump_installs_mods_before_the_server_boots(self):
        c = FakeClient(servers=[server()], state="running", files=[f("old.jar")], contents=JAR)
        out = converge(c)
        self.assertEqual(c.names(), ["power", "create_backup", "update_startup", "reinstall",
                                     "pull_file", "delete_files", "power"])
        self.assertEqual((c.calls[0], c.calls[-1]), (("power", "stop"), ("power", "start")))
        self.assertEqual(out["mods"]["installed"], ["fabric-api-1.0.jar"])
        self.assertEqual((out["previous_power"], out["power_after"]), ("started", "started"))

    def test_unknown_mod_fails_before_the_server_is_touched(self):
        def fetch(url):
            raise HttpError(404, "nope", url)

        c = FakeClient(servers=[server()], state="running")
        with self.assertRaisesRegex(PterodactylError, "not a Modrinth project"):
            converge(c, fetch=fetch)
        self.assertEqual(c.calls, [])  # not stopped, backed up or reinstalled

    def test_vanilla_with_mods_is_refused_before_any_change(self):
        c = FakeClient(servers=[server()], state="running")
        with self.assertRaisesRegex(PterodactylError, "does not support mods"):
            ops.converge_minecraft(c, spec(loader="vanilla"), mods=["fabric-api"], fetch=CATALOG, sleep=no_sleep)
        self.assertEqual(c.calls, [])

    def test_mods_failing_after_a_version_change_leave_the_server_stopped(self):
        c = FakeClient(servers=[server()], state="running", files=[f("old.jar")])
        c.fail_pull = True
        with self.assertRaises(PterodactylError):
            converge(c)
        self.assertIn(("power", "stop"), c.calls)
        self.assertNotIn(("power", "start"), c.calls)
        self.assertNotIn(("delete_files", ("old.jar",)), c.calls)

    def test_running_server_restarts_when_only_its_mods_changed(self):
        c = FakeClient(servers=[server(container=IN_SYNC)], state="running", files=[f("old.jar")], contents=JAR)
        out = converge(c)
        self.assertEqual(c.names(), ["pull_file", "delete_files", "power"])
        self.assertEqual(c.calls[-1], ("power", "restart"))
        self.assertTrue(out["changed"])

    def test_running_server_with_unchanged_mods_is_left_alone(self):
        c = FakeClient(servers=[server(container=IN_SYNC)], state="running", files=[f("fabric-api-1.0.jar")])
        out = converge(c)
        self.assertEqual(c.calls, [])
        self.assertFalse(out["changed"])

    def test_stopped_server_stays_stopped_after_a_mod_change(self):
        c = FakeClient(servers=[server(container=IN_SYNC)], state="offline", files=[f("old.jar")], contents=JAR)
        converge(c)
        self.assertNotIn("power", c.names())

    def test_new_server_gets_its_mods_and_stays_stopped(self):
        c = FakeClient(servers=[], files=[], contents=JAR)
        out = converge(c)
        self.assertEqual(c.names(), ["create_server", "pull_file"])
        self.assertEqual(out["mods"]["installed"], ["fabric-api-1.0.jar"])
        self.assertEqual(out["power_after"], "stopped")

    def test_check_mode_for_a_new_server_makes_no_calls(self):
        c = FakeClient(servers=[])
        out = converge(c, check_mode=True)
        self.assertEqual(c.calls, [])
        self.assertIsNone(out["mods"])
        self.assertTrue(out["changed"])

    def test_check_mode_reports_mod_changes_without_making_them(self):
        c = FakeClient(servers=[server(container=IN_SYNC)], state="running", files=[f("old.jar")])
        out = converge(c, check_mode=True)
        self.assertEqual(c.calls, [])
        self.assertTrue(out["changed"])
        self.assertEqual(out["mods"]["removed"], ["old.jar"])

    def test_empty_list_removes_every_jar(self):
        c = FakeClient(servers=[server(container=IN_SYNC)], state="offline", files=[f("a.jar"), f("b.jar"), f("x.txt")])
        out = converge(c, mods=[])
        self.assertEqual(out["mods"]["removed"], ["a.jar", "b.jar"])
