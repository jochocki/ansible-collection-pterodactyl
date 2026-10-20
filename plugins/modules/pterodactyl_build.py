#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_build
short_description: Set a Pterodactyl server's resource limits
description:
  - Manages the Build Configuration tab of the panel's server page. Only the options you set are
    compared and changed, so the others keep whatever the server has.
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
  allocations:
    description: Extra allocation limit.
    type: int
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
"""

RETURN = r"""
changes:
  description: The limits that changed, with their new values.
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
        allocations=dict(type="int"),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        client = build_client(module)
        server = get_server(client, p["server"])
        changes, actions = ensure_build(
            client, server,
            {k: p[k] for k in ("memory", "swap", "disk", "io", "cpu", "backups", "databases", "allocations")},
            check_mode=module.check_mode,
        )
        module.exit_json(changed=bool(changes), changes=changes, actions=actions)
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
