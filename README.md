# jochocki.pterodactyl

Manage Minecraft servers on a [Pterodactyl](https://pterodactyl.io) panel from
Ansible. The modules run on the controller and talk to the panel's HTTP API, so
they need no SSH access to the Wings node.

## Modules

| Module | What it does |
| --- | --- |
| `minecraft_server` | Creates a server, converges its limits and version, and optionally keeps its mods in step with Modrinth. |
| `pterodactyl_power` | Starts, stops, restarts or kills a server. |

Supported loaders in 0.1.0: `fabric`, `paper` and `vanilla`. The panel needs
eggs named `Fabric`, `Paper` and `Vanilla Minecraft`.

## Behavior worth knowing

- **Quote versions.** YAML reads an unquoted `1.20` as the float `1.2`.
  `minecraft_server` checks the version against Mojang's release manifest and
  fails on one that was never released.
- **Java follows the version.** Releases below 1.17 get Java 8, 1.17 to 1.20.4
  get 17, 1.20.5 to 1.21.x get 21, and year-numbered releases (26.x) get 25. The
  module sets the image on the server, so the egg does not need to list it.
- **A version change is a sequence.** The server stops, is backed up (the oldest
  unlocked backup makes room), is reinstalled, gets its mods, and then returns
  to its previous power state.
- **Servers are keyed by `external_id`.** It defaults to the lower-cased,
  dash-separated name. A server found by exact name gets the key set on first
  run, so a later rename does not orphan it.

## Example

```yaml
- name: A modded server
  jochocki.pterodactyl.minecraft_server:
    name: Tiny Animals
    loader: fabric
    version: "26.3"
    node: wings01
    memory: 3000
    cpu: 300
    mods:
      - fabric-api
      - xaeros-minimap
      - xaeros-world-map

- name: A vanilla server, which has no mods
  jochocki.pterodactyl.minecraft_server:
    name: The Warden
    loader: vanilla
    version: "1.21"
    node: wings01
```

## Mods

`mods` is optional. Leave it out and the server's `/mods` directory is not
touched. Give it a list and that list is the complete set of mods. `vanilla`
servers can't have mods, so the module refuses the option for them.

Entries are Modrinth project **slugs**, the last part of a project's URL
(`modrinth.com/mod/fabric-api` is `fabric-api`). A project ID works too, and is
the safer pin, because an author can rename a slug. A slug is not always the
project's name: FabricExporter is `fabricexporter`. The module fails on an
unknown one, naming it, before it changes anything.

- **List dependencies yourself.** The module doesn't read a mod's required
  dependencies, so a mod that needs Fabric API only works if `fabric-api` is in
  the list too.
- **Each mod gets the newest release for the server's version and loader.** A
  project with no release for that Minecraft version fails the run before the
  server is touched, so a version bump can't end up half done. The `paper`
  loader accepts `paper`, `spigot` and `bukkit` plugins.
- **`purge` is on by default.** Any `.jar` in `/mods` that isn't in `mods` is
  deleted, hand-installed ones included, but only after the listed files are
  downloaded and their sha512 checked. Set `purge: false` to keep them. Then an
  upgraded mod leaves its old jar behind, and Fabric refuses to start with two
  jars of the same mod. Files that aren't `.jar` are never touched. `mods: []`
  removes every jar.
- **Mods go in before the server boots.** After a version change the mods for
  the new version are installed first, and then the server starts. A running
  server is restarted when its mods changed. If the mods fail to install, the
  server is left stopped, not booted without them.

## Connection

Every module takes `panel_url`, `api_key` and `validate_certs`. `panel_url` and
`api_key` fall back to the `PTERODACTYL_URL` and `PTERODACTYL_API_KEY`
environment variables. The key must belong to a root administrator.

## Development

The unit tests use only the standard library and a recording fake of the panel
client:

```bash
# from the directory that contains ansible_collections/
PYTHONPATH=$PWD python -m unittest discover \
  -s ansible_collections/jochocki/pterodactyl/tests/unit \
  -t . -p 'test_*.py'
```
