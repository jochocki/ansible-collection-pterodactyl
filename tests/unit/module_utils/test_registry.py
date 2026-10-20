import json
import unittest

from ansible_collections.jochocki.pterodactyl.plugins.module_utils import registry as reg
from ansible_collections.jochocki.pterodactyl.plugins.module_utils.http import HttpError


class Parse(unittest.TestCase):
    def test_references(self):
        cases = {
            "openjdk:11-jdk-slim": ("docker.io", "library/openjdk", "11-jdk-slim"),
            "eclipse-temurin:21-jdk-jammy": ("docker.io", "library/eclipse-temurin", "21-jdk-jammy"),
            "ghcr.io/pterodactyl/yolks:java_21": ("ghcr.io", "pterodactyl/yolks", "java_21"),
            "quay.io/parkervcp/pterodactyl-images:debian_source": ("quay.io", "parkervcp/pterodactyl-images", "debian_source"),
            "someone/image": ("docker.io", "someone/image", "latest"),
            "localhost:5000/team/app:1.0": ("localhost:5000", "team/app", "1.0"),
            "ghcr.io/org/app@sha256:abc": ("ghcr.io", "org/app", "sha256:abc"),
        }
        for ref, want in cases.items():
            self.assertEqual(reg.parse_image(ref), want, ref)


class Fake(object):
    """A registry that wants a bearer token for anything."""

    def __init__(self, manifests, token_status=200, challenge=True):
        self.manifests, self.token_status, self.challenge, self.calls = manifests, token_status, challenge, []

    def __call__(self, method, url, headers=None, data=None, timeout=60, validate_certs=True):
        self.calls.append((method, url, (headers or {}).get("Authorization")))
        if "/token" in url:
            return self.token_status, json.dumps({"token": "t0k"}).encode(), {}
        if self.challenge and not (headers or {}).get("Authorization"):
            return 401, b"", {"www-authenticate": 'Bearer realm="https://auth.example/token",service="reg",scope="repository:x:pull"'}
        return (200 if url in self.manifests else 404), b"", {}


class Check(unittest.TestCase):
    def test_exists_after_a_token_round_trip(self):
        http = Fake({"https://registry-1.docker.io/v2/library/eclipse-temurin/manifests/21-jdk-jammy"})
        self.assertEqual(reg.check_image("eclipse-temurin:21-jdk-jammy", http), "exists")
        self.assertEqual([c[0] for c in http.calls], ["HEAD", "GET", "HEAD"])
        self.assertEqual(http.calls[-1][2], "Bearer t0k")

    def test_missing(self):
        self.assertEqual(reg.check_image("openjdk:11-jdk-slim", Fake(set())), "missing")

    def test_docker_hub_uses_the_registry_host_not_the_reference_host(self):
        http = Fake(set())
        reg.check_image("openjdk:11-jdk-slim", http)
        self.assertTrue(http.calls[0][1].startswith("https://registry-1.docker.io/v2/library/openjdk/manifests/"))

    def test_a_registry_that_wants_credentials_is_unknown_not_missing(self):
        out = reg.check_image("ghcr.io/org/private:1", Fake(set(), token_status=403))
        self.assertTrue(out.startswith("unknown"), out)

    def test_no_challenge_needed(self):
        self.assertEqual(reg.check_image("ghcr.io/o/r:1", Fake({"https://ghcr.io/v2/o/r/manifests/1"}, challenge=False)), "exists")

    def test_a_network_error_is_unknown(self):
        def boom(*a, **k):
            raise HttpError(0, "timed out", "u")
        self.assertTrue(reg.check_image("a:1", boom).startswith("unknown"))

    def test_an_unexpected_status_is_unknown(self):
        self.assertTrue(reg.check_image("a:1", lambda *a, **k: (500, b"", {})).startswith("unknown: HTTP 500"))
