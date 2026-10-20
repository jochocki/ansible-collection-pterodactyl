# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Converge a server's /mods directory to a list of Modrinth projects."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import modrinth
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.minecraft import LOADERS
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError

MODS_DIR = "/mods"


def plan(wanted, present):
    """Split resolved files and the directory listing into pull / keep / stale.

    wanted: resolved dicts from modrinth.resolve.
    present: file attribute dicts (name, size, is_file) from the panel.
    A file already on the server counts only if name and size both match.
    """
    on_disk = {f["name"]: f for f in present if f.get("is_file", True)}
    wanted_names = {w["filename"] for w in wanted}
    pull, keep = [], []
    for item in wanted:
        existing = on_disk.get(item["filename"])
        size_ok = item.get("size") is None or (existing and existing.get("size") == item["size"])
        (keep if existing and size_ok else pull).append(item)
    stale = sorted(n for n in on_disk if n.endswith(".jar") and n not in wanted_names)
    return pull, keep, stale


def sync_mods(client, identifier, version, loader, projects, fetch, purge=True, check_mode=False):
    """Install, verify and (optionally) prune. Returns a result dict.

    Every project resolves before anything changes on the server, so one bad
    project name can't leave a half-updated mods directory.
    """
    row = LOADERS[loader]
    if not row["mod_loaders"]:
        raise PterodactylError("loader %r does not support mods" % loader)

    wanted, errors = [], []
    for project in projects:
        try:
            wanted.append(modrinth.resolve(project, version, row["mod_loaders"], fetch))
        except modrinth.ModrinthError as exc:
            errors.append(str(exc))
        except HttpError as exc:
            if exc.status != 404:
                raise
            errors.append("%s is not a Modrinth project (use the slug from its URL, or its ID)" % project)
    if errors:
        raise PterodactylError("cannot resolve mods: " + "; ".join(errors))

    present = client.list_files(identifier, MODS_DIR)
    created_dir = False
    if present is None:
        created_dir = True
        present = []
        if not check_mode:
            client.create_folder(identifier, "/", "mods")

    pull, keep, stale = plan(wanted, present)
    # A same-named jar with the wrong size is re-pulled: remove it first.
    replace = [p["filename"] for p in pull if any(f["name"] == p["filename"] for f in present)]
    removals = sorted(set(replace) | (set(stale) if purge else set()))
    changed = bool(pull or removals or created_dir)

    result = {
        "changed": changed,
        "installed": [p["filename"] for p in pull],
        "unchanged": [k["filename"] for k in keep],
        "removed": removals,
        "left_in_place": [] if purge else stale,
    }
    if check_mode or not changed:
        return result

    if replace:
        client.delete_files(identifier, MODS_DIR, replace)
    for item in pull:
        client.pull_file(identifier, item["url"], MODS_DIR, item["filename"])
        data = client.read_file(identifier, "%s/%s" % (MODS_DIR, item["filename"]))
        if modrinth.sha512_hex(data) != item["sha512"]:
            client.delete_files(identifier, MODS_DIR, [item["filename"]])
            raise PterodactylError("sha512 mismatch for %s; file removed" % item["filename"])
    # Stale jars go last: if a pull above fails, the old mods are still there.
    if purge and stale:
        client.delete_files(identifier, MODS_DIR, stale)
    return result
