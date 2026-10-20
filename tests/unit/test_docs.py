"""The module documentation is YAML inside a Python string, so nothing else notices when it breaks."""
import glob
import os
import re
import unittest

import yaml

MODULES = sorted(p for p in glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "modules", "*.py"))
                 if not p.endswith("__init__.py"))


def block(source, name):
    match = re.search(r'^%s = r"""(.*?)"""' % name, source, re.S | re.M)
    return match.group(1) if match else None


class Docs(unittest.TestCase):
    def test_there_are_modules_to_check(self):
        self.assertGreaterEqual(len(MODULES), 6)

    def test_every_module_documents_itself_in_valid_yaml(self):
        for path in MODULES:
            source = open(path).read()
            for name in ("DOCUMENTATION", "EXAMPLES", "RETURN"):
                text = block(source, name)
                self.assertIsNotNone(text, "%s has no %s" % (os.path.basename(path), name))
                try:
                    parsed = yaml.safe_load(text)
                except yaml.YAMLError as exc:
                    self.fail("%s %s is not valid YAML: %s" % (os.path.basename(path), name, exc))
                self.assertTrue(parsed, "%s %s is empty" % (os.path.basename(path), name))

    def test_documented_options_are_the_ones_the_module_accepts(self):
        # Every option in DOCUMENTATION must be in the argument spec, and the other way round,
        # apart from the connection options that come from the shared fragment.
        shared = {"panel_url", "api_key", "validate_certs"}
        for path in MODULES:
            source = open(path).read()
            documented = set((yaml.safe_load(block(source, "DOCUMENTATION")).get("options") or {}))
            accepted = set(re.findall(r"^\s{8}(\w+)=dict\(", source, re.M))
            name = os.path.basename(path)
            self.assertEqual(documented, accepted, "%s: documented %s, accepted %s" % (
                name, sorted(documented - accepted), sorted(accepted - documented)))
            self.assertFalse(documented & shared, name)
