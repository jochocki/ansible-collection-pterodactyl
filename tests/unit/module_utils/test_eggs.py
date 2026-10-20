import copy
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import eggs


def panel_egg():
    """An egg as the API returns it."""
    return {
        "id": 15, "nest": 1, "name": "Fabric", "author": "a@example.com", "updated_at": "2024-07-29T17:00:00+00:00",
        "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar {{SERVER_JARFILE}}",
        "docker_image": "img:21",
        "docker_images": {"Java 21": "img:21", "Java 17": "img:17"},
        "script": {"container": "openjdk:11-jdk-slim", "entry": "bash", "install": "#!/bin/bash\r\necho hi\r\n"},
        "variables": [
            {"env_variable": "SERVER_JARFILE", "default_value": "fabric-server-launch.jar", "rules": "required|string",
             "user_viewable": True, "user_editable": True},
            {"env_variable": "MC_VERSION", "default_value": "latest", "rules": "required|string",
             "user_viewable": True, "user_editable": True},
        ],
    }


def source_egg():
    """The same egg as an exported file, identical to panel_egg()."""
    return {
        "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar {{SERVER_JARFILE}}",
        "docker_images": {"Java 21": "img:21", "Java 17": "img:17"},
        "scripts": {"installation": {"container": "openjdk:11-jdk-slim", "entrypoint": "bash",
                                     "script": "#!/bin/bash\necho hi"}},
        "variables": [
            {"env_variable": "SERVER_JARFILE", "default_value": "fabric-server-launch.jar", "rules": "required|string",
             "user_viewable": True, "user_editable": True},
            {"env_variable": "MC_VERSION", "default_value": "latest", "rules": "required|string",
             "user_viewable": True, "user_editable": True},
        ],
    }


def fields(found):
    return {d["field"] for d in found}


class Drift(unittest.TestCase):
    def test_identical_eggs_have_no_drift_even_with_different_line_endings(self):
        self.assertEqual(eggs.drift(panel_egg(), source_egg()), [])

    def test_the_install_container(self):
        s = source_egg()
        s["scripts"]["installation"]["container"] = "eclipse-temurin:21-jdk-jammy"
        found = eggs.drift(panel_egg(), s)
        self.assertEqual(found, [{"field": "install_container", "panel": "openjdk:11-jdk-slim",
                                  "source": "eclipse-temurin:21-jdk-jammy"}])

    def test_the_install_script_reports_sizes_and_keeps_the_text_out_of_the_summary(self):
        s = source_egg()
        s["scripts"]["installation"]["script"] = "#!/bin/bash\necho hi\necho more"
        (d,) = eggs.drift(panel_egg(), s)
        self.assertEqual((d["field"], d["panel"], d["source"]), ("install_script", "2 lines", "3 lines"))
        self.assertIn("echo more", d["source_text"])

    def test_trailing_whitespace_is_not_drift(self):
        s = source_egg()
        s["scripts"]["installation"]["script"] = "#!/bin/bash  \necho hi  \n\n"
        self.assertEqual(eggs.drift(panel_egg(), s), [])

    def test_startup_and_entrypoint(self):
        s = source_egg()
        s["startup"] = "java -jar x"
        s["scripts"]["installation"]["entrypoint"] = "ash"
        self.assertEqual(fields(eggs.drift(panel_egg(), s)), {"startup", "install_entrypoint"})

    def test_runtime_images_report_which_side_has_what(self):
        s = source_egg()
        s["docker_images"] = {"Java 21": "img:21", "Java 25": "img:25"}
        (d,) = eggs.drift(panel_egg(), s)
        self.assertEqual((d["field"], d["panel_only"], d["source_only"]), ("runtime_images", ["img:17"], ["img:25"]))

    def test_image_display_names_are_not_drift(self):
        s = source_egg()
        s["docker_images"] = {"Java twenty-one": "img:21", "Java seventeen": "img:17"}
        self.assertEqual(eggs.drift(panel_egg(), s), [])

    def test_a_variables_default_and_rules(self):
        s = source_egg()
        s["variables"][0]["default_value"] = "server.jar"
        s["variables"][1]["rules"] = "required|string|between:3,15"
        self.assertEqual(fields(eggs.drift(panel_egg(), s)),
                         {"variable SERVER_JARFILE default_value", "variable MC_VERSION rules"})

    def test_a_variable_added_or_dropped(self):
        s = source_egg()
        s["variables"].append({"env_variable": "NEW", "default_value": "x", "rules": "r"})
        del s["variables"][1]
        found = {d["field"]: d for d in eggs.drift(panel_egg(), s)}
        self.assertEqual(found["variable NEW"]["source"], "present")
        self.assertEqual(found["variable MC_VERSION"]["panel"], "present")

    def test_visibility_flags_compare_as_booleans(self):
        s = source_egg()
        p = panel_egg()
        p["variables"][0]["user_editable"] = 1
        self.assertEqual(eggs.drift(p, s), [])
        s["variables"][0]["user_editable"] = False
        self.assertEqual(fields(eggs.drift(p, s)), {"variable SERVER_JARFILE user_editable"})

    def test_an_egg_with_no_variables_or_script(self):
        bare = {"id": 1, "name": "x", "variables": []}
        self.assertEqual(eggs.drift(bare, {"variables": []}), [])


