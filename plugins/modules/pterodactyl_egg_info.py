#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: pterodactyl_egg_info
short_description: Check that a Pterodactyl egg still works and matches its source
description:
  - Lists eggs with their author, last update, install container and runtime images.
  - With O(check_images), asks each image's registry whether it still exists. A reinstall pulls
    the egg's install container, and a tag that has been removed fails it without any warning
    until then.
  - With O(name) and O(source), fetches the egg's exported JSON from a GitHub repository, such as
    C(minecraft/java/fabric/egg-fabric.json) in C(pterodactyl/game-eggs), and reports every
    difference from the egg on the panel.
  - It only reads. The Application API cannot create or update an egg, so applying an update is
    done in the panel's admin UI. Eggs the panel ships are refreshed on every start; eggs
    imported by hand never are, which is what this module is for.
  - An egg's config files and its console log patterns are not compared.
options:
  name:
    description: Only this egg. Needed with O(source). Without it every egg is listed.
    type: str
  nest:
    description: The nest's name, when egg names repeat across nests.
    type: str
  source:
    description: Path of the egg's exported JSON in O(repository), to compare the panel's egg with.
    type: str
  repository:
    description: GitHub repository that holds O(source), as owner/name.
    type: str
    default: pterodactyl/game-eggs
  ref:
    description: Branch, tag or commit of O(repository). Use a commit to keep the comparison stable.
    type: str
    default: main
  check_images:
    description: Ask each registry whether the install and runtime images still exist.
    type: bool
    default: true
  fail_on_drift:
    description: Fail when an image is missing or the egg differs from O(source).
    type: bool
    default: false
extends_documentation_fragment:
  - jochocki.pterodactyl.panel
  - ansible.builtin.action_common_attributes
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
author:
  - Jordan Ochocki (@jochocki)
"""

EXAMPLES = r"""
- name: Is every egg's install container still there?
  jochocki.pterodactyl.pterodactyl_egg_info:
    fail_on_drift: true

- name: Has the Fabric egg fallen behind the maintained one?
  jochocki.pterodactyl.pterodactyl_egg_info:
    name: Fabric
    source: minecraft/java/fabric/egg-fabric.json
    fail_on_drift: true
"""

RETURN = r"""
eggs:
  description: Each egg's id, nest, name, author, updated_at, install_image and runtime_images.
  returned: always
  type: list
  elements: dict
images:
  description: Each image's state, V(exists), V(missing) or V(unknown) with the reason. Only with O(check_images).
  returned: when check_images is true
  type: dict
missing_images:
  description: The images the registries say are gone.
  returned: when check_images is true
  type: list
  elements: str
drift:
  description: Differences from O(source) as field, panel and source. Install script differences are in C(--diff).
  returned: when source is set
  type: list
  elements: dict
"""

import json

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import http as phttp
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.common import (
    build_client,
    connection_spec,
)
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.eggs import drift, egg_info, source_url
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.pterodactyl import PterodactylError
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.registry import check_image


def main():
    spec = connection_spec()
    spec.update(
        name=dict(type="str"),
        nest=dict(type="str"),
        source=dict(type="str"),
        repository=dict(type="str", default="pterodactyl/game-eggs"),
        ref=dict(type="str", default="main"),
        check_images=dict(type="bool", default=True),
        fail_on_drift=dict(type="bool", default=False),
    )
    module = AnsibleModule(argument_spec=spec, supports_check_mode=True,
                           required_by={"source": "name"})
    p = module.params
    try:
        client = build_client(module)
        eggs = client.eggs()
        if p["nest"]:
            ids = {n["id"] for n in client.nests() if n["name"] == p["nest"]}
            eggs = [e for e in eggs if e["nest"] in ids]
        if p["name"]:
            eggs = [e for e in eggs if e["name"] == p["name"]]
            if len(eggs) != 1:
                module.fail_json(msg="expected one egg named %r, found %d%s" % (
                    p["name"], len(eggs), "; set nest" if eggs else ""))
        infos = [egg_info(e) for e in eggs]

        result = {"changed": False, "eggs": infos}
        problems = []
        if p["check_images"]:
            wanted = sorted({i for e in infos for i in e["runtime_images"] + ([e["install_image"]] if e["install_image"] else [])})
            states = {image: check_image(image) for image in wanted}
            result["images"] = states
            result["missing_images"] = sorted(i for i, s in states.items() if s == "missing")
            problems += ["image %s no longer exists" % i for i in result["missing_images"]]

        if p["source"]:
            try:
                source = phttp.get_json(source_url(p["repository"], p["ref"], p["source"]))
            except (phttp.HttpError, ValueError) as exc:
                module.fail_json(msg="cannot read %s from %s@%s: %s" % (p["source"], p["repository"], p["ref"], exc))
            panel_egg = client.egg(eggs[0]["nest"], eggs[0]["id"])
            found = drift(panel_egg, source)
            result["drift"] = [{k: v for k, v in d.items() if not k.endswith("_text")} for d in found]
            problems += ["differs from %s: %s" % (p["source"], d["field"]) for d in found]
            if module._diff:
                scripts = next((d for d in found if d["field"] == "install_script"), None)
                if scripts:
                    result["diff"] = {"before": scripts["panel_text"] + "\n", "after": scripts["source_text"] + "\n",
                                      "before_header": "%s install script (panel)" % p["name"],
                                      "after_header": "%s install script (%s@%s)" % (p["name"], p["repository"], p["ref"])}
        if problems and p["fail_on_drift"]:
            module.fail_json(msg="; ".join(problems), **result)
        module.exit_json(**result)
    except PterodactylError as exc:
        module.fail_json(msg=str(exc))


if __name__ == "__main__":
    main()
