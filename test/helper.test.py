#!/usr/bin/env python3
"""Tests for ingest/helper.py (the "Koble til REMA" helper). Stdlib only.

Runs the real helper on a random 127.0.0.1 port with HOME set to a temp folder, a FAKE `rema` binary and a FAKE
sync script. The real rema1000-cli is never run and ~/.rema1000 is never touched. All tokens are FAKE.

    python3 test/helper.test.py        (or: python3 -m unittest discover -s test -p 'helper.test.py')
"""
import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HELPER = os.path.join(ROOT, "ingest", "helper.py")
TEST_ORIGIN = "http://localhost:8766"
APP_ORIGIN = "https://fake-user-FAKE.github.io"
FAKE_REFRESH = "FAKE-REMA-REFRESH-TOKEN-DO-NOT-USE"

FAKE_REMA = r"""#!/bin/bash
# FAKE rema1000-cli for tests. Never contacts REMA.
echo "$HOME" >> "$HOME/fake-rema-calls.txt"
echo "$*" >> "$HOME/fake-rema-calls.txt"
case "$1 $2" in
  "auth login")
    sleep "${FAKE_REMA_DELAY:-0.3}"
    [ "${FAKE_REMA_MODE:-ok}" = fail ] && { echo "FAKE login cancelled"; exit 1; }
    mkdir -p "$HOME/.rema1000"
    printf '{"firebase":{"refresh_token":"%s"},"device_id":"FAKE-DEVICE"}' "__REFRESH__" > "$HOME/.rema1000/tokens.json"
    echo "Logged in as +47 FAKE (token __REFRESH__)"; exit 0 ;;
  "auth logout") rm -f "$HOME/.rema1000/tokens.json"; exit 0 ;;
esac
exit 2
""".replace("__REFRESH__", FAKE_REFRESH)

FAKE_SYNC = r"""#!/bin/bash
# FAKE ingest/sync.sh for tests.
sleep "${FAKE_SYNC_DELAY:-0.2}"
case "$(cat "$HOME/fake-sync-mode" 2>/dev/null || echo ok)" in
  ok) echo "2 kvitteringer (FAKE)"; echo "Ferdig."; exit 0 ;;
  expired) echo "HTTP 400 for https://securetoken.googleapis.com/v1/token: INVALID_REFRESH_TOKEN (FAKE) eyJabcdefghijklmnop.FAKEFAKE" >&2
           echo "Ferdig, men feilet: REMA" >&2; exit 3 ;;
  *) echo "Ingen mottaker (FAKE) token=__REFRESH__" >&2; exit 1 ;;
esac
""".replace("__REFRESH__", FAKE_REFRESH)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def write_exec(path, body):
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, 0o755)


class HelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mk-helper-")
        cls.home = os.path.join(cls.tmp, "home")
        os.makedirs(cls.home)
        cls.rema = os.path.join(cls.tmp, "rema")
        cls.sync = os.path.join(cls.tmp, "sync.sh")
        write_exec(cls.rema, FAKE_REMA)
        write_exec(cls.sync, FAKE_SYNC)
        cls.cloud = os.path.join(cls.tmp, "cloud.sh")
        write_exec(cls.cloud, '#!/bin/bash\necho "$*" >> "$HOME/fake-cloud-calls.txt"\n')
        os.makedirs(os.path.join(cls.home, ".matkassa"), mode=0o700)
        with open(os.path.join(cls.home, ".matkassa", "supabase_session.json"), "w") as f:
            f.write('{"refresh_token": "FAKE-SUPABASE-RT", "user_id": "FAKE"}')
        cls.port = free_port()
        cls.env = {
            "HOME": cls.home, "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8",
            "MATKASSA_HELPER_PORT": str(cls.port), "MATKASSA_REMA_BIN": cls.rema, "MATKASSA_HELPER_SYNC": cls.sync,
            "MATKASSA_HELPER_ORIGINS": TEST_ORIGIN, "MATKASSA_APP_ORIGIN": APP_ORIGIN, "MATKASSA_HELPER_CLOUD": cls.cloud, "MATKASSA_HELPER_LOGIN_TIMEOUT": "20",
        }
        out = subprocess.run([sys.executable, "-I", HELPER, "pair"], env=cls.env, capture_output=True, text=True)
        cls.pair_out = out.stdout
        cls.code = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", out.stdout).group(0)
        cls.log = open(os.path.join(cls.tmp, "helper.log"), "w+")
        cls.proc = subprocess.Popen([sys.executable, "-I", HELPER, "serve"], env=cls.env, stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.log.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- helpers ----
    def req(self, method, path, token=True, origin=None, host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        if token is True:
            h["Authorization"] = f"Bearer {self.code}"
        elif token:
            h["Authorization"] = f"Bearer {token}"
        if origin:
            h["Origin"] = origin
        if host:
            h["Host"] = host
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read().decode()
        c.close()
        return r.status, (json.loads(body) if body else {}), dict(r.getheaders()), body

    def wait_state(self, want, ms=8000):
        end = time.time() + ms / 1000
        while time.time() < end:
            _, j, _, _ = self.req("GET", "/status")
            if j["rema"]["state"] == want and not j["syncing"]:
                return j
            time.sleep(0.1)
        self.fail(f"state never became {want}: {j}")

    def cloud_calls(self):
        time.sleep(0.3)
        try:
            with open(os.path.join(self.home, "fake-cloud-calls.txt")) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def set_sync_mode(self, mode):
        with open(os.path.join(self.home, "fake-sync-mode"), "w") as f:
            f.write(mode)

    # ---- tests (run in name order) ----
    def test_01_pairing_code_file(self):
        p = os.path.join(self.home, ".matkassa", "helper-pair.json")
        self.assertTrue(os.path.isfile(p))
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertIn("Mer → Kjeder", self.pair_out)
        again = subprocess.run([sys.executable, "-I", HELPER, "pair"], env=self.env, capture_output=True, text=True).stdout
        self.assertIn(self.code, again, "pair shows the same code again (one-time pairing)")

    def test_02_requires_token(self):
        s, j, _, _ = self.req("GET", "/status", token=None)
        self.assertEqual((s, j.get("error")), (401, "unpaired"))
        s, _, _, _ = self.req("GET", "/status", token="AAAA-BBBB-CCCC-DDDD")
        self.assertEqual(s, 401)
        s, _, _, _ = self.req("POST", "/rema/login", token=None)
        self.assertEqual(s, 401)
        s, _, _, _ = self.req("POST", "/sync", token=None)
        self.assertEqual(s, 401)
        self.assertFalse(os.path.exists(os.path.join(self.home, "fake-rema-calls.txt")), "nothing ran without the code")

    def test_03_status_ok_and_code_forgiving(self):
        s, j, h, _ = self.req("GET", "/status")
        self.assertEqual(s, 200)
        self.assertEqual(j["helper"], "matkassa")
        self.assertEqual(j["rema"]["state"], "disconnected")
        self.assertEqual(h.get("Cache-Control"), "no-store")
        s, _, _, _ = self.req("GET", "/status", token=self.code.lower().replace("-", " "))
        self.assertEqual(s, 200, "lower case and spaces are fine when pasting")

    def test_04_foreign_origin_rejected(self):
        for o in ("https://evil.example", APP_ORIGIN + ".evil.example", "null", "http://localhost:9999"):
            s, j, h, _ = self.req("GET", "/status", origin=o)
            self.assertEqual(s, 403, o)
            self.assertNotIn("Access-Control-Allow-Origin", h, o)
            self.assertNotIn("rema", j)
        s, _, _, _ = self.req("POST", "/rema/login", origin="https://evil.example")
        self.assertEqual(s, 403)

    def test_05_allowed_origins_get_cors(self):
        for o in (APP_ORIGIN, TEST_ORIGIN):
            s, _, h, _ = self.req("GET", "/status", origin=o)
            self.assertEqual(s, 200)
            self.assertEqual(h.get("Access-Control-Allow-Origin"), o)
            self.assertEqual(h.get("Vary"), "Origin")

    def test_06_preflight(self):
        s, _, h, _ = self.req("OPTIONS", "/rema/login", token=None, origin=APP_ORIGIN,
                              headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization",
                                       "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(s, 204)
        self.assertIn("Authorization", h.get("Access-Control-Allow-Headers", ""))
        self.assertEqual(h.get("Access-Control-Allow-Private-Network"), "true")
        s, _, h, _ = self.req("OPTIONS", "/rema/login", token=None, origin="https://evil.example")
        self.assertEqual(s, 403)
        self.assertNotIn("Access-Control-Allow-Origin", h)

    def test_07_dns_rebinding_host_rejected(self):
        s, _, _, _ = self.req("GET", "/status", host=f"evil.example:{self.port}")
        self.assertEqual(s, 421)
        s, _, _, _ = self.req("GET", "/status", host=f"localhost:{self.port}")
        self.assertEqual(s, 200)

    def test_08_loopback_only(self):
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{self.port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        self.assertIn(f"127.0.0.1:{self.port}", out)
        self.assertNotIn(f"*:{self.port}", out)
        lan = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
        if lan:
            with self.assertRaises(OSError):
                socket.create_connection((lan, self.port), timeout=1).close()

    def test_09_pages_origin_from_git_remote(self):
        sys.path.insert(0, os.path.join(ROOT, "ingest"))
        import helper
        o = helper.pages_origin()
        self.assertRegex(o, r"^(https://[a-z0-9-]+\.github\.io)?$")
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d])
            self.assertEqual(helper.pages_origin(d), "", "no remote → no web page allowed")
            subprocess.run(["git", "-C", d, "remote", "add", "origin", "https://github.com/Some-User/matkassa.git"])
            self.assertEqual(helper.pages_origin(d), "https://some-user.github.io")

    def test_10_login_connects(self):
        s, j, _, body = self.req("POST", "/rema/login", origin=APP_ORIGIN)
        self.assertEqual(s, 202)
        self.assertEqual(j["rema"]["state"], "connecting")
        j = self.wait_state("connected")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".rema1000", "tokens.json")))
        with open(os.path.join(self.home, "fake-rema-calls.txt")) as f:
            calls = f.read()
        self.assertIn(self.home, calls, "the fake rema ran with the temp HOME, never the real ~/.rema1000")
        self.assertIn("auth login", calls)
        self.assertNotIn(FAKE_REFRESH, json.dumps(j))

    def test_11_sync_ok(self):
        self.set_sync_mode("ok")
        s, j, _, _ = self.req("POST", "/sync")
        self.assertEqual(s, 202)
        self.assertTrue(j["syncing"])
        s2, _, _, _ = self.req("POST", "/sync")
        self.assertEqual(s2, 409, "only one sync at a time")
        j = self.wait_state("connected")
        self.assertTrue(j["rema"]["lastSyncOk"])
        self.assertTrue(j["rema"]["lastSync"])
        self.assertIsNone(j["rema"]["message"])
        self.assertIn("report rema connected --synced", self.cloud_calls(), "the account hears about the sync (status only)")

    def test_12_sync_failure_is_masked(self):
        self.set_sync_mode("broken")
        self.req("POST", "/sync")
        j = self.wait_state("connected")
        self.assertFalse(j["rema"]["lastSyncOk"])
        self.assertIn("Ingen mottaker", j["rema"]["message"])
        self.assertNotIn(FAKE_REFRESH, json.dumps(j), "a token-shaped value in the sync output never reaches the reply")

    def test_13_sync_expired(self):
        self.set_sync_mode("expired")
        self.req("POST", "/sync")
        j = self.wait_state("expired")
        self.assertIn("utløpt", j["rema"]["message"])
        self.assertNotIn("eyJ", json.dumps(j))
        self.assertTrue(any(c.startswith("report rema expired") for c in self.cloud_calls()))

    def test_14_login_again_clears_expired(self):
        self.req("POST", "/rema/login")
        self.wait_state("connected")

    def test_15_logout(self):
        s, j, _, _ = self.req("POST", "/rema/logout")
        self.assertEqual(s, 200)
        self.assertEqual(j["rema"]["state"], "disconnected")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".rema1000", "tokens.json")))
        calls = self.cloud_calls()
        self.assertEqual(calls[-1], "report rema disconnected")
        self.assertFalse(any(FAKE_REFRESH in c or "FAKE-SUPABASE" in c for c in calls), "no token is passed on")

    def test_16_login_cancelled(self):
        # Swap in a fake that fails, as when the user closes the browser window without logging in.
        write_exec(self.rema, FAKE_REMA.replace('"${FAKE_REMA_MODE:-ok}" = fail', "true"))
        try:
            self.req("POST", "/rema/login")
            j = self.wait_state("disconnected")
            self.assertIn("ikke fullført", j["rema"]["message"])
        finally:
            write_exec(self.rema, FAKE_REMA)

    def test_17_unknown_and_methods(self):
        self.assertEqual(self.req("GET", "/rema/login")[0], 404)
        self.assertEqual(self.req("POST", "/shell")[0], 404)
        self.assertEqual(self.req("DELETE", "/status")[0], 405)

    def test_18_state_file_has_no_secrets(self):
        p = os.path.join(self.home, ".matkassa", "helper-state.json")
        with open(p) as f:
            raw = f.read()
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertNotIn(FAKE_REFRESH, raw)
        self.assertNotIn(self.code, raw)

    def test_19_log_has_no_tokens(self):
        self.log.flush()
        with open(self.log.name) as f:
            raw = f.read()
        self.assertIn("GET /status 200", raw)
        self.assertNotIn(self.code, raw)
        self.assertNotIn(FAKE_REFRESH, raw)
        self.assertNotIn("Authorization", raw)

    def test_20_rate_limit(self):
        codes = [self.req("GET", "/status", token="WRONG-WRONG")[0] for _ in range(12)]
        self.assertIn(429, codes)
        self.assertEqual(self.req("GET", "/status")[0], 429, "even the right code waits a minute after a burst")

    def test_30_launchd_plist_dry_run(self):
        dest = os.path.join(self.tmp, "no.matkassa.helper.plist")
        env = dict(os.environ, MATKASSA_HELPER_PLIST=dest)
        r = subprocess.run([os.path.join(ROOT, "ingest", "launchd", "install-helper.sh"), "--dry-run"], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(dest) as f:
            x = f.read()
        self.assertIn("<string>no.matkassa.helper</string>", x)
        self.assertIn("ingest/helper.py</string>", x)
        self.assertIn("<key>KeepAlive</key>", x)
        self.assertIsNone(re.search(r"__[A-Z_]+__", x))
        self.assertEqual(subprocess.run(["plutil", "-lint", "-s", dest]).returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
