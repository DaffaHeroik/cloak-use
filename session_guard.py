"""
session_guard — cegah SSO persisten (Google/Microsoft/GitHub) mati diam-diam.

Lapis pertahanan (semua sudah di-apply, ini lapis terakhir):
  1. IP stabil: domain SSO bypass proxy (lihat hero-cloak-browser.service)
  2. Fingerprint & locale tetap (flag --fingerprint di config yang sama)
  3. GUARD INI: tiap 30 menit cek halaman status sesi; kalau ketemu halaman
     login lagi → auto-restore cookie dari vault (session_manager) + log event.
     Snapshot cookie di-refresh tiap kali sesi terkonfirmasi hidup.

Run:
  python3 session_guard.py            # cek sekali, print JSON
  via systemd timer: cloak-session-guard.timer (setiap 30 menit)
Env:
  CLOAK_GUARD_DOMAINS  default "google,microsoft,github"
  CLOAK_GUARD_LOG      default ~/.cloak-use/session_guard.log
"""
import json
import os
import time
import urllib.request

import cloak
from session_manager import (
    is_session_valid,
    restore_session,
    save_current_session,
)

CHECK_URLS = {
    # URL yang HARUS menampilkan data user kalau sesi hidup
    # (redirect ke login kalau mati)
    "google": "https://mail.google.com",
    "microsoft": "https://outlook.office.com/mail",
    "github": "https://github.com/settings",
}
# URL mengandung salah satu hint ini = sesi sudah ketendang (login form)
LOGIN_HINTS = {
    "google": ("accounts.google.com", "signin", "challenge/pwd"),
    "microsoft": ("login.live.com", "login.microsoftonline.com", "signin."),
    "github": ("login.github.com", "github.com/login"),
}
SETTLE_S = 6  # tunggu SPA redirect selesai


def _probe(domain, url):
    """Return {url, login, title} setelah navigate ke url di tab baru."""
    cloak.attach(new_url=url)
    time.sleep(SETTLE_S)
    href = str(cloak.js("location.href") or "")
    pw = bool(cloak.js("!!document.querySelector('input[type=password]')"))
    title = str(cloak.js("document.title") or "")
    hints = LOGIN_HINTS.get(domain, ("signin",))
    login = any(h in href.lower() for h in hints) or pw
    return {"url": href, "login": login, "title": title[:80]}


def _close_probe(domain):
    """Tutup tab probe + detach (biarin profil login asli Bos gak nyentuh)."""
    for target in (CHECK_URLS.get(domain, ""), *LOGIN_HINTS.get(domain, ())):
        if not target:
            continue
        try:
            cloak.close_tab(url_contains=target)
            break
        except Exception:
            continue
    cloak.detach()


def _log_event(entry):
    path = os.environ.get(
        "CLOAK_GUARD_LOG",
        os.path.join(os.path.expanduser("~/.cloak-use"), "session_guard.log"),
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def check_domain(domain):
    """1 domain: probe -> expired? -> restore -> probe ulang. Return report."""
    url = CHECK_URLS[domain]
    r = _probe(domain, url)
    state = "expired" if r["login"] else "active"

    if state == "active":
        # SELALU refresh snapshot: snapshot lama (mis. cookie yang sudah
        # di-revoke server) gak boleh numpang di vault — kalau gak,
        # restore berikutnya pulihkan cookie basi & loop 'revoked'.
        save_current_session(domain)
        r["snapshot"] = "refreshed"
        _log_event({"domain": domain, "state": "active", "snapshot": "refreshed"})
    elif state == "expired":
        if is_session_valid(domain):
            restore_session(domain)
            r2 = _probe(domain, url)
            state = "active" if not r2["login"] else "revoked-server-side"
            r2["restored"] = True
            r2["state"] = state
            _log_event({"domain": domain, "state": state, "restored": True})
            _close_probe(domain)
            return {**r2, "snapshot_age_ok": True}
        else:
            _log_event({"domain": domain, "state": "expired",
                        "reason": "no valid snapshot in vault"})
            r["hint"] = ("snapshot vault kosong/ basi — login manual sekali "
                         "(noVNC :6080), guard akan menyimpan otomatis")
    _close_probe(domain)
    return {**r, "state": state}


def run_check(domains=None):
    if domains is None:
        domains = [d.strip() for d in
                   os.environ.get("CLOAK_GUARD_DOMAINS", "google,microsoft,github").split(",")
                   if d.strip() in CHECK_URLS]
    report = {"domains": {}, "checked": time.strftime("%Y-%m-%d %H:%M:%S")}
    for d in domains:
        try:
            report["domains"][d] = check_domain(d)
        except Exception as e:
            report["domains"][d] = {"state": "error", "error": str(e)[:200]}
        cloak.detach()
    return report


if __name__ == "__main__":
    print(json.dumps(run_check(), ensure_ascii=False, indent=2))
