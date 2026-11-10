"""
Auto-auth for cloak-use — deteksi form login, eskalasi kredensial via
credential provider, isi form dari vault / hasil provider. TANPA auto-submit:
submit = keputusan sadar, pakai click_text / eval.

Alur:
  detect_login_form()        → field apa yang dibutuhkan halaman ini
  escalate_credentials()     → CLOAK_CREDENTIALS_CMD atau CLI vault-ask
  fill_fields(values)        → isi form via cloak.fill_input (tanpa submit)
  check_login_result()       → heuristik pasca-submit
  save_session_after_login() → simpan cookie, login sekali cukup
"""
import json
import os
import shutil
import subprocess

import cloak
from vault import get_credential, save_session


class CredentialProviderError(RuntimeError):
    """Gagal escalate kredensial (provider gak ada / Bos gak submit)."""

# field type yang bisa muncul di form (subset umum)
_FIELD_DETECTOR = """
(() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('input, select').forEach(el => {
    const type = (el.type || '').toLowerCase();
    if (!['text','email','password','number','tel','search'].includes(type)) return;
    const name = el.name || el.id || '';
    const key = type + '|' + name;
    if (seen.has(key)) return;
    seen.add(key);
    let label = '';
    if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]'); if (l) label = l.textContent.trim(); }
    const ph = el.placeholder || '';
    out.push({
      type: type,
      name: name,
      label: label.slice(0, 60),
      placeholder: ph.slice(0, 60),
      selector: name ? '[name=' + JSON.stringify(name) + ']' : (el.id ? '#' + el.id : null),
    });
  });
  return out;
})()
"""


def detect_login_form():
    """Deteksi field input di halaman. Return list {type, name, label, ...}.

    Heuristik: form login = ada input password, atau ada input email/username
    + input password. Kalau ada input lain (captcha, otp, tfa), field itu
    ikut dilaporkan supaya vault-ask bisa minta semuanya sekaligus.
    """
    raw = cloak.js(_FIELD_DETECTOR)
    fields = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return fields


def _pick_fields(fields):
    """Pilih field yang relevan untuk eskalasi: email/username, password,
    dan field non-asli (otp/captcha/tfa/verify) yang tidak bisa ditebak."""
    picked = []
    for f in fields:
        if f.get("selector") is None:
            continue
        t = f.get("type", "")
        ident = t in ("email", "tel", "number") or "user" in (f.get("name", "") + f.get("label", "")).lower() or "email" in (f.get("name", "") + f.get("label", "")).lower()
        if t == "password" or ident:
            picked.append(f)
        elif t == "text":
            blob = (f.get("name", "") + f.get("label", "") + f.get("placeholder", "")).lower()
            if any(k in blob for k in ("captcha", "otp", "code", "verif", "tfa", "one-time", "2fa")):
                picked.append(f)
    return picked


def _vault_field_spec(f):
    """Field terdeteksi → spec vault-ask 'NAMA|TYP|LABEL|PLACEHOLDER'."""
    name = f.get("name") or ("password" if f.get("type") == "password" else "field")
    name = "".join(c for c in name if c.isalnum() or c in "._-")[:64] or "field"
    typ = "password" if f.get("type") == "password" else "text"
    label = f.get("label") or f.get("placeholder") or name
    place = f.get("placeholder") or ("••••••" if typ == "password" else "")
    return f"{name}|{typ}|{label}|{place}"


