"""A recording stand-in for PterodactylClient."""
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError


def server(**over):
    base = {
        "id": 27, "identifier": "650fdf18", "name": "Tiny Animals", "external_id": "tiny-animals",
        "user": 1, "node": 1, "egg": 15, "allocation": 9, "description": "",
        "limits": {"memory": 3000, "swap": 0, "disk": 500, "io": 500, "cpu": 300, "threads": None, "oom_disabled": True},
        "feature_limits": {"databases": 0, "allocations": 0, "backups": 2},
        "container": {
            "image": "ghcr.io/pterodactyl/yolks:java_21",
            "startup_command": "java -jar {{SERVER_JARFILE}}",
            "environment": {"MC_VERSION": "1.21.11"},
        },
    }
    base.update(over)
    return base


class FakeClient(object):
    def __init__(self, servers=None, state="running", backups=None, files=None, contents=None):
        self._servers = servers if servers is not None else []
        self.state = state
        self._backups = backups if backups is not None else []
        self.files = files
        self.contents = contents or {}
        self.calls = []
        self.installing = 0
        self.fail_pull = False

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

    def update_build(self, sid, payload):
        self._log("update_build", payload)

    def update_startup(self, sid, payload):
        self._log("update_startup", payload)

    def reinstall(self, sid):
        self._log("reinstall")

    def delete_server(self, sid):
        self._log("delete_server", sid)

    # client
    def power_state(self, identifier):
        return self.state

    def send_power(self, identifier, signal):
        self._log("power", signal)
        self.state = {"start": "running", "stop": "offline", "restart": "running", "kill": "offline"}[signal]

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
        return None if self.files is None else [dict(f) for f in self.files]

    def create_folder(self, identifier, root, name):
        self._log("create_folder", root, name)
        self.files = []

    def delete_files(self, identifier, root, files):
        self._log("delete_files", tuple(files))

    def pull_file(self, identifier, url, directory, filename):
        self._log("pull_file", filename)
        if self.fail_pull:
            raise PterodactylError("pull failed")

    def read_file(self, identifier, path):
        return self.contents[path.rsplit("/", 1)[1]]


def no_sleep(_):
    pass
