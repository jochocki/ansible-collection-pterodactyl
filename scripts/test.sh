#!/usr/bin/env bash
# Run the collection's checks from a checkout, whatever directory it lives in.
#
#   scripts/test.sh unit      unit tests (pytest)
#   scripts/test.sh sanity    ansible-test sanity in its default Docker image,
#                             so every Python version it supports is covered
#   scripts/test.sh           both
#
# The code imports itself as ansible_collections.jochocki.pterodactyl, and
# ansible-test insists on running from a directory with that path, so both
# checks run on a copy laid out that way in a temp directory. It has to live
# outside this checkout: inside, ansible-test finds this repo's .git and lists
# files with `git ls-files`, which would skip the copy as untracked.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

ns=$(uv run python -c "import yaml; g = yaml.safe_load(open('galaxy.yml')); print(g['namespace'] + '/' + g['name'])")
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT
dest="$build/ansible_collections/$ns"

mkdir -p "$dest"
rsync -a --exclude .git --exclude .venv --exclude __pycache__ ./ "$dest/"

unit() {
  (cd "$dest" && PYTHONPATH="$build" uv run --project "$root" pytest tests/unit -q)
}

sanity() {
  # `uv run` puts the project venv's ansible-test on PATH.
  (cd "$dest" && uv run --project "$root" ansible-test sanity --docker default --color no)
}

case "${1:-all}" in
  unit) unit ;;
  sanity) sanity ;;
  all) unit && sanity ;;
  *) echo "usage: $0 [unit|sanity]" >&2; exit 2 ;;
esac