class Config(unittest.TestCase):
    """What Wings and the panel read live, so an upload changes every server at once."""

    def pair(self):
        p, s = panel_egg(), source_egg()
        p["config"] = {"files": {"server.properties": {"parser": "properties", "find": {"server-ip": "0.0.0.0"}}},
                       "startup": {"done": ")! For help"}, "logs": {"location": "logs/latest.log"}, "stop": "stop"}
        s["config"] = {"files": '{"server.properties": {"parser": "properties", "find": {"server-ip": "0.0.0.0"}}}',
                       "startup": '{"done": ")! For help"}', "logs": '{"location": "logs/latest.log"}', "stop": "stop"}
        return p, s

    def test_the_api_object_and_the_export_text_compare_equal(self):
        self.assertEqual(eggs.drift(*self.pair()), [])

    def test_a_local_customisation_is_found(self):
        # your egg forces enable-query=true; the maintained one does not
        p, s = self.pair()
        p["config"]["files"]["server.properties"]["find"]["enable-query"] = "true"
        (d,) = eggs.drift(p, s)
        self.assertEqual(d["field"], "config_files")
        self.assertIn("enable-query", d["panel"]["server.properties"]["find"])
        self.assertNotIn("enable-query", d["source"]["server.properties"]["find"])

    def test_stop_command_and_done_text(self):
        p, s = self.pair()
        s["config"]["stop"] = "end"
        s["config"]["startup"] = '{"done": "Done ("}'
        self.assertEqual(fields(eggs.drift(p, s)), {"config_stop", "config_startup"})

    def test_denylist_from_either_place_and_features_only_when_returned(self):
        p, s = self.pair()
        s["file_denylist"] = ["a.txt"]
        self.assertEqual(eggs.drift(p, s), [])  # the API did not say, so no claim
        p["config"]["file_denylist"] = []
        self.assertEqual(fields(eggs.drift(p, s)), {"file_denylist"})
        p2, s2 = self.pair()
        s2["features"] = ["eula"]
        self.assertEqual(eggs.drift(p2, s2), [])
        p2["features"] = []
        self.assertEqual(fields(eggs.drift(p2, s2)), {"features"})

    def test_an_egg_with_no_config_matches_a_source_with_none(self):
        self.assertEqual(eggs.drift(panel_egg(), source_egg()), [])


class Info(unittest.TestCase):
    def test_install_and_runtime_images(self):
        info = eggs.egg_info(panel_egg())
        self.assertEqual(info["install_image"], "openjdk:11-jdk-slim")
        self.assertEqual(info["runtime_images"], ["img:17", "img:21"])
        self.assertEqual((info["id"], info["name"], info["nest"]), (15, "Fabric", 1))

    def test_an_egg_without_an_install_container(self):
        e = panel_egg()
        e["script"] = {"container": None}
        self.assertIsNone(eggs.egg_info(e)["install_image"])

    def test_the_single_runtime_image_of_an_old_egg_counts(self):
        e = {"id": 2, "name": "old", "docker_image": "only:1", "script": {}}
        self.assertEqual(eggs.egg_info(e)["runtime_images"], ["only:1"])


class Url(unittest.TestCase):
    def test_raw_url(self):
        self.assertEqual(eggs.source_url("pterodactyl/game-eggs", "main", "minecraft/java/fabric/egg-fabric.json"),
                         "https://raw.githubusercontent.com/pterodactyl/game-eggs/main/minecraft/java/fabric/egg-fabric.json")

    def test_a_leading_slash_and_odd_refs_are_handled(self):
        self.assertEqual(eggs.source_url("o/r", "feature/x", "/a b/egg.json"),
                         "https://raw.githubusercontent.com/o/r/feature%2Fx/a%20b/egg.json")
