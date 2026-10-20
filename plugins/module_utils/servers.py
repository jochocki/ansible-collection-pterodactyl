# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Server lookup, power, backups and the Minecraft server lifecycle."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import time

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import (
    LOADERS,
    java_image,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import (
    PterodactylError,
    wait_until,
)

RUNNING = ("running", "starting")


def find_server(servers, external_id=None, identifier=None, name=None):
    """Pick one server. external_id wins, then identifier, then exact name."""
    if external_id:
        hits = [s for s in servers if s.get("external_id") == external_id]
        if hits:
            return hits[0]
    if identifier:
        hits = [s for s in servers if s.get("identifier") == identifier]
        if hits:
            return hits[0]
    if name:
        hits = [s for s in servers if s.get("name") == name]
        if len(hits) > 1:
            raise PterodactylError(
                "%d servers are named %r; set external_id to tell them apart" % (len(hits), name)
            )
        if hits:
            return hits[0]
    return None


def power_label(current_state):
    """Map a panel state to the value pterodactyl_power takes as `state`."""
    return "started" if current_state in RUNNING else "stopped"


# -- backups ----------------------------------------------------------------
def rotate_and_backup(client, identifier, limit, timeout=600, interval=10, sleep=time.sleep):
    """Take a backup, freeing a slot first if the server is at its limit.

    Returns a short description of what happened. A limit of 0 means the
    panel would refuse the backup, so it is skipped rather than failing.
    """
    if limit == 0:
        return "skipped: backup limit is 0"
    existing = client.backups(identifier)
    if len(existing) >= limit:
        deletable = [b for b in existing if not b.get("is_locked")]
        if not deletable:
            raise PterodactylError("all %d backups are locked; cannot make room for a new one" % len(existing))
        oldest = min(deletable, key=lambda b: b["created_at"])
        client.delete_backup(identifier, oldest["uuid"])
    created = client.create_backup(identifier)
    uuid = created["uuid"]

    def done():
        for b in client.backups(identifier):
            if b["uuid"] == uuid:
                if b.get("completed_at") and not b.get("is_successful"):
                    raise PterodactylError("backup %s failed" % uuid)
                return b.get("is_successful")
        return False

    wait_until(done, timeout, interval, "backup %s" % uuid, sleep)
    return "created %s" % uuid


# -- power ------------------------------------------------------------------
def set_power(client, identifier, state, wait=True, timeout=120, interval=3, sleep=time.sleep):
    """Move a server to `state` (started, stopped, restarted, killed).

    Returns True when a signal was sent.
    """
    current = power_label(client.power_state(identifier))
    if state in ("started", "stopped") and current == state:
        return False
    signal = {"started": "start", "stopped": "stop", "restarted": "restart", "killed": "kill"}[state]
    client.send_power(identifier, signal)
    if wait and state in ("started", "restarted"):
        wait_until(lambda: client.power_state(identifier) == "running", timeout, interval, "server to run", sleep)
    elif wait and state in ("stopped", "killed"):
        wait_until(lambda: client.power_state(identifier) == "offline", timeout, interval, "server to stop", sleep)
    return True


# -- minecraft server -------------------------------------------------------
def desired_environment(loader, version):
    row = LOADERS[loader]
    env = dict(row["environment"])
    env[row["version_var"]] = version
    return env


def current_version(server, loader):
    env = (server.get("container") or {}).get("environment") or {}
    return env.get(LOADERS[loader]["version_var"])


def limits_diff(server, want):
    """Limit fields that differ. `want` holds only the fields the user set."""
    changes = {}
    for key in ("memory", "swap", "disk", "io", "cpu"):
        if want.get(key) is not None and want[key] != server["limits"].get(key):
            changes[key] = want[key]
    if want.get("backups") is not None and want["backups"] != server["feature_limits"].get("backups"):
        changes["backups"] = want["backups"]
    return changes


def build_payload(server, changes):
    limits = server["limits"]
    features = server["feature_limits"]
    return {
        "allocation": server["allocation"],
        "memory": changes.get("memory", limits["memory"]),
        "swap": changes.get("swap", limits["swap"]),
        "disk": changes.get("disk", limits["disk"]),
        "io": changes.get("io", limits["io"]),
        "cpu": changes.get("cpu", limits["cpu"]),
        "threads": limits.get("threads"),
        "oom_disabled": limits.get("oom_disabled", True),
        "feature_limits": {
            "databases": features["databases"],
            "allocations": features["allocations"],
            "backups": changes.get("backups", features["backups"]),
        },
    }


def ensure_minecraft_server(client, spec, check_mode=False, restore_power=True, backup=True, sleep=time.sleep):
    """Create or converge one Minecraft server.

    spec keys: name, external_id, loader, version, node, owner, limits (dict
    of memory/swap/disk/io/cpu/backups, any may be None).
    Returns {changed, actions, server, previous_power}.
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
            return {"changed": True, "actions": actions, "server": None, "previous_power": "stopped"}
        egg = [e for e in client.eggs() if e["name"] == row["egg"]]
        if len(egg) != 1:
            raise PterodactylError("expected one egg named %r, found %d" % (row["egg"], len(egg)))
        node = [n for n in client.nodes() if n["name"] == spec["node"]]
        if len(node) != 1:
            raise PterodactylError("expected one node named %r, found %d" % (spec["node"], len(node)))
        created = client.create_server({
            "name": spec["name"],
            "external_id": spec.get("external_id"),
            "user": spec["owner"],
            "egg": egg[0]["id"],
            "docker_image": image,
            "startup": row["startup"],
            "environment": desired_environment(loader, spec["version"]),
            "limits": {k: want.get(k, d) for k, d in (("memory", 1024), ("swap", 0), ("disk", 0), ("io", 500), ("cpu", 0))},
            "feature_limits": {"databases": 0, "allocations": 0, "backups": want.get("backups", 2)},
            "allocation": {"default": client.free_allocation(node[0]["id"])},
            "start_on_completion": False,
        })
        return {"changed": True, "actions": actions, "server": created, "previous_power": "stopped"}

    if server.get("egg") is not None:
        egg_id = [e["id"] for e in client.eggs() if e["name"] == row["egg"]]
        if egg_id and server["egg"] not in egg_id:
            raise PterodactylError(
                "%s runs a different egg than loader %r; changing egg is not supported" % (spec["name"], loader)
            )

    identifier = server["identifier"]

    if spec.get("external_id") and server.get("external_id") != spec["external_id"]:
        actions.append("set external_id %s" % spec["external_id"])
        if not check_mode:
            client.update_details(server["id"], {
                "name": server["name"],
                "user": server["user"],
                "external_id": spec["external_id"],
                "description": server.get("description") or "",
            })

    changes = limits_diff(server, want)
    if changes:
        actions.append("update limits %s" % ", ".join("%s=%s" % kv for kv in sorted(changes.items())))
        if not check_mode:
            client.update_build(server["id"], build_payload(server, changes))

    version_changed = current_version(server, loader) != spec["version"]
    image_changed = (server.get("container") or {}).get("image") != image
    previous_power = "stopped"
    if version_changed or image_changed:
        actions.append("set %s %s on %s" % (loader, spec["version"], image))
    if version_changed:
        actions.append("backup, reinstall")

    if (version_changed or image_changed) and not check_mode:
        previous_power = power_label(client.power_state(identifier))
        if version_changed:
            if previous_power == "started":
                set_power(client, identifier, "stopped", sleep=sleep)
            if backup:
                actions.append("backup: %s" % rotate_and_backup(
                    client, identifier, changes.get("backups", server["feature_limits"]["backups"]), sleep=sleep))
        client.update_startup(server["id"], {
            "startup": (server.get("container") or {}).get("startup_command") or row["startup"],
            "environment": desired_environment(loader, spec["version"]),
            "egg": server["egg"],
            "image": image,
            "skip_scripts": False,
        })
        if version_changed:
            client.reinstall(server["id"])
            wait_until(lambda: not client.is_installing(identifier), 600, 10, "reinstall to finish", sleep)
            if restore_power and previous_power == "started":
                set_power(client, identifier, "started", sleep=sleep)
        elif previous_power == "started":
            actions.append("image applies on next restart")
    elif version_changed or image_changed:
        previous_power = "started"  # unknown in check mode; assume the common case

    return {
        "changed": bool(actions),
        "actions": actions,
        "server": server,
        "previous_power": previous_power,
    }
