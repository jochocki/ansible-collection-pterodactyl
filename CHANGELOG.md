# Changelog

All notable changes to this collection are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

## 1.0.0 - 2026-10-20

First release on Galaxy.

### Added

- `pterodactyl_server`, `pterodactyl_build`, `pterodactyl_startup` and
  `pterodactyl_power`: generic modules named after the tabs of the panel's
  server page. Each changes only what you set.
- `pterodactyl_build` manages a server's allocations and ports as well as its
  resource limits.
- `minecraft_server`: turns a Minecraft version and loader (`fabric`, `paper`,
  `vanilla`) into the right egg, Java image and variables, then converges the
  server, its optional mod list and its power state in the right order.
- `pterodactyl_egg_info`: checks the panel's eggs against the registries and
  the egg source, including the config Wings reads live.
- Support for `--diff` and check mode.
- The `jochocki.pterodactyl.pterodactyl` action group, so
  `module_defaults` can set the panel connection once for a play.

### Changed

- Egg variables come from the egg instead of being hardcoded.
- A version change stops the server, backs it up, reinstalls it, gets its mods
  and restores its previous power state. `minecraft_server` chooses what
  happens when the backup limit is reached: rotate, fail or skip.
- A reinstall is judged by whether it ran, a failed install reports the log
  location, and a Fabric server's vanilla jar is replaced on a version change.
- A server with mods but no mod list fails instead of guessing, and unmanaged
  mods are checked on a version change.
