# -*- coding: utf-8 -*-
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""One HTTP entry point, so tests swap a single function."""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.urls import open_url


class HttpError(Exception):
    def __init__(self, status, body, url=""):
        super(HttpError, self).__init__("HTTP %s from %s: %s" % (status, url, body[:300]))
        self.status = status
        self.body = body
        self.url = url


def request(method, url, headers=None, data=None, timeout=60, validate_certs=True):
    """Return (status, body bytes). HTTP errors come back as a status, not an exception."""
    try:
        resp = open_url(
            url,
            method=method,
            headers=headers or {},
            data=data,
            timeout=timeout,
            validate_certs=validate_certs,
            follow_redirects="all",
        )
        return resp.getcode(), resp.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except URLError as exc:
        raise HttpError(0, str(exc.reason), url)


def get_json(url, headers=None, timeout=60, validate_certs=True, http=request):
    status, body = http("GET", url, headers, None, timeout, validate_certs)
    if status != 200:
        raise HttpError(status, body.decode("utf-8", "replace"), url)
    return json.loads(body.decode("utf-8"))
