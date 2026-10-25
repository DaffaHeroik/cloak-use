#!/usr/bin/env python3
"""cloak-use — MCP server: Browser for AI agents (text-first).

MCP server (stdio JSON-RPC 2.0) di atas browser lokal (Cloak) di
127.0.0.1:9222. Text-first: baca halaman via Accessibility tree, bukan
screenshot. 10-100x lebih cepat + murah dari Browser Use untuk 90% kasus.

Setup (OpenCode / Hermes / Claude / Cursor):
  command: ["/path/to/cloak-use/server.py", "serve"]

CLI debug:
  python3 server.py call browser_status '{}'
  python3 server.py call read_page '{}'
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cloak

TOOLS = [
    {
        "name": "browser_status",
        "description": "Status browser Cloak + daftar tab terbuka. Jalankan pertama kali sebelum tool lain.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_tabs",
        "description": "Daftar tab yang terbuka di browser (url, title).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_tab",
        "description": "Buka tab baru dengan URL. Return info tab.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "attach_tab",
        "description": "Attach ke tab yang sudah terbuka (berdasarkan url/title/index). Wajib sebelum read_page/click_text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url_contains": {"type": "string"},
                "title_contains": {"type": "string"},
                "index": {"type": "integer"},
            },
        },
    },
    {
        "name": "goto",
        "description": "Navigate tab aktif ke URL baru.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_page",
        "description": "Baca halaman sebagai TEKS (Accessibility tree). Pilihan include: 'interactive' (link/button/textbox — buat memutuskan aksi), 'text' (konten artikel), 'all' (semua)._ini 10-100x lebih cepat dari screenshot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include": {"type": "string", "enum": ["interactive", "text", "all"], "default": "interactive"},
                "max_nodes": {"type": "integer", "default": 1500},
            },
        },
    },
    {
        "name": "click_text",
        "description": "Klik element berdasarkan teks yang terlihat (misal 'Sign in', 'Save'). Cari di AX tree, klik pakai real mouse event. Tidak perlu selector CSS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "role": {"type": "string", "default": None},
                "exact": {"type": "boolean", "default": False},
            },
            "required": ["text"],
        },
    },
    {
        "name": "fill",
        "description": "Isi input berdasarkan CSS selector. React-friendly (native value setter + dispatch event).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["selector", "text"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll halaman (down/up).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["down", "up"]},
                "amount": {"type": "integer", "default": 3},
            },
        },
    },
    {
        "name": "eval",
        "description": "Jalankan JavaScript di tab aktif. Power user — hati-hati.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string"},
                "await_promise": {"type": "boolean", "default": False},
            },
            "required": ["expr"],
        },
    },
    {
        "name": "screenshot",
        "description": "Screenshot fallback — HANYA kalau text tidak cukup (canvas, chart, map). Simpan ke path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    },
]


_LOOP = None


def _get_loop():
    import asyncio
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


async def dispatch(name, args):
    args = args or {}
    if name == "browser_status":
        try:
            tabs = cloak.list_tabs()
        except Exception as e:
            return {"online": False, "error": f"browser tidak terjangkau: {e}"}
        return {
            "online": True,
            "tabs": len(tabs),
            "tab_list": [{"url": t["url"][:100], "title": (t["title"] or "")[:60]} for t in tabs],
        }
    if name == "list_tabs":
        tabs = cloak.list_tabs()
        return {"count": len(tabs), "tabs": [{"url": t["url"], "title": t["title"]} for t in tabs]}
    if name == "open_tab":
        info = cloak.attach(new_url=args["url"])
        return info
    if name == "attach_tab":
        return cloak.attach(
            url_contains=args.get("url_contains"),
            title_contains=args.get("title_contains"),
            index=args.get("index"),
        )
    if name == "goto":
        return cloak.goto(args["url"])
    if name == "read_page":
        return cloak.read_page(
            include=args.get("include", "interactive"),
            max_nodes=args.get("max_nodes", 1500),
        )
    if name == "click_text":
        return cloak.click_text(text=args["text"], role=args.get("role"), exact=args.get("exact", False))
    if name == "fill":
        return {"ok": cloak.fill_input(args["selector"], args["text"])}
    if name == "scroll":
        return cloak.scroll(args.get("direction", "down"), args.get("amount", 3))
    if name == "eval":
        v = cloak.js(args["expr"], await_promise=args.get("await_promise", False))
        return {"value": v}
    if name == "screenshot":
        return cloak.screenshot(args.get("path"))
    raise ValueError(f"unknown tool: {name}")


def _result(content):
    return {"content": [{"type": "text", "text": json.dumps(content, ensure_ascii=False, default=str)}]}


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("method") == "initialize":
            resp = {
                "jsonrpc": "2.0", "id": req.get("id"), "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "cloak-use", "version": "1.0.0"},
                },
            }
        elif req.get("method") == "notifications/initialized":
            continue
        elif req.get("method") == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": TOOLS}}
        elif req.get("method") == "tools/call":
            name = req["params"]["name"]
            args = req["params"].get("arguments", {})
            try:
                out = _get_loop().run_until_complete(dispatch(name, args))
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": _result(out)}
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {
                    "content": [{"type": "text", "text": f"error: {e}"}], "isError": True,
                }}
        else:
            resp = {"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "method not found"}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


def cli():
    """Debug CLI: server.py call <tool> '<json args>'"""
    if len(sys.argv) >= 4 and sys.argv[1] == "call":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        try:
            out = _get_loop().run_until_complete(dispatch(name, args))
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        except Exception as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    else:
        print(__doc__)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve_stdio()
    else:
        cli()
