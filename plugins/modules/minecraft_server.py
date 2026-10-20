#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: minecraft_server
short_description: Create and upgrade a Minecraft server on a Pterodactyl panel
description:
  - Creates the server if it is missing, converges its limits, and moves it to
    a new Minecraft version.
  - The version is checked against Mojang's release manifest, and the Java
    image follows from it (8, 17, 21 or 25).
  - A version change stops the server, backs it up (making room by deleting the
    oldest unlocked backup), reinstalls it, and restores its power state. Set
    O(restore_power=false) to leave it stopped so mods can be swapped first.
  - Servers are found by O(external_id), then by exact O(name). A server found by
    name has its external ID set, so a later rename does not orphan it.
options:
  name:
    description: Server name on the panel.
    type: str
    required: true
  external_id:
    description: Stable key for the server. Defaults to the name, lower-cased with dashes.
    type: str
  state:
    description: V(absent) deletes the server.
    type: str
    choices: [present, absent]
    default: present
  loader:
    description: Server software. Only these have eggs the module knows.
    type: str
    choices: [fabric, paper, vanilla]
    required: true
  version:
    description: Minecraft release, such as V("1.21.4") or V("26.3"). Always quote it, because YAML reads 1.20 as 1.2.
    type: str
    required: true
  node:
    description: Panel node name. Needed only to create a server.
    type: str
  owner:
    description: Panel user ID that owns a new server.
    type: int
    default: 1
  memory:
    description: Memory limit in MB.
    type: int
  cpu:
    description: CPU limit in percent. 0 is unlimited.
    type: int
  disk:
    description: Disk limit in MB. 0 is unlimited.
    type: int
  swap:
    description: Swap limit in MB.
    type: int
  io:
    description: Block IO weight.
    type: int
  backups:
    description: Backup slots.
    type: int
  backup_before_upgrade:
    description: Back the server up before a version change.
    type: bool
    default: true
  restore_power:
    description: Start the server again after a version change if it was running.
    type: bool
    default: true
  validate_version:
    description: Check O(version) against Mojang's release manifest.
    type: bool
    default: true
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Tiny Animals on the newest release
  jochocki.pterodactyl.minecraft_server:
    name: Tiny Animals
    loader: fabric
    version: "26.3"
    node: wings01
    memory: 3000
    cpu: 300
    restore_power: false
  register: tiny

- name: Put it back the way it was
  jochocki.pterodactyl.pterodactyl_power:
    server: Tiny Animals
    state: "{{ tiny.previous_power }}"
"""

RETURN = r"""
actions:
  description: What the module did, or would do in check mode.
  returned: always
  type: list
  elements: str
previous_power:
  description: V(started) or V(stopped), the server's state before the module ran.
  returned: success
  type: str
power_after:
  description:
    - V(started) or V(stopped), the state the module left the server in.
    - It differs from RV(previous_power) after a version change with O(restore_power=false).
  returned: success
  type: str
identifier:
  description: The server's 8-character identifier.
  returned: when the server exists
  type: str
"""

import re

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import http as phttp
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import (
    MOJANG_MANIFEST,
    check_version,
    release_ids,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import (
    ensure_minecraft_server,
    find_server,
)


def default_external_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    spec = connection_spec()
    spec.update(
        name=dict(type="str", required=True),
        external_id=dict(type="str"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        loader=dict(type="str", required=True, choices=["fabric", "paper", "vanilla"]),
        version=dict(type="str", required=True),
        node=dict(type="str"),
        owner=dict(type="int", default=1),
        memory=dict(type="int"),
        cpu=dict(type="int"),
        disk=dict(type="int"),
        swap=dict(type="int"),
        io=dict(type="int"),
        backups=dict(type="int"),
        backup_before_upgrade=dict(type="bool", default=True),
        restore_power=dict(type="bool", default=True),
        validate_version=dict(type="bool", default=True),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        client = build_client(module)
        external_id = p["external_id"] or default_external_id(p["name"])

        if p["state"] == "absent":
            server = find_server(client.servers(), external_id=external_id, name=p["name"])
            if server and not module.check_mode:
                client.delete_server(server["id"])
            module.exit_json(changed=server is not None, actions=["delete server"] if server else [])

        if p["validate_version"]:
            check_version(p["version"], release_ids(phttp.get_json(MOJANG_MANIFEST)))
        else:
            check_version(p["version"], {p["version"]})

        result = ensure_minecraft_server(
            client,
            {
                "name": p["name"],
                "external_id": external_id,
                "loader": p["loader"],
                "version": p["version"],
                "node": p["node"],
                "owner": p["owner"],
                "limits": {k: p[k] for k in ("memory", "cpu", "disk", "swap", "io", "backups")},
            },
            check_mode=module.check_mode,
            restore_power=p["restore_power"],
            backup=p["backup_before_upgrade"],
        )
        server = result.pop("server")
        if server:
            result["identifier"] = server.get("identifier")
        module.exit_json(**result)
    except (PterodactylError, phttp.HttpError, ValueError) as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
