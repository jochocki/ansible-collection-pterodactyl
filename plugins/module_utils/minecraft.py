# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Minecraft version parsing, Java selection and the per-loader egg table."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

JAVA_IMAGE = "ghcr.io/pterodactyl/yolks:java_{}"

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

# (minimum Minecraft version, Java major). Highest matching row wins.
# Year-numbered releases (26.x) need Java 25.
JAVA_MINIMUMS = (
    ((1, 0, 0), 8),
    ((1, 17, 0), 17),
    ((1, 20, 5), 21),
    ((26, 0, 0), 25),
)

_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

# Everything a loader needs from the panel and from Modrinth. One row per
# supported loader, so adding one is a data change. The egg's own variables, their names
# and their defaults come from the panel, not from here, so a new egg version needs no
# change; only the one that holds the Minecraft version (version_var) is named.
LOADERS = {
    "fabric": {
        "egg": "Fabric",
        "version_var": "MC_VERSION",
        "jar_var": "SERVER_JARFILE",
        "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar {{SERVER_JARFILE}}",
        "mod_loaders": ("fabric",),
        "mods_dir": "/mods",
    },
    "paper": {
        "egg": "Paper",
        "version_var": "MINECRAFT_VERSION",
        "jar_var": "SERVER_JARFILE",
        "startup": "java -Xms128M -XX:MaxRAMPercentage=95.0 -jar {{SERVER_JARFILE}}",
        "mod_loaders": ("paper", "spigot", "bukkit"),
        "mods_dir": "/plugins",
    },
    "vanilla": {
        "egg": "Vanilla Minecraft",
        "version_var": "VANILLA_VERSION",
        "jar_var": "SERVER_JARFILE",
        "startup": "java -Xms128M -XX:MaxRAMPercentage=95.0 -jar {{SERVER_JARFILE}}",
        "mod_loaders": (),
    },
}


def parse_version(value):
    """Turn "1.21.4", "1.20" or "26.3" into a comparable (major, minor, patch)."""
    text = str(value).strip()
    if not _VERSION_RE.match(text):
        raise ValueError("not a Minecraft release version: %r" % (value,))
    parts = [int(p) for p in text.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def java_major(version):
    parsed = parse_version(version)
    major = JAVA_MINIMUMS[0][1]
    for minimum, java in JAVA_MINIMUMS:
        if parsed >= minimum:
            major = java
    return major


def java_image(version):
    return JAVA_IMAGE.format(java_major(version))


def release_ids(manifest):
    """Release version ids from Mojang's version manifest."""
    return {v["id"] for v in manifest.get("versions", []) if v.get("type") == "release"}


def check_version(version, known):
    """Fail on a version Mojang never shipped.

    YAML turns an unquoted 1.20 into the float 1.2, and "1.2" parses fine, so
    parsing alone can't catch it. The manifest can.
    """
    parse_version(version)
    if version not in known:
        raise ValueError(
            "%r is not a released Minecraft version. Quote versions in YAML "
            "(1.20 unquoted becomes 1.2)." % (version,)
        )
