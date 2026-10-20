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
    find_egg,
    find_server,
    new_diff,
    power_label,
    record,
    INSTALL_LOG,
    rotate_and_backup,
    set_power,
    update_startup,
    wait_installed,
)


def egg_environment(client, nest_id, egg_id, loader, version, current=None, extra=None):
    """Every variable of the egg, ready to send.

    Each keeps the server's current value, or the egg's own default for a new server or a variable
    the egg gained. Only the Minecraft version, and whatever the play sets explicitly, is changed.
    Taking names and defaults from the egg means a newer egg (a different SERVER_JARFILE, say)
    never gets old values pushed back onto it.
    """
    current = current or {}
    env = {v["env_variable"]: current.get(v["env_variable"], v["default_value"])
           for v in client.egg_variables(nest_id, egg_id)}
    env[LOADERS[loader]["version_var"]] = version
    env.update(extra or {})
    return env


def _extra_environment(spec):
    return {k: str(v) for k, v in (spec.get("environment") or {}).items()}


def current_version(server, loader):
    env = (server.get("container") or {}).get("environment") or {}
    return env.get(LOADERS[loader]["version_var"])


def jar_stamp(client, server, name):
    """When the jar the server starts (its SERVER_JARFILE) was last written, or None if it isn't there."""
    if not name:
        return None
    for f in client.list_files(server["identifier"], "/") or []:
        if f["name"] == name:
            return f.get("modified_at")
    return None


def check_install_ran(client, server, name, before):
    """The panel does not always notice an install that never ran, so look for its effect.

    A failed image pull, for instance, leaves the panel reporting success. A real install
    rewrites the jar the server starts, so a jar that is missing or untouched means it did not.
    """
    if not name:
        return  # nothing to look for
    after = jar_stamp(client, server, name)
    if after is None or after == before:
        raise PterodactylError(
            "the reinstall finished, but %s was not rewritten, so the install script most likely did not run "
            "(a failed image pull does this and the panel still reports success). Wings keeps the output "
            "on the node, by default in %s; read it and fix the cause, then run again with reinstall. "
            "The server is left stopped." % (name, INSTALL_LOG % (server.get("uuid") or "<server uuid>"))
        )


def ensure_minecraft_server(client, spec, check_mode=False, restore_power=True, backup=True, sleep=time.sleep):
    """Create or converge one Minecraft server.

    spec keys: name, external_id, loader, version, node, owner, limits (dict
    of memory/swap/disk/io/cpu/backups, any may be None).
    Returns {changed, actions, server, previous_power, power_after, diff}. Both power values are
    "started" or "stopped" and describe the real server, changed or not. diff is the
    {before, after} of everything that changed, for --diff.
    """
    diff = new_diff()
    loader = spec["loader"]
    row = LOADERS[loader]
    image = java_image(spec["version"])
    actions = []
    server = find_server(client.servers(), spec.get("external_id"), None, spec["name"])
    want = spec.get("limits") or {}

    if server is None:
        actions.append("create server %s (%s %s, %s)" % (spec["name"], loader, spec["version"], image))
        diff["after"]["server"] = {"name": spec["name"], "loader": loader, "version": spec["version"],
                                   "docker_image": image, "node": spec["node"],
                                   "limits": {k: v for k, v in want.items() if v is not None}}
        if check_mode:
            return {"changed": True, "actions": actions, "server": None, "previous_power": "stopped",
                    "power_after": "stopped", "diff": diff}
        egg = find_egg(client, row["egg"])
        created = create_server(client, {
            "name": spec["name"],
            "external_id": spec.get("external_id"),
            "owner": spec["owner"],
            "egg": row["egg"],
            "image": image,
            "startup": egg.get("startup") or row["startup"],
            "environment": egg_environment(client, egg["nest"], egg["id"], loader, spec["version"],
                                           extra=_extra_environment(spec)),
            "node": spec["node"],
            "limits": want,
            "feature_limits": {"backups": want.get("backups", 2)},
            "port": want.get("port"),
            "additional_ports": want.get("additional_ports"),
            "ip": want.get("ip"),
        }, sleep=sleep)
        return {"changed": True, "actions": actions, "server": created,
                "previous_power": "stopped", "power_after": "stopped", "diff": diff}

    if server.get("egg") is not None:
        egg_ids = [e["id"] for e in client.eggs() if e["name"] == row["egg"]]
        if egg_ids and server["egg"] not in egg_ids:
            raise PterodactylError(
                "%s runs a different egg than loader %r; changing egg is not supported" % (spec["name"], loader)
            )

    identifier = server["identifier"]
    previous_power = power_label(client.power_state(identifier))
    power_after = previous_power

    actions += ensure_details(client, server, {"external_id": spec.get("external_id")}, check_mode, diff)
    changes, build_actions = ensure_build(client, server, want, check_mode, diff)
    actions += build_actions

    current_env = (server.get("container") or {}).get("environment") or {}
    extra = _extra_environment(spec)
    env_changed = {k: v for k, v in extra.items() if current_env.get(k) != v}
    version_changed = current_version(server, loader) != spec["version"]
    image_changed = (server.get("container") or {}).get("image") != image
    # A forced reinstall retries an install that did not take.
    reinstall = version_changed or bool(spec.get("reinstall"))
    startup_changed = version_changed or image_changed or bool(env_changed)
    if startup_changed:
        actions.append("set %s %s on %s" % (loader, spec["version"], image))
        if image_changed:
            record(diff, "startup", "docker_image", (server.get("container") or {}).get("image"), image)
        if version_changed:
            record(diff, "startup", LOADERS[loader]["version_var"], current_version(server, loader), spec["version"])
        for key, new in env_changed.items():
            record(diff, "startup", "environment.%s" % key, current_env.get(key), new)
    if reinstall:
        actions.append("backup, reinstall%s" % ("" if version_changed else " (forced)"))

    if (reinstall or startup_changed) and not check_mode:
        if reinstall:
            if previous_power == "started":
                set_power(client, identifier, "stopped", sleep=sleep)
                power_after = "stopped"
            if backup:
                actions.append("backup: %s" % rotate_and_backup(
                    client, identifier, changes.get("backups", server["feature_limits"]["backups"]), sleep=sleep))
        environment = egg_environment(client, server["nest"], server["egg"], loader, spec["version"], current_env, extra)
        update_startup(
            client, server,
            image=image,
            startup=(server.get("container") or {}).get("startup_command") or row["startup"],
            environment=environment,
        )
        if reinstall:
            jar = environment.get(row["jar_var"])  # the new value: a play may have just changed it
            stamp = jar_stamp(client, server, jar)
            client.reinstall(server["id"])
            wait_installed(client, identifier, "reinstall", sleep)
            check_install_ran(client, server, jar, stamp)
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
        "diff": diff,
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
        result["diff"]["after"]["server"]["mods"] = sorted(w["filename"] for w in wanted)
        return result

    outcome = apply_mods(client, server["identifier"], wanted, purge=purge, check_mode=check_mode,
                         diff=result["diff"])
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
