"""
Local credential vault — obfuscated storage for login credentials + session
cookies. Auto-save setelah login pertama, auto-fill di kunjungan berikutnya.
JANGAN simpan hal yang benar-benar rahasia di sini (XOR+base64, bukan
enkripsi kriptografis) — untuk kredensial penting pakai secret manager.
"""
import base64
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

VAULT_PATH = Path(os.environ.get(
    "CLOAK_VAULT_PATH",
    os.path.join(os.environ.get("CLOAK_USE_HOME",
                                os.path.expanduser("~/.cloak-use")),
                 "vault.json"),
))
# default fixed buat portofolio/VPS; override via CLOAK_VAULT_KEY kalau mau
VAULT_KEY = (os.environ.get("CLOAK_VAULT_KEY")
             or hashlib.sha256(b"cloak-use-vault-hero-2026").digest())
if isinstance(VAULT_KEY, str):
    VAULT_KEY = hashlib.sha256(VAULT_KEY.encode()).digest()

def _encrypt(data: str) -> str:
    """Simple XOR + base64 (not military grade, but good enough for local VPS)."""
    key = VAULT_KEY[:len(data)]
    xored = bytes(a ^ b for a, b in zip(data.encode(), key))
    return base64.b64encode(xored).decode()

def _decrypt(token: str) -> str:
    """Decrypt vault entry."""
    try:
        raw = base64.b64decode(token.encode())
        key = VAULT_KEY[:len(raw)]
        xored = bytes(a ^ b for a, b in zip(raw, key))
        return xored.decode()
    except Exception:
        return ""

def _load():
    if VAULT_PATH.exists():
        return json.loads(VAULT_PATH.read_text())
    return {"credentials": {}, "sessions": {}}

def _save(data):
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VAULT_PATH.write_text(json.dumps(data, indent=2))

def save_credential(domain: str, username: str, password: str):
    """Save login credential for a domain."""
    data = _load()
    data["credentials"][domain] = {
        "username": _encrypt(username),
        "password": _encrypt(password),
        "saved_at": datetime.utcnow().isoformat()
    }
    _save(data)

def get_credential(domain: str):
    """Get credential for a domain. Returns (username, password) or (None, None)."""
    data = _load()
    entry = data.get("credentials", {}).get(domain)
    if entry:
        return _decrypt(entry["username"]), _decrypt(entry["password"])
    return None, None

def save_session(domain: str, cookies: dict):
    """Save session cookies for a domain."""
    data = _load()
    data["sessions"][domain] = {
        "cookies": cookies,
        "saved_at": datetime.utcnow().isoformat()
    }
    _save(data)

def get_session(domain: str):
    """Get saved session for a domain."""
    data = _load()
    return data.get("sessions", {}).get(domain)

def list_domains():
    """List all domains with saved credentials."""
    data = _load()
    return list(data.get("credentials", {}).keys())

def is_logged_in(domain: str):
    """Check if we have valid session for domain."""
    session = get_session(domain)
    if not session:
        return False
    # Check if session is less than 7 days old
    saved = session.get("saved_at", "")
    if not saved:
        return False
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(saved)).total_seconds()
        return age < (7 * 24 * 3600)  # 7 days
    except Exception:
        return False
