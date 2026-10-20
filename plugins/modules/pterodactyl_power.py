#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_power
short_description: Set the power state of a Pterodactyl server
description:
  - Starts, stops, restarts or kills a server and waits for it.
  - Idempotent for V(started) and V(stopped).
  - Pass the O(ignore:previous_power) value that M(jochocki.pterodactyl.minecraft_server)
    returns as O(state) to put a server back the way it was.
options:
  server:
    description: Server name, 8-character identifier or external ID.
    type: str
    required: true
  state:
    description: Target power state.
    type: str
    choices: [started, stopped, restarted, killed]
    required: true
  wait:
    description: Wait for the state to be reached.
    type: bool
    default: true
  timeout:
    description: Seconds to wait.
    type: int
    default: 120
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Restore the previous power state
  jochocki.pterodactyl.pterodactyl_power:
    server: Tiny Animals
    state: "{{ tiny.previous_power }}"
"""

RETURN = r"""
identifier:
  description: Identifier of the server.
  returned: success
  type: str
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import find_server, power_label, set_power


def main():
    spec = connection_spec()
    spec.update(
        server=dict(type="str", required=True),
        state=dict(type="str", required=True, choices=["started", "stopped", "restarted", "killed"]),
        wait=dict(type="bool", default=True),
        timeout=dict(type="int", default=120),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    try:
        client = build_client(module)
        ref = module.params["server"]
        server = find_server(client.servers(), external_id=ref, identifier=ref, name=ref)
        if server is None:
            module.fail_json(msg="no server matches %r" % ref)
        state = module.params["state"]
        if module.check_mode:
            current = power_label(client.power_state(server["identifier"]))
            module.exit_json(changed=state in ("restarted", "killed") or current != state,
                             identifier=server["identifier"])
        changed = set_power(client, server["identifier"], state,
                            wait=module.params["wait"], timeout=module.params["timeout"])
        module.exit_json(changed=changed, identifier=server["identifier"])
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
