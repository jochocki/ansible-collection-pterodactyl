"""A server that has mods but no mods list is ambiguous, so the module refuses by default."""
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft_ops as ops
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.tests.unit.fakes import FakeClient, no_sleep, server
from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_audit import modrinth_knows, version
from ansible_collections.jochocki.pterodactyl.tests.unit.module_utils.test_mods import GOOD, GOOD_SHA, catalog

OLD = b"fabric-api-for-1.21"


def spec(**over):
    base = {"name": "Tiny Animals", "external_id": "tiny-animals", "loader": "fabric", "version": "1.21.10",
            "node": "wings01", "owner": 1, "limits": {}}
    base.update(over)
    return base


def jars(*names):
    return [{"name": n, "size": 1, "is_file": True} for n in names]


def client(*names, **kw):
    contents = {n: OLD + n.encode() for n in names}
    return FakeClient(servers=[server()], state="running", files=jars(*names), contents=contents, **kw)


def run(c, unlisted="fail", mods=None, **kw):
    return ops.converge_minecraft(c, spec(**kw.pop("spec", {})), mods=mods, post=kw.pop("post", None),
                                  unlisted=unlisted, fetch=kw.pop("fetch", None), sleep=no_sleep, **kw)


class Fail(unittest.TestCase):
    def test_jars_with_no_list_fail_before_anything_changes(self):
        c = client("fabric-api.jar", "xaeros.jar")
        with self.assertRaisesRegex(PterodactylError, "Tiny Animals: /mods holds 2 jar\\(s\\) \\(fabric-api.jar, xaeros.jar\\) "
                                                      "but no mods list is set"):
            run(c)
        self.assertEqual(c.calls, [])  # the server was not stopped, backed up or reinstalled

    def test_it_is_the_default(self):
        c = client("a.jar")
        with self.assertRaises(PterodactylError):
            ops.converge_minecraft(c, spec(), sleep=no_sleep)

    def test_the_message_says_which_jars_will_not_load_on_a_version_change(self):
        c = client("fabric-api.jar", "xaeros.jar")
        post = modrinth_knows({OLD + b"fabric-api.jar": version("0.102.0+1.21", ["1.21"]),
                               OLD + b"xaeros.jar": version("1", ["1.21.10"])})
        with self.assertRaises(PterodactylError) as ctx:
            run(c, post=post)
        text = str(ctx.exception)
        self.assertIn("version is changing to 1.21.10", text)
        self.assertIn("fabric-api.jar (built for Minecraft 1.21)", text)
        self.assertNotIn("xaeros.jar (", text)  # a compatible jar is not blamed

    def test_it_names_both_ways_out(self):
        with self.assertRaisesRegex(PterodactylError, "Set mods to the list.*unlisted_mods to warn or ignore"):
            run(client("a.jar"))

    def test_a_long_list_is_shortened(self):
        with self.assertRaisesRegex(PterodactylError, "holds 9 jar.*and 3 more"):
            run(client(*["m%d.jar" % i for i in range(9)]))

    def test_check_mode_fails_too(self):
        with self.assertRaises(PterodactylError):
            run(client("a.jar"), check_mode=True)

    def test_without_a_version_change_it_still_fails(self):
        s = server(container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                              "environment": {"MC_VERSION": "1.21.10", "SERVER_JARFILE": "fabric-server-launch.jar"}})
        c = client("a.jar")
        c._servers = [s]
        with self.assertRaisesRegex(PterodactylError, "holds 1 jar"):
            run(c)


class Passes(unittest.TestCase):
    def test_no_jars(self):
        run(client(), unlisted="fail")

    def test_a_directory_that_does_not_exist(self):
        c = FakeClient(servers=[server()], state="offline", files=None)
        run(c)

    def test_only_jars_count(self):
        run(FakeClient(servers=[server()], state="offline", files=jars("readme.txt", "config.json")))

    def test_a_new_server_has_nothing_to_complain_about(self):
        run(FakeClient(servers=[]))

    def test_vanilla_has_no_mods_to_find(self):
        s = server(egg=5, container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                                     "environment": {"VANILLA_VERSION": "1.21"}})
        c = FakeClient(servers=[s], state="offline", files=jars("a.jar"))
        c.eggs = lambda: [{"id": 5, "nest": 1, "name": "Vanilla Minecraft"}]
        run(c, spec={"loader": "vanilla", "version": "1.21.4"})

    def test_a_list_means_it_is_managed_even_when_empty(self):
        for listed in ([], ["fabric-api"]):
            c = client("old.jar")
            c.contents["fabric-api-1.0.jar"] = GOOD
            run(c, mods=listed, fetch=catalog({"fabric-api": GOOD_SHA}), spec={"version": "26.3"})


class Policies(unittest.TestCase):
    def test_warn_goes_ahead_and_audits_a_version_change(self):
        c = client("fabric-api.jar")
        post = modrinth_knows({OLD + b"fabric-api.jar": version("0.102.0+1.21", ["1.21"])})
        out = run(c, unlisted="warn", post=post)
        self.assertEqual(out["unmanaged_mods"][0]["status"], "incompatible")
        self.assertIn("reinstall", c.names())  # it went ahead

    def test_ignore_goes_ahead_without_a_word(self):
        c = client("fabric-api.jar")
        out = run(c, unlisted="ignore", post=modrinth_knows())
        self.assertNotIn("unmanaged_mods", out)
        self.assertIn("reinstall", c.names())

    def test_ignore_does_not_even_look(self):
        c = client("a.jar")
        run(c, unlisted="ignore")
        # only the reinstall check reads the server's root, nothing lists /mods
        self.assertNotIn("/mods", c.listed)


class Paper(unittest.TestCase):
    """Paper keeps its plugins in /plugins, not /mods."""

    def paper(self, *names):
        s = server(egg=3, container={"image": "ghcr.io/pterodactyl/yolks:java_21", "startup_command": "x",
                                     "environment": {"MINECRAFT_VERSION": "1.21", "SERVER_JARFILE": "server.jar"}})
        c = FakeClient(servers=[s], state="offline", files=jars(*names))
        return c

    def test_unlisted_plugins_are_found_in_plugins(self):
        c = self.paper("essentials.jar")
        with self.assertRaisesRegex(PterodactylError, "/plugins holds 1 jar"):
            run(c, spec={"loader": "paper", "version": "1.21"})
        self.assertIn("/plugins", c.listed)
        self.assertNotIn("/mods", c.listed)

    def test_a_plugin_list_installs_into_plugins(self):
        c = self.paper()
        c.rewrites = ["server.jar"]  # what a Paper install writes
        c.contents["essentials-1.0.jar"] = GOOD
        out = ops.converge_minecraft(c, spec(loader="paper", version="26.3"), mods=["essentials"],
                                     fetch=_paper_catalog(), sleep=no_sleep)
        self.assertEqual(c.pulled_to, ["/plugins"])
        self.assertEqual(out["mods"]["installed"], ["essentials-1.0.jar"])


def _paper_catalog():
    def fetch(url):
        return [{"version_number": "1.0", "version_type": "release", "date_published": "2026-01-01",
                 "game_versions": ["26.3"], "loaders": ["paper"],
                 "files": [{"filename": "essentials-1.0.jar", "url": "https://cdn/e", "size": len(GOOD), "primary": True,
                            "hashes": {"sha512": GOOD_SHA}}]}]
    return fetch
