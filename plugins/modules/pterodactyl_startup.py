#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_startup
short_description: Set a Pterodactyl server's image, startup command and variables
description:
  - Manages the Startup tab of the panel's server page. Only the options you set are compared and
    changed.
  - Changing the egg is not supported. The egg is chosen when the server is created.
  - The module does not stop the server. A running server picks up a new image at its next start.
    With O(reinstall=true) the server is reinstalled after a change, which the panel does by
    stopping it, so stop and back it up first if its data matters.
options:
  server:
    description: Server name, 8-character identifier or external ID.
    type: str
    required: true
  docker_image:
    description: Docker image the server runs in.
    type: str
  startup:
    description: Startup command.
    type: str
  environment:
    description:
      - Egg variables to set, as a dict. Variables not listed keep their value.
      - Values are sent as strings.
    type: dict
  reinstall:
    description: Reinstall the server and wait for it when something changed.
    type: bool
    default: false
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
  - ansible.builtin.action_common_attributes
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Move a server to a newer Java and version
  jochocki.pterodactyl.pterodactyl_startup:
    server: Tiny Animals
    docker_image: ghcr.io/pterodactyl/yolks:java_25
    environment:
      MC_VERSION: "26.3"
    reinstall: true
"""

RETURN = r"""
changes:
  description: The fields that changed, with their new values.
  returned: always
  type: dict
"""

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
    diff_result,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import ensure_startup, get_server, new_diff


def main():
    spec = connection_spec()
    spec.update(
        server=dict(type="str", required=True),
        docker_image=dict(type="str"),
        startup=dict(type="str"),
        environment=dict(type="dict"),
        reinstall=dict(type="bool", default=False),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        client = build_client(module)
        server = get_server(client, p["server"])
        diff = new_diff()
        changes, actions = ensure_startup(
            client, server,
            image=p["docker_image"],
            startup=p["startup"],
            environment={k: str(v) for k, v in p["environment"].items()} if p["environment"] else None,
            reinstall=p["reinstall"],
            check_mode=module.check_mode, diff=diff,
        )
        module.exit_json(changed=bool(changes), changes=changes, actions=actions,
                         **(diff_result(p["server"], diff) if module._diff else {}))
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
