# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Resolve a Modrinth project to the file a server should hold."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import hashlib

from ansible.module_utils.six.moves.urllib.parse import quote

API = "https://api.modrinth.com/v2"


class ModrinthError(Exception):
    pass


def pick_version(project, versions, game_version, loaders):
    """Newest release that matches both the game version and a loader.

    Falls back to beta/alpha only when no release exists. The API already
    filters by query, but the filter is repeated here so a surprise in the
    response can't install a wrong-version jar.
    """
    matching = [
        v for v in versions
        if game_version in v.get("game_versions", [])
        and any(l in v.get("loaders", []) for l in loaders)
    ]
    if not matching:
        raise ModrinthError(
            "%s has no version for Minecraft %s with loader %s"
            % (project, game_version, "/".join(loaders))
        )
    releases = [v for v in matching if v.get("version_type") == "release"]
    pool = releases or matching
    return max(pool, key=lambda v: v.get("date_published", ""))


def pick_file(project, version):
    files = version.get("files") or []
    if not files:
        raise ModrinthError("%s %s has no files" % (project, version.get("version_number")))
    primary = [f for f in files if f.get("primary")]
    return (primary or files)[0]


def resolve(project, game_version, loaders, fetch):
    """Return a dict describing the file to install.

    fetch is a callable taking a URL and returning parsed JSON.
    """
    query = "loaders=%s&game_versions=%s" % (
        quote(json.dumps(list(loaders)), safe=""),
        quote(json.dumps([game_version]), safe=""),
    )
    versions = fetch("%s/project/%s/version?%s" % (API, quote(project, safe=""), query))
    version = pick_version(project, versions, game_version, loaders)
    fileinfo = pick_file(project, version)
    sha512 = (fileinfo.get("hashes") or {}).get("sha512")
    if not sha512:
        raise ModrinthError("%s %s has no sha512 to verify" % (project, version.get("version_number")))
    return {
        "project": project,
        "version": version.get("version_number"),
        "filename": fileinfo["filename"],
        "url": fileinfo["url"],
        "size": fileinfo.get("size"),
        "sha512": sha512,
    }


def identify(hashes, post):
    """Which Modrinth versions do these file hashes belong to? {sha512: version}, unknown hashes absent.

    post is a callable taking (url, body) and returning parsed JSON.
    """
    if not hashes:
        return {}
    return post("%s/version_files" % API, {"hashes": sorted(hashes), "algorithm": "sha512"})


def supports(version, game_version, loaders):
    """(works with the game version, works with a loader) for a Modrinth version object."""
    return (game_version in version.get("game_versions", []),
            any(l in version.get("loaders", []) for l in loaders))


def sha512_hex(data):
    return hashlib.sha512(data).hexdigest()
