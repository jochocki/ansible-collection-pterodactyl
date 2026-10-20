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


def resolve_mods(version, loader, projects, fetch):
    """Resolve every project to the file to install, or raise listing all failures.

    Reads nothing from, and changes nothing on, the server, so callers run it
    first: a bad project name then can't leave a half-updated server.
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
    return wanted


def apply_mods(client, identifier, wanted, purge=True, check_mode=False, diff=None, directory=MODS_DIR):
    """Install, verify and (optionally) prune `directory`. Returns a result dict."""
    present = client.list_files(identifier, directory)
    created_dir = False
    if present is None:
        present = []
        created_dir = bool(wanted)
        if created_dir and not check_mode:
            client.create_folder(identifier, "/", directory.strip("/"))

    pull, keep, stale = plan(wanted, present)
    # A same-named jar with the wrong size is re-pulled: remove it first.
    replace = [p["filename"] for p in pull if any(f["name"] == p["filename"] for f in present)]
    removals = sorted(set(replace) | (set(stale) if purge else set()))
    changed = bool(pull or removals or created_dir)

    if changed and diff is not None:
        names = sorted(f["name"] for f in present if f["name"].endswith(".jar"))
        after = sorted((set(names) | {p["filename"] for p in pull}) - set(removals))
        diff["before"].setdefault("mods", {})["files"] = names
        diff["after"].setdefault("mods", {})["files"] = after

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
        client.delete_files(identifier, directory, replace)
    for item in pull:
        client.pull_file(identifier, item["url"], directory, item["filename"])
        data = client.read_file(identifier, "%s/%s" % (directory, item["filename"]))
        if modrinth.sha512_hex(data) != item["sha512"]:
            client.delete_files(identifier, directory, [item["filename"]])
            raise PterodactylError("sha512 mismatch for %s; file removed" % item["filename"])
    # Stale jars go last: if a pull above fails, the old mods are still there.
    if purge and stale:
        client.delete_files(identifier, directory, stale)
    return result


def list_jars(client, identifier, directory=MODS_DIR):
    """The .jar files in a server's mods directory, sorted. Empty if the directory does not exist."""
    return sorted(f["name"] for f in (client.list_files(identifier, directory) or []) if f["name"].endswith(".jar"))


def audit_unmanaged(client, identifier, game_version, loader, post, limit=40):
    """Say which of a server's existing mods work with `game_version`, by asking Modrinth about each jar.

    Used when the version changes on a server whose mods are not managed. Returns a list of
    {file, status, detail} with status compatible, incompatible or unknown (not on Modrinth, or
    the lookup failed), and None when there is nothing to check or too much to download.
    """
    row = LOADERS[loader]
    if not row["mod_loaders"]:
        return None
    directory = row["mods_dir"]
    jars = list_jars(client, identifier, directory)
    if not jars or len(jars) > limit:
        return None
    hashes = {}
    for name in jars:
        hashes[name] = modrinth.sha512_hex(client.read_file(identifier, "%s/%s" % (directory, name)))
    try:
        known = modrinth.identify(set(hashes.values()), post)
    except (HttpError, ValueError):
        known = {}
    report = []
    for name in jars:
        version = known.get(hashes[name])
        if version is None:
            report.append({"file": name, "status": "unknown", "detail": "not found on Modrinth"})
            continue
        fits_game, fits_loader = modrinth.supports(version, game_version, row["mod_loaders"])
        if fits_game and fits_loader:
            report.append({"file": name, "status": "compatible", "detail": version.get("version_number")})
        else:
            games = version.get("game_versions", [])
            report.append({"file": name, "status": "incompatible",
                           "detail": "built for Minecraft %s" % (", ".join(games[:3]) + (" and later" if len(games) > 3 else ""))})
    return report


def sync_mods(client, identifier, version, loader, projects, fetch, purge=True, check_mode=False, diff=None):
    """Resolve, then apply."""
    return apply_mods(client, identifier, resolve_mods(version, loader, projects, fetch), purge, check_mode, diff,
                      LOADERS[loader]["mods_dir"])
