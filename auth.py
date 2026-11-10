"""
Auth layer — OAuth2 token management for Gmail + Microsoft.
Reads tokens from disk, refreshes when needed, never asks for passwords.
Paths overridable via env (default ~/.cloak-use/):
  GOOGLE_TOKEN_PATH, MSAL_TOKEN_PATH
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HOME = Path(os.path.expanduser("~/.cloak-use"))
GOOGLE_TOKEN_PATH = os.environ.get(
    "GOOGLE_TOKEN_PATH", str(DEFAULT_HOME / "google_token.json"))
MSAL_TOKEN_PATH = os.environ.get(
    "MSAL_TOKEN_PATH", str(DEFAULT_HOME / "msal_token_cache.json"))

# --- Google OAuth2 ---

def google_refresh_token():
    """Refresh Google access_token using refresh_token. Returns fresh access_token."""
    tok = json.load(open(GOOGLE_TOKEN_PATH))
    rt = tok.get("refresh_token")
    if not rt:
        raise RuntimeError("Google refresh_token missing — need to re-auth once")

    data = json.dumps({
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": rt,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"Google token refresh failed: {e.code} {body}")

    tok["token"] = res["access_token"]
    tok["expiry"] = time.time() + int(res.get("expires_in", 3600))
    # Save back (but don't overwrite refresh_token if not returned)
    if "refresh_token" in res:
        tok["refresh_token"] = res["refresh_token"]
    with open(GOOGLE_TOKEN_PATH, "w") as f:
        json.dump(tok, f, indent=2)
    return tok["token"]


def _parse_expiry(exp):
    """Parse ISO8601 expiry to float timestamp."""
    if isinstance(exp, (int, float)):
        return float(exp)
    # ISO format: 2026-10-16T11:41:32Z
    try:
        from datetime import datetime, timezone
        dt = datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def google_access_token():
    """Return valid Google access_token, refreshing if expired."""
    tok = json.load(open(GOOGLE_TOKEN_PATH))
    expiry = _parse_expiry(tok.get("expiry", 0))
    if expiry < time.time() + 60:
        return google_refresh_token()
    return tok["token"]


def google_headers():
    """Headers for Google API calls."""
    return {
        "Authorization": f"Bearer {google_access_token()}",
        "Content-Type": "application/json",
    }


def google_api(url, params=None):
    """Call Google API with auto-refresh. Returns parsed JSON."""
    if params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(params)
    req = urllib.request.Request(url, headers=google_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Force refresh and retry once
            google_refresh_token()
            req = urllib.request.Request(url, headers=google_headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        raise


# --- Microsoft / Azure AD OAuth2 ---

def msal_refresh_token():
    """Refresh Microsoft access_token using MSAL cache."""
    cache = json.load(open(MSAL_TOKEN_PATH))
    rt_entry = cache.get("RefreshToken", {})
    # Extract refresh_token string from MSAL serialized format
    rt_str = None
    for k, v in rt_entry.items():
        if isinstance(v, dict):
            secret = v.get("secret", "")
            if len(secret) > 20:
                rt_str = secret
                break
        elif isinstance(v, str) and len(v) > 20:
            rt_str = v
            break
    if not rt_str:
        raise RuntimeError("MSAL refresh_token missing — need to re-auth once")

    app_meta = cache.get("AppMetadata", {})
    client_id = None
    for k in app_meta:
        if "login.microsoftonline.com" in k:
            parts = k.split("-")
            if len(parts) >= 2:
                client_id = parts[-1]
            break
    if not client_id:
        client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

    from urllib.parse import urlencode
    body = urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": rt_str,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"MSAL token refresh failed: {e.code} {body}")

    # Update cache
    at_key = list(cache["AccessToken"].keys())[0]
    rt_key = list(cache["RefreshToken"].keys())[0]
    cache["AccessToken"] = {at_key: {"credential_type": "AccessToken", "secret": res["access_token"]}}
    if "refresh_token" in res:
        cache["RefreshToken"] = {rt_key: {"credential_type": "RefreshToken", "secret": res["refresh_token"]}}
    with open(MSAL_TOKEN_PATH, "w") as f:
        json.dump(cache, f, indent=2)
    return res["access_token"]


def msal_access_token():
    """Return valid Microsoft access_token, refreshing if needed."""
    cache = json.load(open(MSAL_TOKEN_PATH))
    at_entry = cache.get("AccessToken", {})
    for k, v in at_entry.items():
        if isinstance(v, dict):
            secret = v.get("secret", "")
            if len(secret) > 20:
                return secret
        elif isinstance(v, str) and len(v) > 20:
            return v
    return msal_refresh_token()


def msal_headers():
    return {
        "Authorization": f"Bearer {msal_access_token()}",
        "Content-Type": "application/json",
    }


def msal_api(url, params=None):
    """Call Microsoft Graph API with auto-refresh."""
    if params:
        from urllib.parse import urlencode
        url = url + "?" + urlencode(params)
    req = urllib.request.Request(url, headers=msal_headers())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            msal_refresh_token()
            req = urllib.request.Request(url, headers=msal_headers())
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        raise
