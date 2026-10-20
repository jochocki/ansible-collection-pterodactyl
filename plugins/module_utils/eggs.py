# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Compare an egg on the panel with the exported file it came from (or should match)."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ansible.module_utils.six.moves.urllib.parse import quote

RAW = "https://raw.githubusercontent.com/%s/%s/%s"


def source_url(repository, ref, path):
    return RAW % (repository, quote(ref, safe=""), quote(path.lstrip("/"), safe="/"))


def _script(text):
    """Line-ending and trailing-whitespace noise is not drift."""
    return "\n".join(line.rstrip() for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").strip().split("\n"))


def _json(value):
    """Egg config arrives as JSON text in an export file and as a parsed object from the API."""
    if isinstance(value, str):
        try:
            return json.loads(value) if value.strip() else None
        except ValueError:
            return value
    return value or None


def _bool(value):
    return bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes")


def egg_info(egg):
    """The facts about an egg that matter when asking whether it still works."""
    script = egg.get("script") or {}
    runtime = sorted(set((egg.get("docker_images") or {}).values()) | ({egg["docker_image"]} if egg.get("docker_image") else set()))
    return {
        "id": egg["id"],
        "nest": egg.get("nest"),
        "name": egg["name"],
        "author": egg.get("author"),
        "updated_at": egg.get("updated_at"),
        "install_image": script.get("container"),
        "runtime_images": runtime,
    }


def drift(panel, source):
    """Differences between the panel's egg and an exported egg file.

    panel is the egg as the API returns it, with its variables under "variables".
    source is the parsed JSON file. Each result is {field, panel, source}. What is
    compared: the install container, entrypoint and script, the startup command, the
    runtime images, the config Wings reads live (files rewritten at start, the "done"
    text, log location, stop command), the file denylist, and each variable's default,
    rules and visibility. Features are compared only when the panel's API returns them,
    which it does not appear to.
    """
    found = []
    script = panel.get("script") or {}
    install = (source.get("scripts") or {}).get("installation") or {}

    def note(field, have, want):
        if have != want:
            found.append({"field": field, "panel": have, "source": want})

    note("install_container", script.get("container"), install.get("container"))
    note("install_entrypoint", script.get("entry"), install.get("entrypoint"))
    have_script, want_script = _script(script.get("install")), _script(install.get("script"))
    if have_script != want_script:
        found.append({"field": "install_script",
                      "panel": "%d lines" % len(have_script.split("\n")), "source": "%d lines" % len(want_script.split("\n")),
                      "panel_text": have_script, "source_text": want_script})
    note("startup", panel.get("startup"), source.get("startup"))

    cfg, src_cfg = panel.get("config") or {}, source.get("config") or {}
    for key in ("files", "startup", "logs"):
        note("config_%s" % key, _json(cfg.get(key)), _json(src_cfg.get(key)))
    note("config_stop", cfg.get("stop"), src_cfg.get("stop"))
    denylist = panel.get("file_denylist") if panel.get("file_denylist") is not None else cfg.get("file_denylist")
    if denylist is not None:
        note("file_denylist", sorted(denylist), sorted(source.get("file_denylist") or []))
    if panel.get("features") is not None:
        note("features", sorted(panel["features"]), sorted(source.get("features") or []))

    have_images = set((panel.get("docker_images") or {}).values())
    want_images = set((source.get("docker_images") or {}).values())
    if have_images != want_images:
        found.append({"field": "runtime_images", "panel_only": sorted(have_images - want_images),
                      "source_only": sorted(want_images - have_images)})

    have_vars = {v["env_variable"]: v for v in panel.get("variables") or []}
    want_vars = {v["env_variable"]: v for v in source.get("variables") or []}
    for name in sorted(set(have_vars) | set(want_vars)):
        if name not in have_vars:
            found.append({"field": "variable %s" % name, "panel": None, "source": "present"})
        elif name not in want_vars:
            found.append({"field": "variable %s" % name, "panel": "present", "source": None})
        else:
            have, want = have_vars[name], want_vars[name]
            for key in ("default_value", "rules"):
                note("variable %s %s" % (name, key), have.get(key), want.get(key))
            for key in ("user_viewable", "user_editable"):
                if key in have and key in want:
                    note("variable %s %s" % (name, key), _bool(have[key]), _bool(want[key]))
    return found
