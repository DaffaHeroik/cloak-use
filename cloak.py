#!/usr/bin/env python3
"""Cloak core — CDP client untuk browser lokal di 127.0.0.1:9222.

Text-first browser automation. AX tree (Accessibility tree) adalah representation
utama, bukan screenshot. Alasan:

  Screenshot-driven (Browser Use style):
    setiap step = screenshot -> vision model -> decision -> screenshot...
    1 langkah = 5-30 detik + ribuan token gambar. Untuk baca 1 halaman = menit.

  Text-driven (cloak-use):
    Accessibility.getFullAXTree -> JSON teks -> langsung ke LLM.
    1 halaman = 2 detik, ~500 token. 10-100x lebih murah.

Browser target diatur via env CLOAK_BROWSER_URL (default ws:///json endpoint
di 127.0.0.1:9222). One Python process holds the websocket for the whole flow.
"""
import json
import os
import threading
import time
import urllib.request

import websocket

PORT = int(os.environ.get("CLOAK_PORT", "9222"))
HOST = os.environ.get("CLOAK_HOST", "127.0.0.1")

_id = 0
_ws = None
_lock = threading.Lock()
_events = []
_connected_tab = None


# ---------------------------------------------------------------------------
# Tab management
# ---------------------------------------------------------------------------

def list_tabs(pages_only=True):
    """List open targets. Setiap entry bawa webSocketDebuggerUrl sendiri."""
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/json", timeout=5) as r:
        tabs = json.load(r)
    if pages_only:
        tabs = [t for t in tabs if t["type"] == "page"]
    return tabs


def find_tab(url_contains=None, title_contains=None, index=None):
    """Cari tab berdasarkan URL/title/cursor. Return dict atau None."""
    tabs = list_tabs()
    if index is not None:
        return tabs[index] if 0 <= index < len(tabs) else None
    for t in tabs:
        if url_contains and url_contains in t.get("url", ""):
            return t
        if title_contains and title_contains.lower() in (t.get("title") or "").lower():
            return t
    return None


def connect(ws_url):
    """Attach ke 1 tab. Semua js()/send() berikutnya ke tab ini."""
    global _ws, _connected_tab
    _ws = websocket.create_connection(ws_url, timeout=60)
    _connected_tab = ws_url
    return _ws


def attach(url_contains=None, title_contains=None, index=None, new_url=None):
    """Attach ke tab (atau buka baru). Return info tab yang aktif.

    new_url: kalau set, buka tab baru dengan URL ini (Target.createTarget).
    """
    global _ws, _connected_tab
    if new_url is not None:
        # Target.createTarget butuh browser-level socket
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/json/version", timeout=5) as r:
            browser_ws = json.load(r)["webSocketDebuggerUrl"]
        tmp = websocket.create_connection(browser_ws, timeout=30)
        mid = 0
        tmp.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": new_url}}))
        end = time.time() + 30
        target_id = None
        while time.time() < end:
            try:
                tmp.settimeout(1)
                m = json.loads(tmp.recv())
                if m.get("id") == 1:
                    target_id = m.get("result", {}).get("targetId")
                    break
            except Exception:
                break
        tmp.close()
        time.sleep(1.5)  # kasih waktu load
        tab = find_tab(url_contains=new_url if len(new_url) < 60 else None)
        if tab is None:
            tabs = list_tabs()
            tab = tabs[-1]
    else:
        tab = find_tab(url_contains, title_contains, index)
        if tab is None:
            raise RuntimeError(f"tab tidak ketemu (url={url_contains}, title={title_contains}, index={index})")
    connect(tab["webSocketDebuggerUrl"])
    send("Page.enable")
    send("Runtime.enable")
    return {"url": tab["url"], "title": tab["title"], "ws": tab["webSocketDebuggerUrl"]}


def detach():
    global _ws, _connected_tab
    if _ws:
        _ws.close()
    _ws = None
    _connected_tab = None


# ---------------------------------------------------------------------------
# Low-level CDP
# ---------------------------------------------------------------------------

def _drain_events():
    out = []
    try:
        _ws.settimeout(1)
    except Exception:
        pass
    while True:
        try:
            m = json.loads(_ws.recv())
        except Exception:
            break
        if m.get("method"):
            _events.append(m)
        elif m.get("id"):
            out.append(m)
    return out


def send(method, params=None, timeout=30):
    global _id
    with _lock:
        _id += 1
        mid = _id
        _ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            for resp in _drain_events():
                if resp.get("id") == mid:
                    if "error" in resp:
                        raise RuntimeError(f"{method}: {resp['error']}")
                    return resp.get("result", {})
            time.sleep(0.05)
        raise TimeoutError(f"{method} timeout")


