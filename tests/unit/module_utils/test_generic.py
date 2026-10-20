"""The generic layer: one group of functions per tab of the panel's server page."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import servers as srv
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server


class Lookup(unittest.TestCase):
    def test_by_name_identifier_or_external_id(self):
        c = FakeClient(servers=[server()])
        for ref in ("Tiny Animals", "650fdf18", "tiny-animals"):
            self.assertEqual(srv.get_server(c, ref)["id"], 27)

    def test_missing_names_the_reference(self):
        with self.assertRaisesRegex(PterodactylError, "no server matches 'nope'"):
            srv.get_server(FakeClient(servers=[server()]), "nope")


class Details(unittest.TestCase):
    def test_rename_found_by_external_id_keeps_the_other_fields(self):
        c = FakeClient()
        s = server(description="old text")
        actions = srv.ensure_details(c, s, {"name": "Renamed", "external_id": "tiny-animals", "description": None, "owner": None})
        self.assertEqual(c.calls, [("update_details", {"name": "Renamed", "user": 1, "external_id": "tiny-animals", "description": "old text"})])
        self.assertEqual(actions, ["update details: name=Renamed"])

    def test_owner_change(self):
        c = FakeClient()
        srv.ensure_details(c, server(), {"owner": 5})
        self.assertEqual(c.calls[0][1]["user"], 5)

    def test_in_sync_and_unset_options_are_noops(self):
        c = FakeClient()
        self.assertEqual(srv.ensure_details(c, server(), {"name": "Tiny Animals", "external_id": None, "description": None, "owner": 1}), [])
        self.assertEqual(c.calls, [])

    def test_empty_description_matches_null(self):
        self.assertEqual(srv.details_diff(server(description=None), {"description": ""}), {})

    def test_check_mode(self):
        c = FakeClient()
        actions = srv.ensure_details(c, server(), {"external_id": "new"}, check_mode=True)
        self.assertEqual((c.calls, len(actions)), ([], 1))


class Build(unittest.TestCase):
    def test_only_given_limits_change_and_the_rest_is_kept(self):
        c = FakeClient()
        changes, actions = srv.ensure_build(c, server(), {"memory": 4000, "cpu": None, "databases": 2})
        body = c.calls[0][1]
        self.assertEqual(changes, {"memory": 4000, "databases": 2})
        self.assertEqual((body["memory"], body["cpu"], body["disk"], body["io"]), (4000, 300, 500, 500))
        self.assertEqual(body["feature_limits"], {"databases": 2, "allocations": 0, "backups": 2})
        self.assertEqual(body["allocation"], 9)
        self.assertEqual(actions, ["update build: databases=2, memory=4000"])

    def test_zero_is_a_value_not_unset(self):
        changes, unused_result = srv.ensure_build(FakeClient(), server(), {"cpu": 0})
        self.assertEqual(changes, {"cpu": 0})

    def test_in_sync_is_a_noop(self):
        c = FakeClient()
        self.assertEqual(srv.ensure_build(c, server(), {"memory": 3000, "backups": 2}), ({}, []))
        self.assertEqual(c.calls, [])

    def test_check_mode_reports_without_calling(self):
        c = FakeClient()
        changes, unused_result = srv.ensure_build(c, server(), {"memory": 1}, check_mode=True)
        self.assertEqual((changes, c.calls), ({"memory": 1}, []))


class Startup(unittest.TestCase):
    def test_diff_lists_only_what_differs(self):
        s = server()
        self.assertEqual(srv.startup_diff(s, image="ghcr.io/pterodactyl/yolks:java_21", environment={"MC_VERSION": "1.21.11"}), {})
        self.assertEqual(
            srv.startup_diff(s, image="ghcr.io/pterodactyl/yolks:java_25", startup="java -jar x",
                             environment={"MC_VERSION": "26.3", "NEW": "1"}),
            {"image": "ghcr.io/pterodactyl/yolks:java_25", "startup": "java -jar x",
             "environment": {"MC_VERSION": "26.3", "NEW": "1"}})

    def test_update_fills_unset_fields_from_the_server(self):
        c = FakeClient()
        srv.ensure_startup(c, server(), environment={"MC_VERSION": "26.3"})
        body = c.calls[0][1]
        self.assertEqual(body["startup"], "java -jar {{SERVER_JARFILE}}")
        self.assertEqual(body["image"], "ghcr.io/pterodactyl/yolks:java_21")
        self.assertEqual((body["egg"], body["skip_scripts"]), (15, False))
        self.assertEqual(c.names(), ["update_startup"])

    def test_reinstall_waits_for_the_install(self):
        c = FakeClient()
        changes, actions = srv.ensure_startup(c, server(), image="x", reinstall=True, sleep=no_sleep)
        self.assertEqual(c.names(), ["update_startup", "reinstall"])
        self.assertGreaterEqual(c.installing, 2)
        self.assertEqual(actions[-1], "reinstall")

    def test_no_change_means_no_reinstall(self):
        c = FakeClient()
        self.assertEqual(srv.ensure_startup(c, server(), environment={"MC_VERSION": "1.21.11"}, reinstall=True), ({}, []))
        self.assertEqual(c.calls, [])

    def test_check_mode(self):
        c = FakeClient()
        changes, actions = srv.ensure_startup(c, server(), image="x", reinstall=True, check_mode=True)
        self.assertEqual((bool(changes), c.calls, actions[-1]), (True, [], "reinstall"))


class Create(unittest.TestCase):
    def spec(self, **over):
        base = {"name": "Factorio", "external_id": "factorio", "owner": 1, "egg": "Fabric", "image": "img",
                "startup": "run", "environment": {"A": "1"}, "node": "wings01"}
        base.update(over)
        return base

    def test_defaults_and_waits_for_install(self):
        c = FakeClient()
        created = srv.create_server(c, self.spec(), sleep=no_sleep)
        body = c.calls[0][1]
        self.assertEqual(body["limits"], {"memory": 1024, "swap": 0, "disk": 0, "io": 500, "cpu": 0})
        self.assertEqual(body["feature_limits"], {"databases": 0, "allocations": 0, "backups": 0})
        self.assertEqual((body["egg"], body["allocation"], body["start_on_completion"]), (15, {"default": 77}, False))
        self.assertEqual(created["identifier"], "newident1")
        self.assertGreaterEqual(c.installing, 2)

    def test_given_limits_win(self):
        c = FakeClient()
        srv.create_server(c, self.spec(limits={"memory": 2000, "cpu": 200}, feature_limits={"backups": 3}), sleep=no_sleep)
        body = c.calls[0][1]
        self.assertEqual((body["limits"]["memory"], body["limits"]["cpu"], body["feature_limits"]["backups"]), (2000, 200, 3))

    def test_unknown_egg_or_node_is_refused_before_creating(self):
        for over, msg in (({"egg": "Nope"}, "egg named 'Nope'"), ({"node": "nope"}, "node named 'nope'")):
            c = FakeClient()
            with self.assertRaisesRegex(PterodactylError, msg):
                srv.create_server(c, self.spec(**over), sleep=no_sleep)
            self.assertEqual(c.calls, [])
