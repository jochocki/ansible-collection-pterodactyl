#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_server
short_description: Create, rename and delete a Pterodactyl server
description:
  - Manages a server's existence and the fields on the Details tab of the panel's server page.
  - The options for creating a server mirror the panel's create form. They are only used when
    the server does not exist yet. Change an existing server's limits with
    M(jochocki.pterodactyl.pterodactyl_build), which also moves its ports, and its image, startup command and variables with
    M(jochocki.pterodactyl.pterodactyl_startup).
  - Servers are found by O(external_id) when it is set, then by exact O(name).
    A server found by name gets its external ID set.
options:
  name:
    description: Server name.
    type: str
    required: true
  external_id:
    description: Stable key for the server. Setting it makes a later rename safe.
    type: str
  description:
    description: Free text on the Details tab.
    type: str
  owner:
    description: Panel user ID that owns the server. Required to create one.
    type: int
  state:
    description: V(absent) deletes the server.
    type: str
    choices: [present, absent]
    default: present
  node:
    description: Panel node name. Required to create a server.
    type: str
  egg:
    description: Egg name. Required to create a server.
    type: str
  docker_image:
    description: Docker image. Required to create a server.
    type: str
  startup:
    description: Startup command. Required to create a server.
    type: str
  environment:
    description: Egg variables for a new server.
    type: dict
  memory:
    description: Memory limit in MB, for a new server. Default 1024.
    type: int
  swap:
    description: Swap limit in MB, for a new server. Default 0.
    type: int
  disk:
    description: Disk limit in MB, for a new server. 0 is unlimited, which is the default.
    type: int
  io:
    description: Block IO weight, for a new server. Default 500.
    type: int
  cpu:
    description: CPU limit in percent, for a new server. 0 is unlimited, which is the default.
    type: int
  backups:
    description: Backup slots, for a new server. Default 0.
    type: int
  databases:
    description: Database limit, for a new server. Default 0.
    type: int
  allocation_limit:
    description: How many additional allocations the server may hold, for a new server. Default 0.
    type: int
  port:
    description:
      - The primary (game) port of a new server. It must already exist as an unassigned allocation
        on the node. Without it the first free allocation is used.
    type: int
  additional_ports:
    description: Additional ports for a new server, each an unassigned allocation on the node. Needs O(port).
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
- name: A Factorio server
  jochocki.pterodactyl.pterodactyl_server:
    name: Factorio
    owner: 1
    node: wings01
    egg: Factorio
    docker_image: ghcr.io/ptero-eggs/yolks:debian
    startup: ./bin/x64/factorio --start-server
    memory: 2000
    cpu: 200

- name: Rename it without orphaning it
  jochocki.pterodactyl.pterodactyl_server:
    external_id: factorio
    name: Factorio (family)
"""

RETURN = r"""
server:
  description: The server after the module ran. Not returned when it was deleted or is only planned in check mode.
  returned: when the server exists
  type: dict
  contains:
    id:
      description: Numeric ID, used by the application API.
      type: int
    identifier:
      description: The 8-character identifier, used by the client API and in the panel's URLs.
      type: str
    name:
      description: Server name.
      type: str
    external_id:
      description: External ID, if set.
      type: str
actions:
  description: What the module did, or would do in check mode.
  returned: always
  type: list
  elements: str
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
    summarize,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import (
    create_server,
    ensure_details,
    find_server,
)

CREATE_REQUIRED = ("owner", "node", "egg", "docker_image", "startup")


def main():
    spec = connection_spec()
    spec.update(
        name=dict(type="str", required=True),
        external_id=dict(type="str"),
        description=dict(type="str"),
        owner=dict(type="int"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        node=dict(type="str"),
        egg=dict(type="str"),
        docker_image=dict(type="str"),
        startup=dict(type="str"),
        environment=dict(type="dict"),
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
        server = find_server(client.servers(), external_id=p["external_id"], name=p["name"])

        if p["state"] == "absent":
            if server and not module.check_mode:
                client.delete_server(server["id"])
            module.exit_json(changed=server is not None, actions=["delete server"] if server else [])

        if server is not None:
            actions = ensure_details(
                client, server,
                {k: p[k] for k in ("name", "external_id", "description", "owner")},
                check_mode=module.check_mode,
            )
            module.exit_json(changed=bool(actions), actions=actions, server=summarize(server))

        missing = [k for k in CREATE_REQUIRED if p[k] is None]
        if missing:
            module.fail_json(msg="server %r does not exist; to create it also set: %s" % (p["name"], ", ".join(missing)))
        actions = ["create server %s" % p["name"]]
        if module.check_mode:
            module.exit_json(changed=True, actions=actions)
        created = create_server(client, {
            "name": p["name"],
            "external_id": p["external_id"],
            "description": p["description"],
            "owner": p["owner"],
            "egg": p["egg"],
            "image": p["docker_image"],
            "startup": p["startup"],
            "environment": {k: str(v) for k, v in (p["environment"] or {}).items()},
            "node": p["node"],
            "limits": {k: p[k] for k in ("memory", "swap", "disk", "io", "cpu") if p[k] is not None},
            "feature_limits": {k: p[k] for k in ("databases", "backups") if p[k] is not None},
            "port": p["port"],
            "additional_ports": p["additional_ports"],
            "ip": p["ip"],
        })
        module.exit_json(changed=True, actions=actions, server=summarize(created))
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
