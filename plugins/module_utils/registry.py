# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Does a container image still exist? Asks the registry, anonymously, the way a pull would."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import re

from ansible.module_utils.six.moves.urllib.parse import urlencode

from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError, request_with_headers

MANIFEST_TYPES = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

# Docker Hub's API host is not the name in an image reference.
REGISTRY_HOSTS = {"docker.io": "registry-1.docker.io", "index.docker.io": "registry-1.docker.io"}


def parse_image(ref):
    """Split a reference into (registry, repository, tag-or-digest), with Docker Hub's defaults."""
    name, reference = ref, "latest"
    if "@" in ref:
        name, reference = ref.split("@", 1)
    else:
        last = ref.rsplit("/", 1)[-1]
        if ":" in last:
            name, reference = ref.rsplit(":", 1)
    parts = name.split("/")
    registry = "docker.io"
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, parts = parts[0], parts[1:]
    repo = "/".join(parts)
    if registry == "docker.io" and "/" not in repo:
        repo = "library/" + repo  # official images
    return registry, repo, reference


def _token(challenge, repo, http):
    """A pull token for the realm a registry named in its 401 challenge."""
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.get("realm")
    if not realm:
        return None
    query = {"scope": fields.get("scope") or "repository:%s:pull" % repo}
    if fields.get("service"):
        query["service"] = fields["service"]
    status, body, _ = http("GET", "%s?%s" % (realm, urlencode(query)))
    if status != 200:
        return None
    doc = json.loads(body.decode("utf-8"))
    return doc.get("token") or doc.get("access_token")


def check_image(ref, http=request_with_headers):
    """'exists', 'missing', or 'unknown: <why>'. Never raises on a registry answer it doesn't understand."""
    registry, repo, reference = parse_image(ref)
    url = "https://%s/v2/%s/manifests/%s" % (REGISTRY_HOSTS.get(registry, registry), repo, reference)
    headers = {"Accept": MANIFEST_TYPES}
    try:
        status, _, resp = http("HEAD", url, headers)
        if status == 401:
            token = _token(resp.get("www-authenticate", ""), repo, http)
            if not token:
                return "unknown: %s wants credentials" % registry
            status, _, resp = http("HEAD", url, dict(headers, Authorization="Bearer %s" % token))
    except HttpError as exc:
        return "unknown: %s" % exc
    if status == 200:
        return "exists"
    if status == 404:
        return "missing"
    return "unknown: HTTP %s from %s" % (status, registry)
