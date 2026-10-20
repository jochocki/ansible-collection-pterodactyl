# jochocki.pterodactyl

Manage Minecraft servers on a [Pterodactyl](https://pterodactyl.io) panel from
Ansible. The modules run on the controller and talk to the panel's HTTP API, so
they need no SSH access to the Wings node.

## Modules

| Module | What it does |
| --- | --- |
| `minecraft_server` | Creates a server, converges its limits, and moves it to a new Minecraft version. |
| `minecraft_mods` | Syncs `/mods` with a list of Modrinth projects and verifies every new file. |
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
  unlocked backup makes room), is reinstalled, and then returns to its previous
  power state. With `restore_power: false` it stays stopped, so mods can be
  swapped first. The module returns `previous_power` for `pterodactyl_power`.
- **Servers are keyed by `external_id`.** It defaults to the lower-cased,
  dash-separated name. A server found by exact name gets the key set on first
  run, so a later rename does not orphan it.
- **Mods resolve before anything changes.** One unknown project leaves the
  directory untouched. New files are checked against Modrinth's sha512, and old
  jars are removed only after the new ones verify.
- **`purge` defaults to true.** A mod upgrade has a new filename. Left behind,
  the old jar makes Fabric refuse to start on the duplicate mod ID.

## Example

```yaml
- name: Move Tiny Animals to a new release
  jochocki.pterodactyl.minecraft_server:
    name: Tiny Animals
    loader: fabric
    version: "26.3"
    node: wings01
    memory: 3000
    cpu: 300
    restore_power: false
  register: tiny

- name: Update its mods
  jochocki.pterodactyl.minecraft_mods:
    server: Tiny Animals
    version: "26.3"
    loader: fabric
    mods: [fabric-api, xaeros-minimap, xaeros-world-map]

- name: Put the power back the way it was
  jochocki.pterodactyl.pterodactyl_power:
    server: Tiny Animals
    state: "{{ tiny.previous_power }}"
```

## Mods

`minecraft_mods` takes Modrinth project **slugs**, the last part of a project's
URL (`modrinth.com/mod/fabric-api` is `fabric-api`). A project ID works too, and
is the safer pin, because an author can rename a slug. A slug is not always the
project's name: FabricExporter is `fabricexporter`, and the module fails on an
unknown one before it changes anything.

```yaml
- jochocki.pterodactyl.minecraft_mods:
    server: Tiny Animals
    version: "26.3"
    loader: fabric
    mods:
      - fabric-api
      - xaeros-minimap
```

- **List dependencies yourself.** The module doesn't read a mod's required
  dependencies, so a mod that needs Fabric API only works if `fabric-api` is in
  the list too.
- **Each mod gets the newest release for the server's version and loader.** A
  project with no release for that Minecraft version fails the whole run, so a
  version bump can't leave `/mods` half updated. The `paper` loader accepts
  `paper`, `spigot` and `bukkit` plugins. `vanilla` has no mod support.
- **`purge` is on by default.** Any `.jar` in `/mods` that isn't in `mods` is
  deleted, hand-installed ones included, but only after the listed files are
  downloaded and their sha512 checked. Set `purge: false` to keep them. Then an
  upgraded mod leaves its old jar behind, and Fabric refuses to start with two
  jars of the same mod. Files that aren't `.jar` are never touched.
- **The module doesn't restart the server.** Follow it with
  `pterodactyl_power` (`state: restarted`) to load the new mods.

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
