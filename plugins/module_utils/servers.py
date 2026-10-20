# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Generic Pterodactyl server operations, one group per tab of the panel's server page.

Nothing here knows about Minecraft; minecraft_ops builds on it."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import time

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


# -- diff -------------------------------------------------------------------
def new_diff():
    return {"before": {}, "after": {}}


def record(diff, section, key, before, after):
    """Note one change for --diff. A None collector (no diff wanted) is ignored."""
    if diff is None:
        return
    diff["before"].setdefault(section, {})[key] = before
    diff["after"].setdefault(section, {})[key] = after


# -- lookup -----------------------------------------------------------------
def get_server(client, ref):
    """The server a name, identifier or external ID points at, or an error."""
    server = find_server(client.servers(), external_id=ref, identifier=ref, name=ref)
    if server is None:
        raise PterodactylError("no server matches %r" % ref)
    return server


def _only(items, name, what):
    hits = [i for i in items if i["name"] == name]
    if len(hits) != 1:
        raise PterodactylError("expected one %s named %r, found %d" % (what, name, len(hits)))
    return hits[0]


def wait_installed(client, identifier, what="install", sleep=time.sleep):
    wait_until(lambda: not client.is_installing(identifier), 600, 10, "%s to finish" % what, sleep)


# -- allocations (ports) ----------------------------------------------------
def _describe(allocs):
    return ", ".join(sorted("%s:%s" % (a["ip"], a["port"]) for a in allocs))


def pick_allocation(port, own, free, ip=None):
    """The allocation for a port: one the server already holds, else a free one.

    Raises when there is none, or when the port exists on several IPs and `ip`
    doesn't say which.
    """
    for pool in (own, free):
        hits = [a for a in pool if a["port"] == port and (ip is None or a["ip"] == ip)]
        if len(hits) > 1:
            raise PterodactylError("port %s exists on several IPs (%s); set ip" % (port, _describe(hits)))
        if hits:
            return hits[0]
    raise PterodactylError(
        "the node has no free allocation for port %s%s. It may belong to another server, or it may not "
        "exist; add it under Nodes, Allocation in the panel" % (port, " on %s" % ip if ip else "")
    )


def plan_allocations(node_allocs, own, primary_id, port=None, additional_ports=None, ip=None):
    """What the build call must change to give a server these ports.

    port is the primary (game) port, additional_ports the complete set of the
    others, and either may be None to leave that part alone. Returns
    {allocation, add, remove, changes}, where changes is empty when nothing
    needs to happen. Removed ports are only ever those no longer listed.
    """
    free = [a for a in node_allocs if not a.get("assigned")]
    own_ids = {a["id"] for a in own}
    target = pick_allocation(port, own, free, ip) if port is not None else None
    primary = target["id"] if target else primary_id

    wanted = []
    if additional_ports is not None:
        for extra in additional_ports:
            alloc = pick_allocation(extra, own, free, ip)
            if alloc["id"] == primary:
                raise PterodactylError("port %s is the primary port, so it can't also be an additional port" % extra)
            if alloc["id"] not in [w["id"] for w in wanted]:
                wanted.append(alloc)

    add = ([target] if target and target["id"] not in own_ids else []) + [w for w in wanted if w["id"] not in own_ids]
    remove = []
    if additional_ports is not None:
        keep = {primary} | {w["id"] for w in wanted}
        remove = [a for a in own if a["id"] not in keep]

    ports = {a["id"]: a["port"] for a in list(node_allocs) + list(own)}
    held_after = (own_ids - {a["id"] for a in remove}) | {a["id"] for a in add}
    before_extras = sorted(a["port"] for a in own if a["id"] != primary_id)
    after_extras = sorted(ports[i] for i in held_after if i != primary)

    changes = {}
    if primary != primary_id:
        changes["port"] = target["port"]
    extras_added = [a for a in add if a is not target]
    if extras_added:
        changes["added_ports"] = sorted(a["port"] for a in extras_added)
    if remove:
        changes["removed_ports"] = sorted(a["port"] for a in remove)
    return {
        "allocation": primary,
        "add": [a["id"] for a in add],
        "remove": [a["id"] for a in remove],
        "changes": changes,
        "before": {"port": ports.get(primary_id), "additional_ports": before_extras},
        "after": {"port": ports[primary], "additional_ports": after_extras},
    }


