"""A version change on a server whose mods are not managed checks the jars it will leave behind."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils import modrinth, mods
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server

OLD = b"fabric-api-for-1.21"
SAME = b"xaeros-for-1.21.10"
STRANGER = b"hand-made"


def version(number, games, loaders=("fabric",)):
    return {"version_number": number, "game_versions": list(games), "loaders": list(loaders)}


def modrinth_knows(by_bytes=None):
    """A POST function answering for the jars whose bytes it was told about."""
    known = {modrinth.sha512_hex(b): v for b, v in (by_bytes or {}).items()}

    def post(url, body):
        assert url.endswith("/version_files") and body["algorithm"] == "sha512"
        return {h: known[h] for h in body["hashes"] if h in known}
    return post


def client(**contents):
    c = FakeClient(servers=[server()], state="offline", files=[{"name": n, "size": len(b), "is_file": True} for n, b in contents.items()],
                   contents=contents)
    return c


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "1.21.10",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


class Audit(unittest.TestCase):
    def audit(self, c, post, game="1.21.10", loader="fabric", **kw):
        return mods.audit_unmanaged(c, "id", game, loader, post, **kw)

    def test_compatible_incompatible_and_unknown(self):
        c = client(**{"fabric-api.jar": OLD, "xaeros.jar": SAME, "mine.jar": STRANGER})
        post = modrinth_knows({OLD: version("0.102.0+1.21", ["1.21"]), SAME: version("1.0", ["1.21.10", "1.21.9"])})
        report = {r["file"]: r for r in self.audit(c, post)}
        self.assertEqual(report["xaeros.jar"]["status"], "compatible")
        self.assertEqual((report["fabric-api.jar"]["status"], report["fabric-api.jar"]["detail"]),
                         ("incompatible", "built for Minecraft 1.21"))
        self.assertEqual(report["mine.jar"]["status"], "unknown")

    def test_the_right_game_version_for_the_wrong_loader_is_incompatible(self):
        c = client(**{"a.jar": OLD})
        report = self.audit(c, modrinth_knows({OLD: version("1", ["1.21.10"], loaders=["forge"])}))
        self.assertEqual(report[0]["status"], "incompatible")

    def test_a_long_list_of_versions_is_shortened(self):
        c = client(**{"a.jar": OLD})
        report = self.audit(c, modrinth_knows({OLD: version("1", ["1.20", "1.20.1", "1.20.2", "1.20.3"])}))
        self.assertEqual(report[0]["detail"], "built for Minecraft 1.20, 1.20.1, 1.20.2 and later")

    def test_a_modrinth_failure_makes_everything_unknown_not_an_error(self):
        def post(url, body):
            raise HttpError(503, "down", url)
        report = self.audit(client(**{"a.jar": OLD}), post)
        self.assertEqual([r["status"] for r in report], ["unknown"])

    def test_nothing_to_check(self):
        self.assertIsNone(self.audit(client(), modrinth_knows()))                     # no jars
        self.assertIsNone(self.audit(client(**{"a.jar": OLD}), modrinth_knows(), loader="vanilla"))
        self.assertIsNone(self.audit(client(**{"a%d.jar" % i: OLD + bytes([i]) for i in range(5)}), modrinth_knows(), limit=3))

    def test_non_jars_are_ignored_and_nothing_is_modified(self):
        c = client(**{"a.jar": OLD, "readme.txt": b"x"})
        report = self.audit(c, modrinth_knows())
        self.assertEqual([r["file"] for r in report], ["a.jar"])
        self.assertEqual(c.calls, [])


class Flow(unittest.TestCase):
    def post(self):
        return modrinth_knows({OLD: version("0.102.0+1.21", ["1.21"])})

    def bump(self, **kw):
        c = client(**{"fabric-api.jar": OLD})
        c.state = "offline"
        return c, ops.converge_minecraft(c, spec(), post=self.post(), sleep=no_sleep, **kw)

    def test_a_version_bump_with_unmanaged_mods_reports_what_will_not_load(self):
        c, out = self.bump()
        self.assertEqual(out["unmanaged_mods"][0]["status"], "incompatible")
        self.assertNotIn("delete_files", c.names())  # reported, never touched

    def test_it_is_reported_in_check_mode_too_before_anything_changes(self):
        c, out = self.bump(check_mode=True)
        self.assertEqual(out["unmanaged_mods"][0]["status"], "incompatible")
        self.assertEqual(c.calls, [])

    def test_no_audit_without_a_version_change(self):
        c = client(**{"fabric-api.jar": OLD})
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                              "environment": {"MC_VERSION": "1.21.10", "SERVER_JARFILE": "fabric-server-launch.jar"}})
        c._servers = [s]
        out = ops.converge_minecraft(c, spec(), post=self.post(), sleep=no_sleep)
        self.assertNotIn("unmanaged_mods", out)

    def test_no_audit_when_mods_are_managed(self):
        from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import GOOD, GOOD_SHA, catalog
        c = client(**{"fabric-api.jar": OLD})
        c.contents["fabric-api-1.0.jar"] = GOOD
        out = ops.converge_minecraft(c, spec(version="26.3"), mods=["fabric-api"], fetch=catalog({"fabric-api": GOOD_SHA}),
                                     post=self.post(), sleep=no_sleep)
        self.assertNotIn("unmanaged_mods", out)

    def test_no_audit_without_a_post_function(self):
        c = client(**{"fabric-api.jar": OLD})
        self.assertNotIn("unmanaged_mods", ops.converge_minecraft(c, spec(), sleep=no_sleep))

    def test_a_new_server_has_nothing_to_audit(self):
        out = ops.converge_minecraft(FakeClient(servers=[]), spec(), post=self.post(), sleep=no_sleep)
        self.assertNotIn("unmanaged_mods", out)
