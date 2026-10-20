import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import minecraft as mc


class JavaTable(unittest.TestCase):
    def test_java_by_version(self):
        cases = {
            "1.12.2": 8, "1.16.5": 8, "1.17": 17, "1.20.4": 17, "1.20.5": 21,
            "1.21": 21, "1.21.11": 21, "26.1": 25, "26.3": 25,
        }
        for version, java in cases.items():
            self.assertEqual(mc.java_major(version), java, version)

    def test_year_numbered_beats_lexical_order(self):
        # "26.3" < "1.21" as strings is False but "9" < "26" shows why strings are unsafe
        self.assertGreater(mc.parse_version("26.3"), mc.parse_version("1.21.11"))
        self.assertGreater(mc.parse_version("1.21.11"), mc.parse_version("1.21.2"))

    def test_image_name(self):
        self.assertEqual(mc.java_image("26.3"), "ghcr.io/pterodactyl/yolks:java_25")

    def test_rejects_non_versions(self):
        for bad in ("latest", "1", "1.21-pre1", "", "1.2.3.4"):
            with self.assertRaises(ValueError):
                mc.parse_version(bad)


class VersionCheck(unittest.TestCase):
    known = mc.release_ids({"versions": [
        {"id": "1.20", "type": "release"}, {"id": "1.21.4", "type": "release"},
        {"id": "26.3", "type": "release"}, {"id": "1.21.5-pre1", "type": "snapshot"},
    ]})

    def test_known(self):
        mc.check_version("1.20", self.known)

    def test_yaml_float_is_caught(self):
        # YAML reads 1.20 as the float 1.2
        with self.assertRaisesRegex(ValueError, "Quote versions"):
            mc.check_version("1.2", self.known)

    def test_snapshots_are_not_releases(self):
        self.assertNotIn("1.21.5-pre1", self.known)


class LoaderTable(unittest.TestCase):
    def test_every_loader_has_what_the_modules_need(self):
        for name, row in mc.LOADERS.items():
            for key in ("egg", "version_var", "startup", "environment", "mod_loaders"):
                self.assertIn(key, row, name)

    def test_paper_accepts_plugin_loaders(self):
        self.assertEqual(mc.LOADERS["paper"]["mod_loaders"], ("paper", "spigot", "bukkit"))

    def test_vanilla_has_no_mod_support(self):
        self.assertEqual(mc.LOADERS["vanilla"]["mod_loaders"], ())
