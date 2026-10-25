#!/usr/bin/env python3
"""Flow runner — jalanin multi-step browser flow di SATU process.

Latar belakang: setiap `python3 -c "..."` itu spawn process baru, reconnect
websocket, Page.enable+Runtime.enable (2 round trip), lalu sleep 3-4 detik
untuk SPA. 5 langkah = 5 x (1.5s startup + 4s sleep) = 25-30 detik buang-buang.

Flow ini: attach SEKALI, tunggu element pakai selector poll (300ms interval),
tanpa read_page full (3s) — coba DOM probe langsung yang ~50ms.

Usage:
    python3 flow.py threads_login
    python3 flow.py gmail_check
"""
import json
import sys
import time

sys.path.insert(0, "/root/cloak-use")
import cloak


def q(sel):
    """DOM probe cepat — return text atau None. ~50ms, bikan 3s AX tree."""
    return cloak.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); return e ? (e.value || e.textContent || '').trim().slice(0, 200) : null; }})()")


def exists(sel):
    return cloak.js(f"!!document.querySelector({json.dumps(sel)})")


def wait_el(sel, timeout=20):
    """Tunggu sampai selector muncul. Poll 300ms, return True/False."""
    end = time.time() + timeout
    while time.time() < end:
        if exists(sel):
            return True
        time.sleep(0.3)
    return False


def wait_gone(sel, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if not exists(sel):
            return True
        time.sleep(0.3)
    return False


def snapshot(lines=40):
    """AX snapshot tipis (hanya interactive, max 40) — untuk decision."""
    p = cloak.read_page(include="interactive", max_nodes=lines)
    return p


def comment(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Flow: Threads login via Instagram SSO
# ---------------------------------------------------------------------------

def threads_login():
    t_start = time.time()
    comment("attach ke tab threads...")
    try:
        cloak.attach(url_contains="threads.com")
    except Exception:
        cloak.attach(new_url="https://www.threads.com/")
        time.sleep(3)

    url = cloak.js("location.href")
    comment(f"url: {url[:70]}")

    # kalau sudah login (ada tombol create), done
    if cloak.js(
        '!!Array.from(document.querySelectorAll("button")).find(b=>b.textContent.includes("Create")||b.textContent.includes("创建")||b.textContent.includes("Buat"))'
    ):
        comment("SUDAH LOGIN — langsung ke home")
        return home_brief(t_start)

    # belum login → klik login
    comment("klik tombol Login (Instagram)...")
    cloak.js("""
      (() => {
        const btn = Array.from(document.querySelectorAll('button, a, [role=button]'))
          .find(e => e.textContent.toLowerCase().includes('instagram') || e.textContent.includes('登录'));
        if (btn) { btn.click(); return true; } return false;
      })()
    """)
    time.sleep(2)

    # Instagram SSO page: tunggu input username muncul
    comment("tunggu form Instagram SSO...")
    if wait_el('input[name=username]', timeout=25):
        comment("form SSO muncul — Instagram minta login")
        return {"status": "need_instagram_credentials", "elapsed": round(time.time() - t_start, 1)}
    comment("form SSO tidak muncul, cek state...")
    p = snapshot()
    return {"status": "unknown", "lines": p["lines"][:20], "elapsed": round(time.time() - t_start, 1)}


def home_brief(t_start):
    p = snapshot()
    comment(f"LOGIN OK, {p['nodes_kept']} elements")
    out = [l for l in p["lines"][:20]]
    return {"status": "logged_in", "lines": out, "elapsed": round(time.time() - t_start, 1)}


# ---------------------------------------------------------------------------
# Flow: Gmail check
# ---------------------------------------------------------------------------

def gmail_check():
    t_start = time.time()
    comment("buka Gmail...")
    try:
        cloak.attach(url_contains="mail.google.com")
    except Exception:
        cloak.attach(new_url="https://mail.google.com/")
        time.sleep(3)

    # tunggu inbox loaded
    comment("tunggu inbox...")
    ok = wait_el('div[role=main]', timeout=25)
    if not ok:
        return {"status": "gmail_load_fail", "elapsed": round(time.time() - t_start, 1)}

    title = cloak.js("document.title")
    comment(f"title: {title}")
    # hitung unread
    unread = cloak.js("""
      (() => {
        const rows = document.querySelectorAll('tr.zA');
        let unread = 0;
        rows.forEach(r => { if (r.querySelector('.bA4')) unread++; });
        return unread;
      })()
    """)
    emails = cloak.js("""
      (() => {
        const rows = Array.from(document.querySelectorAll('tr.zA')).slice(0, 10);
        return rows.map(r => {
          const from = r.querySelector('.bog') ? r.querySelector('.bog').textContent.trim() : '';
          const subj = r.querySelector('.bog + span') ? r.querySelector('.bog + span').textContent.trim() : '';
          return from + ' | ' + subj;
        }).filter(x => x);
      })()
    """)
    return {
        "status": "ok",
        "title": title,
        "unread_est": unread,
        "emails": (emails or [])[:10],
        "elapsed": round(time.time() - t_start, 1),
    }


FLOWS = {
    "threads_login": threads_login,
    "gmail_check": gmail_check,
}


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "threads_login"
    fn = FLOWS.get(name)
    if not fn:
        print(f"flow tidak ada: {name}. Tersedia: {list(FLOWS)}")
        sys.exit(1)
    result = fn()
    print()
    print(json.dumps(result, ensure_ascii=False, indent=1))
