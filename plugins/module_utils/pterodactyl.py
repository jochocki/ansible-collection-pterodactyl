# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Pterodactyl panel client covering the application and client APIs."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import time

from ansible.module_utils.six.moves.urllib.parse import urlencode

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import http as phttp


class PterodactylError(Exception):
    def __init__(self, message, status=None):
        super(PterodactylError, self).__init__(message)
        self.status = status


def wait_until(predicate, timeout, interval, what, sleep=time.sleep):
    """Poll predicate() until truthy. Raises PterodactylError on timeout."""
    waited = 0
    while True:
        value = predicate()
        if value:
            return value
        if waited >= timeout:
            raise PterodactylError("timed out after %ss waiting for %s" % (timeout, what))
        sleep(interval)
        waited += interval


class PterodactylClient(object):
    def __init__(self, url, api_key, validate_certs=True, timeout=60, http=phttp.request):
        self.base = url.rstrip("/")
        self.validate_certs = validate_certs
        self.timeout = timeout
        self._http = http
        self._headers = {
            "Authorization": "Bearer %s" % api_key,
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Content-Type": "application/json",
        }

    # -- plumbing ---------------------------------------------------------
    def call(self, method, path, body=None, params=None, ok=(200, 201, 202, 204)):
        url = self.base + path
        if params:
            url += "?" + urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self._http(method, url, self._headers, data, self.timeout, self.validate_certs)
        if status not in ok:
            raise PterodactylError(
                "%s %s -> HTTP %s: %s" % (method, path, status, raw.decode("utf-8", "replace")[:300]),
                status=status,
            )
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return None

    def paginate(self, path, params=None):
        """All `attributes` dicts of a paginated list endpoint."""
        items, page = [], 1
        while True:
            query = dict(params or {}, per_page=100, page=page)
            doc = self.call("GET", path, params=query)
            items.extend(obj["attributes"] for obj in doc["data"])
            pagination = doc.get("meta", {}).get("pagination", {})
            if page >= pagination.get("total_pages", 1):
                return items
            page += 1

    # -- application API --------------------------------------------------
    def servers(self):
        return self.paginate("/api/application/servers")

    def nodes(self):
        return self.paginate("/api/application/nodes")

    def eggs(self):
        """Every egg, flattened across nests."""
        eggs = []
        for nest in self.paginate("/api/application/nests"):
            doc = self.call("GET", "/api/application/nests/%s" % nest["id"], params={"include": "eggs"})
            for egg in doc["attributes"]["relationships"]["eggs"]["data"]:
                eggs.append(egg["attributes"])
        return eggs

    def node_allocations(self, node_id):
        """Every allocation on a node: id, ip, port and whether it is assigned."""
        return self.paginate("/api/application/nodes/%s/allocations" % node_id)

    def server_allocations(self, server_id):
        """The allocations assigned to one server (its primary among them)."""
        doc = self.call("GET", "/api/application/servers/%s" % server_id, params={"include": "allocations"})
        return [a["attributes"] for a in doc["attributes"]["relationships"]["allocations"]["data"]]

    def free_allocation(self, node_id):
        for alloc in self.paginate("/api/application/nodes/%s/allocations" % node_id):
            if not alloc.get("assigned"):
                return alloc["id"]
        raise PterodactylError("node %s has no free allocation" % node_id)

    def create_server(self, payload):
        return self.call("POST", "/api/application/servers", body=payload)["attributes"]

    def update_details(self, server_id, payload):
        return self.call("PATCH", "/api/application/servers/%s/details" % server_id, body=payload)

    def update_build(self, server_id, payload):
        return self.call("PATCH", "/api/application/servers/%s/build" % server_id, body=payload)

    def update_startup(self, server_id, payload):
        return self.call("PATCH", "/api/application/servers/%s/startup" % server_id, body=payload)

    def reinstall(self, server_id):
        return self.call("POST", "/api/application/servers/%s/reinstall" % server_id)

    def delete_server(self, server_id):
        return self.call("DELETE", "/api/application/servers/%s" % server_id)

    # -- client API -------------------------------------------------------
    def _c(self, identifier, suffix=""):
        return "/api/client/servers/%s%s" % (identifier, suffix)

    def power_state(self, identifier):
        return self.call("GET", self._c(identifier, "/resources"))["attributes"]["current_state"]

    def send_power(self, identifier, signal):
        self.call("POST", self._c(identifier, "/power"), body={"signal": signal})

    def is_installing(self, identifier):
        return bool(self.call("GET", self._c(identifier))["attributes"].get("is_installing"))

    def backups(self, identifier):
        doc = self.call("GET", self._c(identifier, "/backups"))
        return [b["attributes"] for b in doc["data"]]

    def create_backup(self, identifier):
        return self.call("POST", self._c(identifier, "/backups"), body={})["attributes"]

    def delete_backup(self, identifier, uuid):
        self.call("DELETE", self._c(identifier, "/backups/%s" % uuid))

    def list_files(self, identifier, directory):
        """File names in a directory, or None when the directory does not exist.

        The panel answers 500 for a missing directory, so 404 and 500 both
        mean "not there" and anything else is a real error.
        """
        try:
            doc = self.call("GET", self._c(identifier, "/files/list"), params={"directory": directory})
        except PterodactylError as exc:
            if exc.status in (404, 500):
                return None
            raise
        return [dict(f["attributes"]) for f in doc["data"]]

    def create_folder(self, identifier, root, name):
        self.call("POST", self._c(identifier, "/files/create-folder"), body={"root": root, "name": name})

    def delete_files(self, identifier, root, files):
        self.call("POST", self._c(identifier, "/files/delete"), body={"root": root, "files": files})

    def pull_file(self, identifier, url, directory, filename):
        # foreground makes the panel block until the download finishes.
        self.call(
            "POST",
            self._c(identifier, "/files/pull"),
            body={"url": url, "directory": directory, "filename": filename, "foreground": True},
        )

    def read_file(self, identifier, path):
        """Bytes of a file, fetched through the panel's signed download URL."""
        doc = self.call("GET", self._c(identifier, "/files/download"), params={"file": path})
        status, raw = self._http("GET", doc["attributes"]["url"], {}, None, self.timeout, self.validate_certs)
        if status != 200:
            raise PterodactylError("download of %s failed with HTTP %s" % (path, status), status=status)
        return raw