def verify_allocations(client, server, plan):
    """The panel silently skips allocations it won't assign, so check it did."""
    held = {a["id"] for a in client.server_allocations(server["id"])}
    missing = [i for i in plan["add"] if i not in held]
    lingering = [i for i in plan["remove"] if i in held]
    if missing or lingering:
        raise PterodactylError(
            "the panel ignored part of the allocation change (not added: %s, not removed: %s); an allocation "
            "may already be assigned to another server or sit on a different node" % (missing, lingering)
        )


def _creation_allocation(client, node_id, spec):
    """The `allocation` block of a create call: the chosen ports, else the first free allocation."""
    if spec.get("port") is None and spec.get("additional_ports") is None:
        return {"default": client.free_allocation(node_id)}
    if spec.get("port") is None:
        raise PterodactylError("additional_ports needs port, the primary one, to create a server")
    plan = plan_allocations(client.node_allocations(node_id), [], None, spec["port"],
                            spec.get("additional_ports"), spec.get("ip"))
    block = {"default": plan["allocation"]}
    extras = [i for i in plan["add"] if i != plan["allocation"]]
    if extras:
        block["additional"] = extras
    return block


# -- create -----------------------------------------------------------------
def create_server(client, spec, sleep=time.sleep):
    """Create a server and wait for the panel to install it.

    spec: name, external_id, owner, description, egg (name), image, startup,
    environment, node (name), limits (memory/swap/disk/io/cpu) and
    feature_limits (databases/allocations/backups), any limit may be missing.
    """
    limits = spec.get("limits") or {}
    features = spec.get("feature_limits") or {}
    created = client.create_server({
        "name": spec["name"],
        "external_id": spec.get("external_id"),
        "description": spec.get("description") or "",
        "user": spec["owner"],
        "egg": _only(client.eggs(), spec["egg"], "egg")["id"],
        "docker_image": spec["image"],
        "startup": spec["startup"],
        "environment": spec.get("environment") or {},
        "limits": {k: limits.get(k, d) for k, d in (("memory", 1024), ("swap", 0), ("disk", 0), ("io", 500), ("cpu", 0))},
        "feature_limits": {k: features.get(k, 0) for k in ("databases", "allocations", "backups")},
        "allocation": _creation_allocation(client, _only(client.nodes(), spec["node"], "node")["id"], spec),
        "start_on_completion": False,
    })
    # Files and power calls fail until the panel finishes installing it.
    wait_installed(client, created["identifier"], sleep=sleep)
    return created


# -- details tab ------------------------------------------------------------
def details_diff(server, want):
    """Detail fields that differ. `want` holds only the fields the user set."""
    current = {
        "name": server["name"],
        "external_id": server.get("external_id"),
        "description": server.get("description") or "",
        "owner": server["user"],
    }
    return {k: v for k, v in want.items() if v is not None and current[k] != v}


def ensure_details(client, server, want, check_mode=False, diff=None):
    """Converge name, external_id, description and owner. Returns action strings."""
    changes = details_diff(server, want)
    if not changes:
        return []
    current = {"name": server["name"], "external_id": server.get("external_id"),
               "description": server.get("description") or "", "owner": server["user"]}
    for key, new in changes.items():
        record(diff, "details", key, current[key], new)
    if not check_mode:
        client.update_details(server["id"], {
            "name": changes.get("name", server["name"]),
            "user": changes.get("owner", server["user"]),
            "external_id": changes.get("external_id", server.get("external_id")),
            "description": changes.get("description", server.get("description") or ""),
        })
    return ["update details: %s" % ", ".join("%s=%s" % kv for kv in sorted(changes.items()))]


# -- build configuration tab ------------------------------------------------
LIMIT_KEYS = ("memory", "swap", "disk", "io", "cpu")
FEATURE_KEYS = ("databases", "allocations", "backups")


def limits_diff(server, want):
    """Limit fields that differ. `want` holds only the fields the user set."""
    changes = {}
    for key in LIMIT_KEYS:
        if want.get(key) is not None and want[key] != server["limits"].get(key):
            changes[key] = want[key]
    for key in FEATURE_KEYS:
        if want.get(key) is not None and want[key] != server["feature_limits"].get(key):
            changes[key] = want[key]
    return changes