def js(expr, await_promise=False, timeout=30):
    """Runtime.evaluate. Tidak ada ceiling 5 detik — promise boleh di-await."""
    global _id
    with _lock:
        _id += 1
        mid = _id
        _ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise,
        }}))
        end = time.time() + timeout
        while time.time() < end:
            for resp in _drain_events():
                if resp.get("id") == mid:
                    if "error" in resp:
                        raise RuntimeError(f"JS error: {resp['error']}")
                    r = resp.get("result", {})
                    if r.get("exceptionDetails"):
                        raise RuntimeError(
                            "JS exception: " +
                            r['exceptionDetails'].get('exception', {}).get('description', str(r['exceptionDetails']))
                        )
                    return r.get("result", {}).get("value")
            time.sleep(0.05)
        raise TimeoutError("js timeout: " + expr[:60])


def click(x, y, button="left"):
    """Real input events via CDP. Turnstile checkbox & canvas UI ignore
    synthesized JS MouseEvents — ini kunci bypass widget interactive."""
    send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none", "clickCount": 0})
    send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": button, "clickCount": 1})
    send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": button, "clickCount": 1})


def fill_input(selector, text):
    """Isi input pakai native value setter + dispatch event (React-friendly)."""
    js(f"""
    (() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) throw new Error('element not found: {selector}');
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, {json.dumps(text)});
      el.dispatchEvent(new Event('input', {{ bubbles: true }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      return true;
    }})()
    """)


def wait(t):
    time.sleep(t)


def drain_events():
    """Pop collected events (console / network / dll)."""
    with _lock:
        out, _events[:] = _events[:], []
        return out


# ---------------------------------------------------------------------------
# Text-first page reading — ini inti dari "fast"
# ---------------------------------------------------------------------------

def _ax_name(n):
    v = n.get("name", {}).get("value")
    return v if v else None


def _ax_role(n):
    return n.get("role", {}).get("value")


def read_page(max_nodes=1500, include="interactive", tree=None):
    """Baca halaman sebagai TEXT dari Accessibility tree.

    tree: opsional, hasil wait_for_load(return_tree=True) atau poll sendiri.
    Kalikasih, kita skip getFullAXTree (hemat ~1s). 'goto_fast' menggabungkan
    keduanya jadi 1 panggilan.

    include:
      'interactive' — link, button, textbox, menuitem, tab, dll (default).
                      Ini yang agent butuh buat memutuskan tindakan.
      'all'         — semua node termasuk StaticText (snapshot teks penuh).
      'text'        — cuma StaticText + heading (baca konten artikel).

    Return dict: url, title, node count, dan lines (role: name).
    """
    if tree is None:
        tree = send("Accessibility.getFullAXTree", timeout=60)
    nodes = tree.get("nodes", [])
    title = js("document.title")
    url = js("location.href")

    INTERACTIVE = {
        "link", "button", "textbox", "searchbox", "checkbox", "radio",
        "menuitem", "menuitemcheckbox", "tab", "combobox", "option",
        "switch", "slider", "spinbutton", "treeitem", "listboxoption",
        "menubar", "menu", "progressbar", "scrollbar",
    }
    TEXT_ROLES = {"StaticText", "heading", "paragraph", "article", "section", "list", "listitem"}

    def pick(n):
        role = _ax_role(n)
        if include == "all":
            return True
        if include == "interactive":
            return role in INTERACTIVE
        if include == "text":
            return role in TEXT_ROLES or role in {"StaticText", "heading"}
        return True

    lines = []
    kept = 0
    for n in nodes:
        if not pick(n):
            continue
        name = _ax_name(n)
        role = _ax_role(n) or "?"
        if not name and role not in ("menu", "menubar"):
            continue
        # skip node duplikat (AX tree sering duplikat name dengan parent)
        line = f"{role}: {name}" if name else f"{role}"
        lines.append(line)
        kept += 1
        if kept >= max_nodes:
            break

    return {
        "url": url,
        "title": title,
        "nodes_total": len(nodes),
        "nodes_kept": kept,
        "lines": lines,
    }


