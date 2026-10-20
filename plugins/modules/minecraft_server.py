#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: minecraft_server
short_description: Create, upgrade and mod a Minecraft server on a Pterodactyl panel
description:
  - Creates the server if it is missing, converges its limits, and moves it to
    a new Minecraft version.
  - The version is checked against Mojang's release manifest, and the Java
    image follows from it (8, 17, 21 or 25).
  - A version change stops the server, backs it up (making room by deleting the
    oldest unlocked backup) and reinstalls it. It starts again afterwards if it
    was running.
  - A reinstall is checked by its effect. The jar the server starts (C(SERVER_JARFILE)) must have
    been rewritten. The panel can report success for an install that never ran, for example when
    Wings cannot pull the egg's install image, so a jar that is missing or untouched fails the
    run with the server left stopped and the location of Wings' install log.
  - With O(mods), the server's mods are kept in step with Modrinth too, for the
    server's own version and loader. Mods resolve before anything else, so an
    unknown project leaves the server untouched. They are installed before the
    server starts again, and a running server is restarted when its mods changed.
    If they fail to install after a version change, the server is left stopped.
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
  port:
    description:
      - The game port. It must already exist as an allocation on the node.
      - For a new server it picks the allocation instead of the first free one. For an existing
        server it moves the server to that port. Leave it out to leave the port alone.
    type: int
  additional_ports:
    description: The complete set of additional ports. See M(jochocki.pterodactyl.pterodactyl_build).
    type: list
    elements: int
  ip:
    description:
      - The allocation IP. Only needed when a port exists on more than one IP on the node.
      - It applies to every port given, so all of them must be on this IP.
    type: str
  environment:
    description:
      - Egg variables to set on purpose, such as V(SERVER_JARFILE), as a dict. Values are sent as strings.
      - Every other variable keeps the server's current value, and a new server gets the egg's own
        defaults. The Minecraft version variable is set from O(version).
      - Changing a variable updates the server's startup settings. It does not reinstall; add
        O(reinstall=true) when the change needs the install script to run again.
    type: dict
  reinstall:
    description:
      - Run the full version-change sequence (stop, backup, reinstall, restart) even when the
        version already matches.
      - Use it to retry an install that did not take. It is not idempotent and reports changed
        every run, so set it for one run only.
    type: bool
    default: false
  backup_before_upgrade:
    description:
      - What to do about a backup before a version change or forced reinstall.
      - V(rotate) takes a backup, deleting the oldest unlocked backups first when the server is at
        its backup limit. Locked backups are never deleted; the run fails if they leave no room.
      - V(fail) takes a backup but never deletes one. If the server is at its limit the run fails
        before anything changes, also in check mode.
      - V(skip) takes no backup.
    type: str
    choices: [rotate, fail, skip]
    default: rotate
  mods:
    description:
      - Modrinth project slugs or IDs, the complete set of mods for the server.
      - Leave it out to leave the mods directory alone. If the server already has mods, the run
        fails before changing anything unless O(unlisted_mods) says otherwise.
      - An empty list removes every mod (with O(purge=true)). Not valid for the V(vanilla) loader.
      - Required dependencies, such as V(fabric-api), are not added for you. List them.
    type: list
    elements: str
  unlisted_mods:
    description:
      - What to do when O(mods) is not set and the server already has mods in its mods directory
        (C(/mods), or C(/plugins) for Paper).
      - V(fail) stops before anything is changed. Nothing says what those mods should be, and a
        version change would leave jars built for the old version that Fabric refuses to load. This is
        the default, and the message names the jars and, on a version change, which ones won't load.
      - V(warn) lets the run go on, checks the jars on a version change and warns about the ones that
        won't load (see RV(unmanaged_mods)).
      - V(ignore) leaves them alone without a word, for mods you really do manage by hand.
      - Does not apply when O(mods) is set, including an empty list.
    type: str
    choices: [fail, warn, ignore]
    default: fail
  purge:
    description:
      - Delete C(.jar) files in C(/mods) that are not in O(mods), after the listed ones are
        downloaded and verified. Only used with O(mods).
      - With V(false), an upgraded mod leaves its old jar behind, and Fabric refuses to start
        with two jars of one mod.
    type: bool
    default: true
  user_agent:
    description: Sent to Modrinth, which asks for a contact in it. Only used with O(mods).
    type: str
    default: ansible-collection-jochocki.pterodactyl
  validate_version:
    description: Check O(version) against Mojang's release manifest.
    type: bool
    default: true
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
- name: Tiny Animals on the newest release
  jochocki.pterodactyl.minecraft_server:
    name: Tiny Animals
    loader: fabric
    version: "26.3"
    node: wings01
    memory: 3000
    cpu: 300
    mods:
      - fabric-api
      - xaeros-minimap
      - xaeros-world-map