def escalate_credentials(context=""):
    """Minta kredensial sesuai form yang terdeteksi.

    Provider (urutan):
      1. env CLOAK_CREDENTIALS_CMD — command custom. Terima 1 arg: JSON
         {"specs": [...], "context": "..."}; harus return JSON
         {field_name: value} di stdout. Ini escape hatch untuk mesin
         yang gak punya vault-ask (PWA, secret manager, dsb).
      2. CLI vault-ask di PATH (default, ekosistem hero-app Bos) —
         add+wait, form nembak HP.
      3. gak ada dua-duanya → CredentialProviderError dengan panduan.
    """
    fields = _pick_fields(detect_login_form())
    if not fields:
        raise RuntimeError("tidak ada field login yang terdeteksi di halaman ini")
    specs = [_vault_field_spec(f) for f in fields]
    ctx = context or f"login {cloak.js('location.host')}"

    custom = os.environ.get("CLOAK_CREDENTIALS_CMD", "").strip()
    if custom:
        payload = json.dumps({"specs": specs, "context": ctx})
        r = subprocess.run(custom, shell=True, input=payload,
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise CredentialProviderError(
                f"CLOAK_CREDENTIALS_CMD exit {r.returncode}: {r.stderr.strip()[:200]}")
        try:
            values = json.loads(r.stdout.strip() or "{}")
        except json.JSONDecodeError:
            values = {fields[0].get("name") or "password": r.stdout.strip()}
        return {"values": values, "source": "CLOAK_CREDENTIALS_CMD"}

    if shutil.which("vault-ask"):
        return _escalate_via_vault_ask(specs, ctx, fields)
    raise CredentialProviderError(
        "vault-ask tidak tersedia di PATH dan CLOAK_CREDENTIALS_CMD belum set. "
        "Pilih: (a) pasang vault-ask (ekosistem hero-app), (b) set CLOAK_CREDENTIALS_CMD "
        "ke command yang return JSON {field: value}, (c) minta kredensial ke owner via chat.")


def _escalate_via_vault_ask(specs, ctx, fields):
    r = subprocess.run(
        ["vault-ask", "add"] + specs + ["--ctx", ctx],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise CredentialProviderError(
            f"vault-ask add gagal (server down?): {r.stderr.strip()[:200]}")
    ask_id = ""
    for line in r.stderr.splitlines():
        if line.startswith("askId:"):
            ask_id = line.split(":", 1)[1].strip()
    if not ask_id:
        # beberapa versi print JSON {id: ...} di stdout
        try:
            ask_id = json.loads(r.stdout.strip().splitlines()[-1]).get("id", "")
        except Exception:
            pass
    if not ask_id:
        raise CredentialProviderError(
            f"vault-ask add tidak menghasilkan askId: {r.stdout[:200]}")

    w = subprocess.run(
        ["vault-ask", "wait", ask_id, "--timeout", "600"],
        capture_output=True, text=True, timeout=660,
    )
    if w.returncode != 0:
        raise CredentialProviderError(
            f"vault-ask wait gagal/batal: {w.stderr.strip()[:200]}")
    out = w.stdout.strip()
    try:
        values = json.loads(out)  # multi-field
    except json.JSONDecodeError:
        values = {(fields[0].get("name") or "password"): out}  # single-field
    return {"values": values, "source": "vault-ask"}


def get_from_local_vault(host):
    """Credential sudah tersimpan? (setelah login pertama via save_credentials)."""
    base = host.replace("www.", "")
    return get_credential(base)


def fill_fields(values, fields=None):
    """Isi form dari dict values (field_name → value). TANPA submit.

    values boleh berupa output escalate_credentials()['values'] atau hasil
    local vault {username, password}. Return list field yang terisi.
    """
    if fields is None:
        fields = detect_login_form()
    filled = []
    # match: key values ↔ field.name; fallback untuk {username,password}
    norm = {}
    for k, v in values.items():
        kl = k.lower()
        if "pass" in kl:
            keymap = "password"
        elif "user" in kl or "email" in kl:
            keymap = "username"
        else:
            keymap = k
        norm[keymap] = v

    for f in fields:
        name = f.get("name") or ""
        val = values.get(name)
        if val is None:
            # fallback map
            if f.get("type") == "password":
                val = norm.get("password")
            elif "email" in name.lower() or "user" in name.lower():
                val = norm.get("username")
        if val is None:
            continue
        sel = f.get("selector")
        if not sel:
            continue
        cloak.fill_input(sel, str(val))
        filled.append(name or sel)
    return {"filled": filled, "note": "form terisi — submit manual via click_text / eval"}


def check_login_result():
    """Heuristik: halaman setelah submit. True = terlihat berhasil,
    False = ada error, None = tidak bisa dipastikan (verifikasi manual)."""
    url = cloak.js("location.href") or ""
    body = (cloak.js("document.body ? document.body.innerText.slice(0, 4000)" ) or "").lower()
    errors = ["incorrect", "invalid", "wrong password", "wrong username", "not found",
              "failed to", "account locked", "verify your identity", "check your",
              "salah", "tidak valid", "密码错误", "账号或密码错误"]
    successes = ["logout", "log out", "sign out", "beranda", "profile", "your activity"]
    if any(e in body for e in errors):
        return False
    if any(s in body for s in successes) and "login" not in url:
        return True
    return None


def save_session_after_login(host):
    """Simpan cookie setelah login sukses (verifikasi manual oleh agent/Bos)."""
    base = host.replace("www.", "")
    cookies = cloak.send("Network.getAllCookies", timeout=10).get("cookies", [])
    relevant = [c for c in cookies if base in c.get("domain", "")]
    save_session(base, relevant)
    return {"domain": base, "cookies": len(relevant)}
