# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Connection arguments and client construction shared by every module."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import (
    PterodactylClient,
)


def connection_spec():
    return dict(
        panel_url=dict(type="str", default=os.environ.get("PTERODACTYL_URL")),
        api_key=dict(type="str", no_log=True, default=os.environ.get("PTERODACTYL_API_KEY")),
        validate_certs=dict(type="bool", default=True),
    )


def diff_result(name, diff):
    """The {before, after} of a diff, as the line-oriented text --diff shows.

    Returns {} for an empty diff, so it can be merged into exit_json unconditionally.
    """
    if not diff or not (diff["before"] or diff["after"]):
        return {}

    def render(side):
        return json.dumps(side, indent=2, sort_keys=True) + "\n"
    return {"diff": {"before": render(diff["before"]), "after": render(diff["after"]),
                     "before_header": "%s (panel, before)" % name, "after_header": "%s (panel, after)" % name}}


def summarize(server):
    """The fields of a server worth returning from a module."""
    return {k: server.get(k) for k in ("id", "identifier", "name", "external_id")}


def build_client(module):
    if not module.params["panel_url"] or not module.params["api_key"]:
        module.fail_json(msg="panel_url and api_key are required (or set PTERODACTYL_URL and PTERODACTYL_API_KEY)")
    return PterodactylClient(
        module.params["panel_url"],
        module.params["api_key"],
        validate_certs=module.params["validate_certs"],
    )
