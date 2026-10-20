import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import modrinth


def v(number, kind="release", date="2026-01-01", games=("1.21",), loaders=("fabric",), files=None):
    return {
        "version_number": number, "version_type": kind, "date_published": date,
        "game_versions": list(games), "loaders": list(loaders),
        "files": files or [{"filename": "m-%s.jar" % number, "url": "https://cdn/m-%s.jar" % number,
                            "size": 10, "primary": True, "hashes": {"sha512": "ab" * 64}}],
    }


class Pick(unittest.TestCase):
    def test_newest_release_wins(self):
        versions = [v("1", date="2026-01-01"), v("3", date="2026-03-01"), v("2", date="2026-02-01")]
        self.assertEqual(modrinth.pick_version("m", versions, "1.21", ["fabric"])["version_number"], "3")

    def test_release_beats_newer_beta(self):
        versions = [v("1"), v("2-beta", kind="beta", date="2027-01-01")]
        self.assertEqual(modrinth.pick_version("m", versions, "1.21", ["fabric"])["version_number"], "1")

    def test_beta_used_when_no_release(self):
        self.assertEqual(modrinth.pick_version("m", [v("2-beta", kind="beta")], "1.21", ["fabric"])["version_number"], "2-beta")

    def test_wrong_game_version_or_loader_is_refused(self):
        with self.assertRaisesRegex(modrinth.ModrinthError, "no version for Minecraft 1.22"):
            modrinth.pick_version("m", [v("1")], "1.22", ["fabric"])
        with self.assertRaises(modrinth.ModrinthError):
            modrinth.pick_version("m", [v("1")], "1.21", ["paper"])

    def test_any_accepted_loader_matches(self):
        got = modrinth.pick_version("m", [v("1", loaders=("bukkit",))], "1.21", ["paper", "spigot", "bukkit"])
        self.assertEqual(got["version_number"], "1")


class Resolve(unittest.TestCase):
    def test_query_is_encoded_and_file_returned(self):
        seen = []

        def fetch(url):
            seen.append(url)
            return [v("3")]

        got = modrinth.resolve("fabric-api", "1.21", ["fabric"], fetch)
        self.assertIn("/project/fabric-api/version?", seen[0])
        self.assertIn("loaders=%5B%22fabric%22%5D", seen[0])
        self.assertIn("game_versions=%5B%221.21%22%5D", seen[0])
        self.assertEqual(got["filename"], "m-3.jar")
        self.assertEqual(got["sha512"], "ab" * 64)

    def test_primary_file_preferred(self):
        files = [
            {"filename": "sources.jar", "url": "u1", "primary": False, "hashes": {"sha512": "a"}},
            {"filename": "main.jar", "url": "u2", "primary": True, "hashes": {"sha512": "b"}},
        ]
        got = modrinth.resolve("m", "1.21", ["fabric"], lambda url: [v("1", files=files)])
        self.assertEqual(got["filename"], "main.jar")

    def test_missing_hash_is_refused(self):
        files = [{"filename": "x.jar", "url": "u", "primary": True, "hashes": {}}]
        with self.assertRaisesRegex(modrinth.ModrinthError, "sha512"):
            modrinth.resolve("m", "1.21", ["fabric"], lambda url: [v("1", files=files)])
