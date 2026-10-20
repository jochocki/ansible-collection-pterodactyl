"""A recording stand-in for PterodactylClient."""
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError


def server(**over):
    base = {
        "id": 27, "identifier": "650fdf18", "uuid": "9e72677e-dba3-4ece-924c-32339960619b",
        "name": "Tiny Animals", "external_id": "tiny-animals",
        "user": 1, "node": 1, "egg": 15, "allocation": 9, "description": "",
        "limits": {"memory": 3000, "swap": 0, "disk": 500, "io": 500, "cpu": 300, "threads": None, "oom_disabled": True},
        "feature_limits": {"databases": 0, "allocations": 0, "backups": 2},
        "container": {
            "image": "ghcr.io/pterodactyl/yolks:java_21",
            "startup_command": "java -jar {{SERVER_JARFILE}}",
            "environment": {"MC_VERSION": "1.21.11", "SERVER_JARFILE": "fabric-server-launch.jar"},
        },
    }
    base.update(over)
    return base


class FakeClient(object):
    def __init__(self, servers=None, state="running", backups=None, files=None, contents=None, root=None):
        self._servers = servers if servers is not None else []
        self.state = state
        self._backups = backups if backups is not None else []
        self.files = files
        self.contents = contents or {}
        self.calls = []
        self.installing = 0
        self.fail_pull = False
        # Allocations on the node: 9 is this server's primary, 79 belongs to another server.
        self.node_allocs = [
            {"id": 9, "ip": "0.0.0.0", "port": 25565, "assigned": True},
            {"id": 77, "ip": "0.0.0.0", "port": 25566, "assigned": False},
            {"id": 78, "ip": "0.0.0.0", "port": 25567, "assigned": False},
            {"id": 79, "ip": "0.0.0.0", "port": 25568, "assigned": True},
            {"id": 80, "ip": "10.0.0.1", "port": 25569, "assigned": False},
            {"id": 81, "ip": "10.0.0.2", "port": 25569, "assigned": False},
        ]
        self.own = {9}
        self.primary = 9
        self.ignore_allocation_changes = False  # the panel skips them silently
        self.root = root if root is not None else []  # the server's / directory
        self.rewrites = ["fabric-server-launch.jar"]  # what a reinstall that really ran rewrites
        self._clock = 1000
        self.install_status = None  # "install_failed" / "reinstall_failed" after a failed install
        self.reads = []

    def names(self):
        return [c[0] for c in self.calls]

    def _log(self, *call):
        self.calls.append(call)

    # application
    def servers(self):
        return list(self._servers)

    def nodes(self):
        return [{"id": 3, "name": "wings01"}]

    def eggs(self):
        return [{"id": 15, "name": "Fabric"}, {"id": 5, "name": "Vanilla Minecraft"}, {"id": 3, "name": "Paper"}]

    def free_allocation(self, node_id):
        return 77

    def create_server(self, payload):
        self._log("create_server", payload)
        return dict(server(), **{"identifier": "newident1", "name": payload["name"]})

    def update_details(self, sid, payload):
        self._log("update_details", payload)

    def node_allocations(self, node_id):
        self.reads.append("node_allocations")
        return [dict(a) for a in self.node_allocs]

    def server_allocations(self, server_id):
        self.reads.append("server_allocations")
        return [dict(a) for a in self.node_allocs if a["id"] in self.own]

    def update_build(self, sid, payload):
        self._log("update_build", payload)
        if self.ignore_allocation_changes:
            return
        self.own |= set(payload.get("add_allocations", []))
        self.own -= set(payload.get("remove_allocations", []))
        self.primary = payload["allocation"]

    def update_startup(self, sid, payload):
        self._log("update_startup", payload)

    def reinstall(self, sid):
        self._log("reinstall")
        for name in self.rewrites:
            self._clock += 1
            entry = next((f for f in self.root if f["name"] == name), None)
            if entry is None:
                entry = {"name": name, "size": 1, "is_file": True}
                self.root.append(entry)
            entry["modified_at"] = "t%d" % self._clock

    def delete_server(self, sid):
        self._log("delete_server", sid)

    # client
    def power_state(self, identifier):
        return self.state

    def send_power(self, identifier, signal):
        self._log("power", signal)
        self.state = {"start": "running", "stop": "offline", "restart": "running", "kill": "offline"}[signal]

    def server_info(self, identifier):
        return {"uuid": "9e72677e-dba3-4ece-924c-32339960619b", "status": self.install_status}

    def is_installing(self, identifier):
        self.installing += 1
        return self.installing < 2

    def backups(self, identifier):
        return [dict(b) for b in self._backups]

    def create_backup(self, identifier):
        self._log("create_backup")
        new = {"uuid": "new", "created_at": "2099", "is_locked": False, "is_successful": True, "completed_at": "x"}
        self._backups.append(new)
        return new

    def delete_backup(self, identifier, uuid):
        self._log("delete_backup", uuid)
        self._backups = [b for b in self._backups if b["uuid"] != uuid]

    def list_files(self, identifier, directory):
        if directory == "/":
            return [dict(f) for f in self.root]
        return None if self.files is None else [dict(f) for f in self.files]

    def create_folder(self, identifier, root, name):
        self._log("create_folder", root, name)
        self.files = []

    def delete_files(self, identifier, root, files):
        self._log("delete_files", tuple(files))
        if root == "/":
            self.root = [f for f in self.root if f["name"] not in files]
        elif self.files is not None:
            self.files = [f for f in self.files if f["name"] not in files]

    def pull_file(self, identifier, url, directory, filename):
        self._log("pull_file", filename)
        if self.fail_pull:
            raise PterodactylError("pull failed")

    def read_file(self, identifier, path):
        return self.contents[path.rsplit("/", 1)[1]]


def no_sleep(_):
    pass
