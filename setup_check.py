#!/usr/bin/env python3
"""Setup check untuk cloak-use."""
import sys


def main():
    ok = True
    try:
        import websocket  # noqa
        print("[OK]    websocket-client")
    except ImportError:
        print("[MISS]  websocket-client — install: pip install websocket-client")
        ok = False

    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=5) as r:
            import json
            v = json.load(r)
            print(f"[OK]    browser {v.get('Browser')} di 127.0.0.1:9222")
    except Exception as e:
        print(f"[MISS]  browser tidak terjangkau di 127.0.0.1:9222 ({e})")
        ok = False

    try:
        sys.path.insert(0, ".")
        import cloak
        tabs = cloak.list_tabs()
        print(f"[OK]    {len(tabs)} tab terbuka")
    except Exception as e:
        print(f"[MISS]  cloak.py tidak bisa dipanggi: {e}")
        ok = False

    print()
    if ok:
        print("Siap. Jalankan: python3 server.py serve")
    else:
        print("Ada yang kurang — lihat [MISS] di atas.")
        sys.exit(1)


if __name__ == "__main__":
    main()
