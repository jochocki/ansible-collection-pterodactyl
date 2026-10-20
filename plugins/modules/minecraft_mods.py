#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: minecraft_mods
short_description: Keep a Minecraft server's mods in step with Modrinth
description:
  - Resolves each project to its newest release for the server's Minecraft
    version and loader, pulls missing files into C(/mods) through the panel,
    and checks the sha512 of every new file.
  - Every project resolves before anything changes, so one bad name leaves the
    directory untouched.
  - Stale jars are removed after the new ones are verified. A mod upgrade has a
    new filename, so with O(purge=false) the old jar stays and Fabric refuses to
    start on the duplicate mod ID.
  - Does not restart the server. Follow it with M(jochocki.pterodactyl.pterodactyl_power).
options:
  server:
    description: Server name, 8-character identifier or external ID.
    type: str
    required: true
  version:
    description: Minecraft version the mods must support. Quote it.
    type: str
    required: true
  loader:
    description: Server software. Vanilla has no mod support.
    type: str
    choices: [fabric, paper]
    required: true
  mods:
    description: Modrinth project slugs or IDs.
    type: list
    elements: str
    required: true
  purge:
    description: Delete C(.jar) files in C(/mods) that are not in O(mods).
    type: bool
    default: true
  user_agent:
    description: Sent to Modrinth, which asks for a contact in it.
    type: str
    default: ansible-collection-jochocki.pterodactyl
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Mods for Tiny Animals
  jochocki.pterodactyl.minecraft_mods:
    server: Tiny Animals
    version: "26.3"
    loader: fabric
    mods: [fabric-api, xaeros-minimap, xaeros-world-map]
"""

RETURN = r"""
installed:
  description: Files pulled onto the server.
  returned: always
  type: list
  elements: str
removed:
  description: Files deleted from the server.
  returned: always
  type: list
  elements: str
unchanged:
  description: Files already present with the right name and size.
  returned: always
  type: list
  elements: str
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import http as phttp
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import parse_version
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.mods import sync_mods
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import find_server


def main():
    spec = connection_spec()
    spec.update(
        server=dict(type="str", required=True),
        version=dict(type="str", required=True),
        loader=dict(type="str", required=True, choices=["fabric", "paper"]),
        mods=dict(type="list", elements="str", required=True),
        purge=dict(type="bool", default=True),
        user_agent=dict(type="str", default="ansible-collection-jochocki.pterodactyl"),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        parse_version(p["version"])
        client = build_client(module)
        server = find_server(client.servers(), external_id=p["server"], identifier=p["server"], name=p["server"])
        if server is None:
            module.fail_json(msg="no server matches %r" % p["server"])

        def fetch(url):
            return phttp.get_json(url, headers={"User-Agent": p["user_agent"]})

        result = sync_mods(
            client, server["identifier"], p["version"], p["loader"], p["mods"], fetch,
            purge=p["purge"], check_mode=module.check_mode,
        )
        module.exit_json(**result)
    except (PterodactylError, phttp.HttpError, ValueError) as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
