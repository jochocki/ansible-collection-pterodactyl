# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The Minecraft layer: version and loader become an egg, a Java image and startup variables,
then the generic server operations apply them."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import time

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import (
    LOADERS,
    java_image,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.mods import (
    apply_mods,
    resolve_mods,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.servers import (
    create_server,
    ensure_build,
    ensure_details,
    find_server,
    power_label,
    rotate_and_backup,
    set_power,
    update_startup,
    wait_installed,
)


def desired_environment(loader, version):
    row = LOADERS[loader]
    env = dict(row["environment"])
    env[row["version_var"]] = version
    return env


def current_version(server, loader):
    env = (server.get("container") or {}).get("environment") or {}
    return env.get(LOADERS[loader]["version_var"])


def ensure_minecraft_server(client, spec, check_mode=False, restore_power=True, backup=True, sleep=time.sleep):
    """Create or converge one Minecraft server.

    spec keys: name, external_id, loader, version, node, owner, limits (dict
    of memory/swap/disk/io/cpu/backups, any may be None).
    Returns {changed, actions, server, previous_power, power_after}. Both power values are
    "started" or "stopped" and describe the real server, changed or not.
    """
    loader = spec["loader"]
    row = LOADERS[loader]
    image = java_image(spec["version"])
    actions = []
    server = find_server(client.servers(), spec.get("external_id"), None, spec["name"])
    want = spec.get("limits") or {}

    if server is None:
        actions.append("create server %s (%s %s, %s)" % (spec["name"], loader, spec["version"], image))
        if check_mode:
            return {"changed": True, "actions": actions, "server": None, "previous_power": "stopped",
                    "power_after": "stopped"}
        created = create_server(client, {
            "name": spec["name"],
            "external_id": spec.get("external_id"),
            "owner": spec["owner"],
            "egg": row["egg"],
            "image": image,
            "startup": row["startup"],
            "environment": desired_environment(loader, spec["version"]),
            "node": spec["node"],
            "limits": want,
            "feature_limits": {"backups": want.get("backups", 2)},
            "port": want.get("port"),
            "additional_ports": want.get("additional_ports"),
            "ip": want.get("ip"),
        }, sleep=sleep)
        return {"changed": True, "actions": actions, "server": created,
                "previous_power": "stopped", "power_after": "stopped"}

    if server.get("egg") is not None:
        egg_ids = [e["id"] for e in client.eggs() if e["name"] == row["egg"]]
        if egg_ids and server["egg"] not in egg_ids:
            raise PterodactylError(
                "%s runs a different egg than loader %r; changing egg is not supported" % (spec["name"], loader)
            )

    identifier = server["identifier"]
    previous_power = power_label(client.power_state(identifier))
    power_after = previous_power

    actions += ensure_details(client, server, {"external_id": spec.get("external_id")}, check_mode)
    changes, build_actions = ensure_build(client, server, want, check_mode)
    actions += build_actions

    version_changed = current_version(server, loader) != spec["version"]
    image_changed = (server.get("container") or {}).get("image") != image
    if version_changed or image_changed:
        actions.append("set %s %s on %s" % (loader, spec["version"], image))
    if version_changed:
        actions.append("backup, reinstall")

    if (version_changed or image_changed) and not check_mode:
        if version_changed:
            if previous_power == "started":
                set_power(client, identifier, "stopped", sleep=sleep)
                power_after = "stopped"
            if backup:
                actions.append("backup: %s" % rotate_and_backup(
                    client, identifier, changes.get("backups", server["feature_limits"]["backups"]), sleep=sleep))
        update_startup(
            client, server,
            image=image,
            startup=(server.get("container") or {}).get("startup_command") or row["startup"],
            environment=desired_environment(loader, spec["version"]),
        )
        if version_changed:
            client.reinstall(server["id"])
            wait_installed(client, identifier, "reinstall", sleep)
            if restore_power and previous_power == "started":
                set_power(client, identifier, "started", sleep=sleep)
                power_after = "started"
        elif previous_power == "started":
            actions.append("image applies on next restart")

    return {
        "changed": bool(actions),
        "actions": actions,
        "server": server,
        "previous_power": previous_power,
        "power_after": power_after,
    }


def converge_minecraft(client, spec, mods=None, fetch=None, purge=True, check_mode=False, backup=True,
                       sleep=time.sleep):
    """Converge a server and, when `mods` is given, its mods, then its power.

    mods=None leaves /mods alone. A list (even an empty one) makes it the
    complete set of mods. Mods resolve before anything else, so an unknown
    project fails with the server untouched. If the mods fail to install after
    a version change, the server is left stopped rather than booted without
    them.
    """
    wanted = None
    if mods is not None:
        wanted = resolve_mods(spec["version"], spec["loader"], mods, fetch)

    result = ensure_minecraft_server(
        client, spec, check_mode=check_mode, restore_power=mods is None, backup=backup, sleep=sleep)
    if wanted is None:
        return result

    server = result["server"]
    if server is None:  # check mode, server not created yet
        result["mods"] = None
        result["actions"].append("install %d mods once the server exists" % len(wanted))
        return result

    outcome = apply_mods(client, server["identifier"], wanted, purge=purge, check_mode=check_mode)
    result["mods"] = outcome
    if outcome["changed"]:
        result["changed"] = True
        result["actions"].append("mods: %d installed, %d removed" % (len(outcome["installed"]), len(outcome["removed"])))

    if not check_mode and result["previous_power"] == "started":
        if result["power_after"] == "stopped":
            set_power(client, server["identifier"], "started", sleep=sleep)
        elif outcome["changed"]:
            set_power(client, server["identifier"], "restarted", sleep=sleep)
        result["power_after"] = "started"
    return result
