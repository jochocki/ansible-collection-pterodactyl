# jochocki.pterodactyl

Manage Minecraft servers on a [Pterodactyl](https://pterodactyl.io) panel from
Ansible. The modules run on the controller and talk to the panel's HTTP API, so
they need no SSH access to the Wings node.

## Modules

The generic modules follow the tabs of the panel's server page, so they work for
any game on the panel. `minecraft_server` sits on top and adds what only
Minecraft needs.

| Module | Panel tab | What it does |
| --- | --- | --- |
| `pterodactyl_server` | Details | Creates, renames and deletes a server. Setting `external_id` makes a later rename safe. |
| `pterodactyl_build` | Build Configuration | CPU, memory, disk, IO, swap, and the backup, database and allocation limits. |
| `pterodactyl_startup` | Startup | Docker image, startup command and egg variables, with an optional reinstall. |
| `pterodactyl_power` | Console | Starts, stops, restarts or kills a server. |
| `minecraft_server` | all of them | Turns a Minecraft version and loader into the right egg, Java image and variables, then converges the server, its mods and its power state in the right order. |

Ansible modules can't call each other, so the layering is in the code: every
module is a thin wrapper over the same functions in `module_utils`, and
`minecraft_server` uses the same ones the generic modules do. A generic module
changes only what you set and nothing else. It does not stop, back up or restart
the server: ordering is `minecraft_server`'s job, or yours.

Supported loaders for `minecraft_server` in 0.1.0: `fabric`, `paper` and
`vanilla`. The panel needs eggs named `Fabric`, `Paper` and `Vanilla Minecraft`.

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
- **The egg owns its variables.** On an update only the Minecraft version is
  changed: every other egg variable keeps the server's value, so a server's
  `SERVER_JARFILE` is never overwritten. A new server gets the egg's own defaults
  and startup command. Names and defaults come from the panel, so a newer egg
  version needs no change here. To set a variable on purpose, use `environment`
  (for example `SERVER_JARFILE: server.jar` when moving a server to an egg that
  names its jar differently). That updates the startup settings only; add
  `reinstall: true` when the install script has to run again.
- **A reinstall is checked by its effect.** The panel can report success for an
  install that never ran, for example when Wings can't pull the egg's install
  image (a Fabric egg whose install container has been removed from Docker Hub
  does this). So after a reinstall the jar the server starts (`SERVER_JARFILE`)
  must have been rewritten, and if it wasn't, the run fails with the server left
  stopped and the place Wings keeps the install output, which is
  `/var/log/pterodactyl/install/<server uuid>.log` on the node by default. The
  panel has no log viewer for it. Nothing in the server's files is deleted.
- **`reinstall: true` runs the whole sequence again.** It reinstalls even when the
  version already matches, which is how to retry after fixing a failed install. It always
  reports `changed`, so use it for one run, not in a regular playbook.
- **Servers are keyed by `external_id`.** It defaults to the lower-cased,
  dash-separated name. A server found by exact name gets the key set on first
  run, so a later rename does not orphan it.

## Example

```yaml
- name: A modded Minecraft server
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

### A game that is not Minecraft

```yaml
- name: Create it
  jochocki.pterodactyl.pterodactyl_server:
    name: Factorio
    owner: 1
    node: wings01
    egg: Factorio
    docker_image: ghcr.io/ptero-eggs/yolks:debian
    startup: ./bin/x64/factorio --start-server
    memory: 2000

- name: Give it more memory later
  jochocki.pterodactyl.pterodactyl_build:
    server: Factorio
    memory: 4000
```

## Ports

A server's ports are allocations on its node, and they live on the Build
Configuration tab. `pterodactyl_build` (and `minecraft_server`) take them as:

- `port`: the primary, or game, port.
- `additional_ports`: the complete set of other ports.
- `ip`: only needed when a port exists on more than one IP of the node. It
  applies to every port given.

```yaml
- jochocki.pterodactyl.pterodactyl_build:
    server: Factorio
    port: 34197
    additional_ports: [27015]
```

- **The allocations must already exist.** The module assigns and releases them,
  but doesn't create them on the node. A port that doesn't exist, or belongs to
  another server, fails with a message that says so, before anything changes.
- **Leave an option out to leave that part alone.** Without `additional_ports`,
  the extra ports stay as they are, and a move to a new `port` keeps the old one
  assigned as an extra. Set `additional_ports` (even to `[]`) and anything not
  listed is released. The primary is never released without a replacement.
- **The panel skips changes it won't make without an error**, such as an
  allocation that is already taken. The module checks the node first and
  confirms the result afterwards, so a change that didn't happen is an error,
  not a silent `changed`.
- **`allocation_limit` is a different thing.** It is how many additional
  allocations the server is allowed to hold (an Application Feature Limit), not
  which ones it has.
- **When creating a server**, `port` and `additional_ports` choose its
  allocations. Without them it takes the first free one on the node.

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

## Check mode and `--diff`

Every module except `pterodactyl_power` supports `--check` and `--diff`. With
`--diff` a change is shown as a before and after of the panel's state: the
details, build limits, ports, startup (image and version variables) and, for
`minecraft_server`, the exact mod files that would be added and removed. Without
`--diff`, each task's result lists what it did in `actions` (visible with `-v`).

```bash
ansible-playbook site.yml --check --diff
```

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
