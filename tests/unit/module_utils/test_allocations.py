"""Allocation management: the game port and additional ports on the Build Configuration tab."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils import servers as srv
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server

IN_SYNC = {"image": "ghcr.io/pterodactyl/yolks:java_25", "startup_command": "x", "environment": {"MC_VERSION": "26.3"}}


def plan(c, **kw):
    return srv.plan_allocations(c.node_allocs, c.server_allocations(27), 9, **kw)


class Plan(unittest.TestCase):
    def test_moving_the_primary_adds_it_and_keeps_the_old_one(self):
        out = plan(FakeClient(), port=25566)
        self.assertEqual((out["allocation"], out["add"], out["remove"]), (77, [77], []))
        self.assertEqual(out["changes"], {"port": 25566})

    def test_listing_additional_ports_adds_them(self):
        out = plan(FakeClient(), additional_ports=[25566, 25567])
        self.assertEqual((out["allocation"], sorted(out["add"]), out["remove"]), (9, [77, 78], []))
        self.assertEqual(out["changes"], {"added_ports": [25566, 25567]})

    def test_empty_list_releases_every_extra_but_never_the_primary(self):
        c = FakeClient()
        c.own = {9, 77, 78}
        out = plan(c, additional_ports=[])
        self.assertEqual(sorted(out["remove"]), [77, 78])
        self.assertNotIn(9, out["remove"])
        self.assertEqual(out["changes"], {"removed_ports": [25566, 25567]})

    def test_moving_the_primary_releases_the_old_port_when_additional_ports_is_managed(self):
        out = plan(FakeClient(), port=25566, additional_ports=[])
        self.assertEqual((out["allocation"], out["add"], out["remove"]), (77, [77], [9]))
        self.assertEqual(out["changes"], {"port": 25566, "removed_ports": [25565]})

    def test_already_there_is_a_noop(self):
        c = FakeClient()
        self.assertEqual(plan(c, port=25565, additional_ports=[])["changes"], {})
        c.own = {9, 77}
        self.assertEqual(plan(c, port=25565, additional_ports=[25566])["changes"], {})

    def test_unset_options_leave_everything_alone(self):
        c = FakeClient()
        c.own = {9, 77}
        out = plan(c)
        self.assertEqual((out["allocation"], out["add"], out["remove"], out["changes"]), (9, [], [], {}))

    def test_port_held_by_another_server_points_at_the_nodes_page(self):
        with self.assertRaisesRegex(PterodactylError, "no free allocation for port 25568.*Nodes, Allocation"):
            plan(FakeClient(), port=25568)

    def test_port_that_does_not_exist(self):
        with self.assertRaisesRegex(PterodactylError, "no free allocation for port 30000"):
            plan(FakeClient(), additional_ports=[30000])

    def test_a_port_on_several_ips_needs_an_ip(self):
        with self.assertRaisesRegex(PterodactylError, "several IPs.*10.0.0.1:25569.*10.0.0.2:25569"):
            plan(FakeClient(), port=25569)
        self.assertEqual(plan(FakeClient(), port=25569, ip="10.0.0.2")["allocation"], 81)

    def test_primary_cannot_also_be_additional(self):
        with self.assertRaisesRegex(PterodactylError, "primary port"):
            plan(FakeClient(), port=25566, additional_ports=[25566])

    def test_duplicates_are_collapsed(self):
        self.assertEqual(plan(FakeClient(), additional_ports=[25566, 25566])["add"], [77])


class Build(unittest.TestCase):
    def test_one_patch_carries_primary_and_add_and_remove(self):
        c = FakeClient()
        changes, actions = srv.ensure_build(c, server(), {"port": 25566, "additional_ports": [25567]})
        body = c.calls[0][1]
        self.assertEqual(c.names(), ["update_build"])
        self.assertEqual((body["allocation"], body["add_allocations"]), (77, [77, 78]))
        self.assertEqual(body["remove_allocations"], [9])
        self.assertEqual(changes, {"port": 25566, "added_ports": [25567], "removed_ports": [25565]})
        self.assertIn("port=25566", actions[0])

    def test_limits_and_ports_share_the_patch(self):
        c = FakeClient()
        srv.ensure_build(c, server(), {"memory": 4000, "port": 25566})
        body = c.calls[0][1]
        self.assertEqual((body["memory"], body["allocation"], body["cpu"]), (4000, 77, 300))

    def test_no_allocation_keys_when_the_ports_are_untouched(self):
        c = FakeClient()
        srv.ensure_build(c, server(), {"memory": 4000})
        body = c.calls[0][1]
        self.assertNotIn("add_allocations", body)
        self.assertNotIn("remove_allocations", body)
        self.assertEqual(c.reads, [])  # no node lookups for a limits-only change

    def test_a_noop_port_makes_no_patch(self):
        c = FakeClient()
        self.assertEqual(srv.ensure_build(c, server(), {"port": 25565}), ({}, []))
        self.assertEqual(c.calls, [])

    def test_check_mode_plans_without_patching(self):
        c = FakeClient()
        changes, _ = srv.ensure_build(c, server(), {"port": 25566}, check_mode=True)
        self.assertEqual((changes, c.calls), ({"port": 25566}, []))

    def test_a_change_the_panel_silently_ignored_is_an_error(self):
        c = FakeClient()
        c.ignore_allocation_changes = True
        with self.assertRaisesRegex(PterodactylError, "panel ignored part of the allocation change"):
            srv.ensure_build(c, server(), {"additional_ports": [25566]})

    def test_the_verification_passes_when_the_panel_applied_it(self):
        c = FakeClient()
        srv.ensure_build(c, server(), {"additional_ports": [25566]})
        self.assertEqual(c.own, {9, 77})


class Create(unittest.TestCase):
    def spec(self, **over):
        base = {"name": "F", "external_id": "f", "owner": 1, "egg": "Fabric", "image": "img", "startup": "run",
                "node": "wings01"}
        base.update(over)
        return base

    def create(self, **over):
        c = FakeClient()
        srv.create_server(c, self.spec(**over), sleep=no_sleep)
        return c.calls[0][1]["allocation"]

    def test_no_ports_takes_the_first_free_allocation(self):
        self.assertEqual(self.create(), {"default": 77})

    def test_port_chooses_the_allocation(self):
        self.assertEqual(self.create(port=25567), {"default": 78})

    def test_additional_ports_ride_along(self):
        self.assertEqual(self.create(port=25566, additional_ports=[25567]), {"default": 77, "additional": [78]})

    def test_additional_ports_without_a_primary_is_refused(self):
        with self.assertRaisesRegex(PterodactylError, "needs port"):
            self.create(additional_ports=[25567])

    def test_a_taken_port_fails_before_anything_is_created(self):
        c = FakeClient()
        with self.assertRaises(PterodactylError):
            srv.create_server(c, self.spec(port=25568), sleep=no_sleep)
        self.assertEqual(c.calls, [])


class Minecraft(unittest.TestCase):
    def spec(self, **limits):
        return {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "26.3",
                "node": "wings01", "owner": 1, "limits": limits}

    def test_port_picks_the_allocation_of_a_new_server(self):
        c = FakeClient(servers=[])
        ops.ensure_minecraft_server(c, self.spec(port=25567), sleep=no_sleep)
        self.assertEqual(c.calls[0][1]["allocation"], {"default": 78})

    def test_port_moves_an_existing_server_without_touching_its_version(self):
        c = FakeClient(servers=[server(container=dict(IN_SYNC))], state="running")
        out = ops.ensure_minecraft_server(c, self.spec(port=25566), sleep=no_sleep)
        self.assertEqual(c.names(), ["update_build"])
        self.assertEqual(c.calls[0][1]["allocation"], 77)
        self.assertTrue(out["changed"])

    def test_no_port_leaves_the_allocations_alone(self):
        c = FakeClient(servers=[server(container=dict(IN_SYNC))], state="running")
        out = ops.ensure_minecraft_server(c, self.spec(memory=3000), sleep=no_sleep)
        self.assertEqual((c.calls, c.reads, out["changed"]), ([], [], False))
