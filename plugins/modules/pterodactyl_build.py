#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_build
short_description: Set a Pterodactyl server's resource limits
description:
  - Manages the Build Configuration tab of the panel's server page, the resource limits and the
    allocations (the game port and any additional ports). Only the options you set are compared
    and changed, so the others keep whatever the server has.
  - The panel silently skips an allocation it won't assign, so the module checks the node first and
    confirms the result afterwards.
options:
  server:
    description: Server name, 8-character identifier or external ID.
    type: str
    required: true
  memory:
    description: Memory limit in MB. 0 is unlimited.
    type: int
  swap:
    description: Swap limit in MB.
    type: int
  disk:
    description: Disk limit in MB. 0 is unlimited.
    type: int
  io:
    description: Block IO weight, 10 to 1000.
    type: int
  cpu:
    description: CPU limit in percent, where 100 is one core. 0 is unlimited.
    type: int
  backups:
    description: Backup slots.
    type: int
  databases:
    description: Database limit.
    type: int
  allocation_limit:
    description:
      - How many additional allocations the server may hold. This is the limit, not the ports
        themselves, which are O(port) and O(additional_ports).
    type: int
  port:
    description:
      - The primary (game) port. It must already exist as an allocation on the server's node, and
        either be unassigned or already belong to this server.
      - Moving to a new port leaves the old one assigned as an additional port, unless
        O(additional_ports) is set and does not list it.
    type: int
  additional_ports:
    description:
      - The complete set of additional ports. Ports not listed are released from the server.
      - Leave it out to leave the additional ports alone. An empty list releases them all.
      - Each must already exist as an allocation on the node. Create them under Nodes, Allocation
        in the panel.
    type: list
    elements: int
  ip:
    description:
      - The allocation IP. Only needed when a port exists on more than one IP on the node.
      - It applies to every port given, so all of them must be on this IP.
    type: str
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Give Factorio more memory
  jochocki.pterodactyl.pterodactyl_build:
    server: Factorio
    memory: 4000

- name: Move a server to another game port and give it a second one
  jochocki.pterodactyl.pterodactyl_build:
    server: Tiny Animals
    port: 25566
    additional_ports: [25567]
    allocation_limit: 1
"""

RETURN = r"""
changes:
  description: What changed, with the new values. Port changes are reported as port, added_ports and removed_ports.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import ensure_build, get_server


def main():
    spec = connection_spec()
    spec.update(
        server=dict(type="str", required=True),
        memory=dict(type="int"),
        swap=dict(type="int"),
        disk=dict(type="int"),
        io=dict(type="int"),
        cpu=dict(type="int"),
        backups=dict(type="int"),
        databases=dict(type="int"),
        allocation_limit=dict(type="int"),
        port=dict(type="int"),
        additional_ports=dict(type="list", elements="int"),
        ip=dict(type="str"),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        client = build_client(module)
        server = get_server(client, p["server"])
        changes, actions = ensure_build(
            client, server,
            dict(
                {k: p[k] for k in ("memory", "swap", "disk", "io", "cpu", "backups", "databases",
                                   "port", "additional_ports", "ip")},
                allocations=p["allocation_limit"],
            ),
            check_mode=module.check_mode,
        )
        module.exit_json(changed=bool(changes), changes=changes, actions=actions)
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