def build_payload(server, changes, plan=None):
    limits = server["limits"]
    features = server["feature_limits"]
    payload = {
        "allocation": plan["allocation"] if plan else server["allocation"],
        "threads": limits.get("threads"),
        "oom_disabled": limits.get("oom_disabled", True),
        "feature_limits": {k: changes.get(k, features[k]) for k in FEATURE_KEYS},
    }
    payload.update({k: changes.get(k, limits[k]) for k in LIMIT_KEYS})
    if plan and plan["add"]:
        payload["add_allocations"] = plan["add"]
    if plan and plan["remove"]:
        payload["remove_allocations"] = plan["remove"]
    return payload


def ensure_build(client, server, want, check_mode=False, diff=None):
    """Converge limits and allocations (the game port and any additional ports).

    `want` holds only what the user set. Besides the limit keys it may carry
    port, additional_ports and ip. The node's allocations are only read when
    one of the ports is set. Returns (changes, actions).
    """
    changes = limits_diff(server, want)
    plan = None
    if want.get("port") is not None or want.get("additional_ports") is not None:
        plan = plan_allocations(
            client.node_allocations(server["node"]),
            client.server_allocations(server["id"]),
            server["allocation"],
            port=want.get("port"),
            additional_ports=want.get("additional_ports"),
            ip=want.get("ip"),
        )
        changes.update(plan["changes"])
    if not changes:
        return {}, []
    for key, new in limits_diff(server, want).items():
        old = server["limits"].get(key) if key in LIMIT_KEYS else server["feature_limits"].get(key)
        record(diff, "build", key, old, new)
    if plan and plan["changes"]:
        for key in ("port", "additional_ports"):
            if plan["before"][key] != plan["after"][key]:
                record(diff, "ports", key, plan["before"][key], plan["after"][key])
    if not check_mode:
        client.update_build(server["id"], build_payload(server, changes, plan if plan and plan["changes"] else None))
        if plan and plan["changes"]:
            verify_allocations(client, server, plan)
    return changes, ["update build: %s" % ", ".join("%s=%s" % kv for kv in sorted(changes.items()))]


# -- startup tab ------------------------------------------------------------
def startup_diff(server, image=None, startup=None, environment=None):
    """Startup fields that differ from what the server has."""
    container = server.get("container") or {}
    have_env = container.get("environment") or {}
    changes = {}
    if image is not None and container.get("image") != image:
        changes["image"] = image
    if startup is not None and container.get("startup_command") != startup:
        changes["startup"] = startup
    env = {k: v for k, v in (environment or {}).items() if have_env.get(k) != v}
    if env:
        changes["environment"] = env
    return changes


def update_startup(client, server, image=None, startup=None, environment=None):
    """Send the startup tab. The server's own values fill whatever isn't given."""
    container = server.get("container") or {}
    client.update_startup(server["id"], {
        "startup": startup or container.get("startup_command"),
        "environment": environment or {},
        "egg": server["egg"],
        "image": image or container.get("image"),
        "skip_scripts": False,
    })


def ensure_startup(client, server, image=None, startup=None, environment=None, reinstall=False,
                   check_mode=False, sleep=time.sleep, diff=None):
    """Converge the Docker image, startup command and environment variables.

    Returns (changes, actions). With reinstall, a change also reinstalls the
    server and waits for it. Stopping the server first is the caller's job.
    """
    changes = startup_diff(server, image, startup, environment)
    if not changes:
        return {}, []
    container = server.get("container") or {}
    if "image" in changes:
        record(diff, "startup", "docker_image", container.get("image"), changes["image"])
    if "startup" in changes:
        record(diff, "startup", "startup", container.get("startup_command"), changes["startup"])
    for key, new in changes.get("environment", {}).items():
        record(diff, "startup", "environment.%s" % key, (container.get("environment") or {}).get(key), new)
    actions = ["update startup: %s" % ", ".join(sorted(changes))]
    if not check_mode:
        update_startup(client, server, image, startup, environment)
        if reinstall:
            client.reinstall(server["id"])
            wait_installed(client, server["identifier"], "reinstall", sleep)
    if reinstall:
        actions.append("reinstall")
    return changes, actions
