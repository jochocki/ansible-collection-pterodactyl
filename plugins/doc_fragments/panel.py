# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    DOCUMENTATION = r"""
options:
  panel_url:
    description:
      - Base URL of the Pterodactyl panel, for example V(https://panel.example.org).
      - Falls back to the E(PTERODACTYL_URL) environment variable.
    type: str
  api_key:
    description:
      - Panel API key. It must belong to a root administrator, or client calls
        on servers the key's user does not own are refused.
      - Falls back to the E(PTERODACTYL_API_KEY) environment variable.
    type: str
  validate_certs:
    description: Verify the panel's TLS certificate.
    type: bool
    default: true
"""
