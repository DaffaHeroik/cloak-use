#!/usr/bin/env python3
"""Smoke tests — tanpa browser. Jalanin: python3 tests/test_smoke.py"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as e:
        FAIL += 1
        print(f"  FAIL  {name}: {e}")


# --- vault roundtrip di home temp ---
def test_vault_roundtrip():
    import vault
    with tempfile.TemporaryDirectory() as tmp:
        old_path, old_home = vault.VAULT_PATH, os.environ.get("CLOAK_USE_HOME")
        vault.VAULT_PATH = tmp and __import__("pathlib").Path(tmp) / "vault.json"
        try:
            vault.save_credential("test.local", "a@b.com", "sekrit")
            u, p = vault.get_credential("test.local")
            assert u == "a@b.com" and p == "sekrit", (u, p)
            assert "test.local" in vault.list_domains()
            sess = vault.get_session("test.local")
            assert sess is None
        finally:
            vault.VAULT_PATH = old_path


# --- auto_auth: spec builder + pluggable provider ---
def test_field_spec():
    import auto_auth
    f = {"type": "password", "name": "pass", "label": "Password", "selector": "[name='pass']"}
    spec = auto_auth._vault_field_spec(f)
    assert spec.split("|") == ["pass", "password", "Password", "••••••"], spec


def test_provider_env():
    import auto_auth, cloak
    # mock deteksi form + lokasi host
    cloak.js = lambda expr: json.dumps([
        {"type": "password", "name": "pass", "label": "", "placeholder": "",
         "selector": "[name='pass']"},
    ]) if "querySelectorAll" in expr else "example.com"
    import subprocess
    script = 'import sys,json; d=json.load(sys.stdin); print(json.dumps({"pass":"x1"}))'
    env = dict(os.environ, CLOAK_CREDENTIALS_CMD=f"python3 -c {json.dumps(script)}")
    old = os.environ.get("CLOAK_CREDENTIALS_CMD")
    os.environ["CLOAK_CREDENTIALS_CMD"] = env["CLOAK_CREDENTIALS_CMD"]
    try:
        r = auto_auth.escalate_credentials()
        assert r["values"] == {"pass": "x1"}, r
        assert r["source"] == "CLOAK_CREDENTIALS_CMD"
    finally:
        os.environ.pop("CLOAK_CREDENTIALS_CMD", None)
        if old:
            os.environ["CLOAK_CREDENTIALS_CMD"] = old
    # tanpa provider -> CredentialProviderError (bukan crash aneh)
    os.environ.pop("CLOAK_CREDENTIALS_CMD", None)
    import shutil
    if not shutil.which("vault-ask"):
        try:
            auto_auth.escalate_credentials()
            raise AssertionError("seharusnya throw CredentialProviderError")
        except auto_auth.CredentialProviderError:
            pass


def _run(coro):
    import server
    return server._get_loop().run_until_complete(coro)


# --- server: dispatch graceful ---
def test_server_graceful_gmail():
    import server, auth
    old = auth.GOOGLE_TOKEN_PATH
    auth.GOOGLE_TOKEN_PATH = "/nonexistent/token.json"
    try:
        out = _run(server.dispatch("gmail_inbox", {}))
        assert "error" in out and "hint" in out, out
    finally:
        auth.GOOGLE_TOKEN_PATH = old


def test_server_unknown_tool():
    import server
    try:
        _run(server.dispatch("tool_yang_tidak_ada", {}))
        raise AssertionError("seharusnya ValueError")
    except ValueError:
        pass


# --- cloak.wait_for_text logika (mock js) ---
def test_wait_for_text():
    import cloak
    orig_js = cloak.js
    cloak.js = lambda expr: "hello agent world"
    try:
        r = cloak.wait_for_text("agent", timeout=2)
        assert r["found"] is True and "waited_s" in r, r
        r2 = cloak.wait_for_text("zzz", timeout=1)
        assert r2["found"] is False and r2["timeout"] is True, r2
    finally:
        cloak.js = orig_js


if __name__ == "__main__":
    print("smoke tests (tanpa browser):")
    check("vault roundtrip", test_vault_roundtrip)
    check("auto_auth field spec", test_field_spec)
    check("auto_auth pluggable provider", test_provider_env)
    check("server gmail graceful", test_server_graceful_gmail)
    check("server unknown tool", test_server_unknown_tool)
    check("cloak.wait_for_text", test_wait_for_text)
    print(f"\n{PASS} PASS, {FAIL} FAIL")
    sys.exit(1 if FAIL else 0)