def click_text(text, role=None, exact=False):
    """Klik element berdasarkan TEKS yang terlihat.

    Urutan: (1) AX tree + boxModel + real mouse events (paling natural),
    (2) fallback DOM querySelector + JS click kalau AX tree tidak nampak
    node-nya (modal/portal state, lazy render).
    """
    ax = send("Accessibility.getFullAXTree", timeout=60)
    nodes = ax.get("nodes", [])
    best = None
    for n in nodes:
        name = _ax_name(n)
        r = _ax_role(n)
        if not name:
            continue
        if role and r != role:
            continue
        match = (name == text) if exact else (text.lower() in name.lower())
        if match and r in {"link", "button", "menuitem", "tab", "checkbox", "radio", "switch", "textbox"}:
            best = n
            break
    if best is not None:
        backend = best.get("backendDOMNodeId")
        if backend:
            box = send("DOM.getBoxModel", {"backendNodeId": backend}, timeout=15)
            model = box.get("model", box)
            quad = model.get("border") or model.get("content") or model.get("content_quad") or []
            if quad and isinstance(quad[0], (int, float)):
                flat = quad
                quad = [[flat[i], flat[i + 1]] for i in range(0, len(flat) - 1, 2)]
            if quad and len(quad) >= 4:
                xs = [p[0] for p in quad]
                ys = [p[1] for p in quad]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                click(cx, cy)
                return {"clicked": text, "role": _ax_role(best), "at": [round(cx), round(cy)], "via": "ax+mouse"}
    # Fallback: DOM click (kalau AX tree tidak nampak node, mis. modal portal)
    hit = js(f"""
    (() => {{
      const els = Array.from(document.querySelectorAll('button, a, [role=button], [role=link]'));
      const el = els.find(e => e.textContent.trim().toLowerCase().includes({json.dumps(text.lower())}));
      if (!el) return null;
      el.click();
      return el.textContent.trim().slice(0, 60);
    }})()
    """)
    if hit:
        return {"clicked": text, "via": "dom-fallback", "text": hit}
    raise RuntimeError(f"element tidak ketemu: text='{text}' role={role}")


def scroll(direction="down", amount=3):
    """Scroll halaman."""
    dy = amount * 500 if direction == "down" else -amount * 500
    js(f"window.scrollBy(0, {dy})")
    wait(0.8)
    return {"scrolled": direction, "amount": amount}


def wait_for_load(timeout=15, return_tree=False):
    """Tunggu sampai loading settle — readyState + AX tree stabil.

    readyState=complete itu stage DOM parsed, BUKAN stage SPA selesai render.
    Angular/React/Next biasanya render dampak setelah itu. Kalau kita langsung
    baca, AX tree-nya masih kosong / setengah. Makanya kita poll AX tree sampai
    node count-nya stabil 2 poll berturut-turut.

    return_tree=True: kasih back tree terakhir (sudah di-fetch anyway) supaya
    read_page gak perlu getFullAXTree LAGI (hemat ~1s per page read).
    """
    # Stage 1: readyState
    end = time.time() + timeout
    while time.time() < end:
        if js("document.readyState") == "complete":
            break
        wait(0.2)
    # Stage 2: AX tree — tunggu sampai ada node lalu stabil
    tree = None
    prev = -1
    stable = 0
    end = time.time() + min(timeout, 8)
    while time.time() < end:
        try:
            r = send("Accessibility.getFullAXTree", timeout=10)
            n = len(r.get("nodes", []))
            if n > 0:
                tree = r
        except Exception:
            break
        if n == prev and n > 0:
            stable += 1
            if stable >= 1:
                break
        else:
            stable = 0
        prev = n
        wait(0.3)
    wait(0.2)
    if return_tree:
        return tree


def goto(url, wait_ms=1200):
    """Navigate tab ke URL baru, lalu tunggu render SPA settle."""
    send("Page.navigate", {"url": url})
    wait(wait_ms / 1000.0)
    wait_for_load(timeout=10)
    return {"url": url, "title": js("document.title")}


def goto_fast(url, include="interactive", max_nodes=1500):
    """Navigate + baca halaman dalam SATU putaran.

    Kompak: navigate -> tunggu SPA settle (AX tree terbentuk) -> langsung
    extract lines dari tree yang sama. Skip 1 AX fetch + 1 round trip.

    vs goto()+read_page(): hemat ~1.5-2s per navigasi.
    """
    send("Page.navigate", {"url": url})
    tree = wait_for_load(timeout=10, return_tree=True)
    return read_page(max_nodes=max_nodes, include=include, tree=tree)


def screenshot(path=None):
    """Screenshot — dipakai HANYA kalau text tidak cukup (canvas, map, chart)."""
    params = {"format": "png"}
    if path:
        params["clip"] = None
    r = send("Page.captureScreenshot", params, timeout=30)
    import base64
    data = base64.b64decode(r["data"])
    if path:
        with open(path, "wb") as f:
            f.write(data)
        return {"path": path, "bytes": len(data)}
    return {"bytes": len(data), "note": "not saved (no path)"}