- name: A vanilla server has no mods
  jochocki.pterodactyl.minecraft_server:
    name: The Warden
    loader: vanilla
    version: "1.21"
    node: wings01
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
  description: V(started) or V(stopped), the state the module left the server in.
  returned: success
  type: str
unmanaged_mods:
  description:
    - Returned when the version changes on a server whose mods are not managed (no O(mods)).
    - Each existing jar is looked up on Modrinth by its hash and reported as V(compatible) or
      V(incompatible) with the new version, or V(unknown) if Modrinth doesn't know it. The
      jars are never changed, and incompatible or unknown ones also raise a warning.
    - Not returned when there are no jars, more than 40, or the loader has no mod support.
  returned: when it applies
  type: list
  elements: dict
  contains:
    file:
      description: The jar.
      type: str
    status:
      description: V(compatible), V(incompatible) or V(unknown).
      type: str
    detail:
      description: The Minecraft versions an incompatible jar was built for, or why it is unknown.
      type: str
mods:
  description: What happened to the mods. Not returned unless O(mods) is set.
  returned: when O(mods) is set and the server exists
  type: dict
  contains:
    installed:
      description: Files pulled onto the server.
      type: list
      elements: str
    removed:
      description: Files deleted from the server.
      type: list
      elements: str
    unchanged:
      description: Files already present with the right name and size.
      type: list
      elements: str
    left_in_place:
      description: Unlisted jars kept because O(purge=false).
      type: list
      elements: str
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
    diff_result,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import (
    LOADERS,
    MOJANG_MANIFEST,
    check_version,
    release_ids,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft_ops import converge_minecraft
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import find_server


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
        port=dict(type="int"),
        additional_ports=dict(type="list", elements="int"),
        ip=dict(type="str"),
        environment=dict(type="dict"),
        reinstall=dict(type="bool", default=False),
        backup_before_upgrade=dict(type="str", default="rotate", choices=["rotate", "fail", "skip"]),
        mods=dict(type="list", elements="str"),
        unlisted_mods=dict(type="str", default="fail", choices=["fail", "warn", "ignore"]),
        purge=dict(type="bool", default=True),
        user_agent=dict(type="str", default="ansible-collection-jochocki.pterodactyl"),
        validate_version=dict(type="bool", default=True),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True)
    p = module.params
    try:
        client = build_client(module)
        external_id = p["external_id"] or default_external_id(p["name"])
        if p["mods"] is not None and not LOADERS[p["loader"]]["mod_loaders"]:
            module.fail_json(msg="the %s loader does not support mods; leave mods out" % p["loader"])

        if p["state"] == "absent":
            server = find_server(client.servers(), external_id=external_id, name=p["name"])
            if server and not module.check_mode:
                client.delete_server(server["id"])
            module.exit_json(changed=server is not None, actions=["delete server"] if server else [],
                             **(diff_result(p["name"], {"before": {"server": server["name"]}, "after": {}})
                                if server and module._diff else {}))

        if p["validate_version"]:
            check_version(p["version"], release_ids(phttp.get_json(MOJANG_MANIFEST)))
        else:
            check_version(p["version"], {p["version"]})

        def fetch(url):
            return phttp.get_json(url, headers={"User-Agent": p["user_agent"]})

        def post(url, body):
            return phttp.post_json(url, body, headers={"User-Agent": p["user_agent"]})

        result = converge_minecraft(
            client,
            {
                "name": p["name"],
                "external_id": external_id,
                "loader": p["loader"],
                "version": p["version"],
                "node": p["node"],
                "owner": p["owner"],
                "reinstall": p["reinstall"],
                "environment": p["environment"],
                # The build tab: limits and ports.
                "limits": {k: p[k] for k in ("memory", "cpu", "disk", "swap", "io", "backups",
                                             "port", "additional_ports", "ip")},
            },
            mods=p["mods"],
            fetch=fetch,
            post=post,
            unlisted=p["unlisted_mods"],
            purge=p["purge"],
            check_mode=module.check_mode,
            backup=p["backup_before_upgrade"],
        )
        server = result.pop("server")
        if server:
            result["identifier"] = server.get("identifier")
        result.pop("version_changed", None)
        for entry in result.get("unmanaged_mods") or []:
            if entry["status"] != "compatible":
                module.warn("%s: %s in /mods is %s (%s); mods are not managed here, so it was left alone. List mods "
                            "to have them matched to %s." % (p["name"], entry["file"], entry["status"],
                                                             entry["detail"], p["version"]))
        diff = result.pop("diff")
        if module._diff:
            result.update(diff_result(p["name"], diff))
        module.exit_json(**result)
    except (PterodactylError, phttp.HttpError, ValueError) as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
