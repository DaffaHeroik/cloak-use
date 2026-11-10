# cloak-use

**Browser untuk AI agent — text-first, bukan screenshot.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org)

MCP server + engine CDP + CLI + daemon + auth layer, semua di 1 repo.
BACA halaman lewat Accessibility tree sebagai **teks**: 1 halaman ≈ 2 detik,
~500 token. Bandingkan screenshot-driven agent (Browser Use): 5-30 detik per
langkah + ribuan token gambar. **90% lebih cepat, 99% lebih murah** untuk 90%
kasus web automation.

Contribute? Baca [CONTRIBUTING.md](CONTRIBUTING.md) — issue & PR disambut.

```
          ┌─────────────────────────────────────────────────────┐
          │  Browser Cloak (anti-detect, profil login asli)     │
          │  CDP :9222                                          │
          └──────────────┬──────────────────────┬───────────────┘
                         │                      │
              ┌──────────▼──────────┐   ┌───────▼─────────────┐
              │ cloak.py (engine)   │   │ cbd (daemon unix-    │
              │ CDP websocket       │   │ socket, ~0.02s/kick) │
              │ + 26 tools MCP      │   └───────┬─────────────┘
              │ (server.py)         │           │
              └──────────┬──────────┘   ┌───────▼─────────────┐
                         │             │ cb (CLI manusia)     │
              ┌──────────▼──────────┐  └─────────────────────┘
              │ Auth layer          │
              │ vault + auto_auth   │
              │ + Gmail/To Do API   │
              └─────────────────────┘
```

## Kenapa bukan Browser Use / Playwright?

| | cloak-use | Browser Use |
|---|---|---|
| Representasi halaman | AX tree → **teks** | screenshot → vision model |
| 1 langkah | ~1-5 detik | 5-30 detik |
| Token | ~100-500 / halaman | ribuan token gambar |
| Login | pakai browser **sudah login** | sering harus re-login |
| Anti-bot | fingerprint asli, Turnstile sering lolos sendiri | gampang ke-flag |

Playwright: script manual per situs, agent gak bisa ambil keputusan dinamis.

## Komponen

| File | Fungsi |
|---|---|
| `cloak.py` | Engine CDP: tab management, AX tree reading, network layer |
| `server.py` | **MCP server (stdio) — 26 tools** |
| `bin/cb` | CLI text-first buat manusia + agent shell |
| `bin/cbd` | Daemon unix-socket — 1 koneksi CDP permanen, ~0.02s per command |
| `auth.py` | OAuth2/MSAL token refresh (Gmail, Microsoft To Do) |
| `gmail_reader.py` / `todo_reader.py` | API reader, tanpa browser |
| `vault.py` | Vault kredensial + cookie (XOR obfuscation, lihat docs) |
| `auto_auth.py` | Deteksi form login → eskalasi kredensial → **fill tanpa auto-submit** |
| `session_manager.py` | Save/restore cookie via CDP — login sekali |
| `flow.py` | Contoh multi-step flow di 1 process (demo agent loop) |
| `tests/` | Smoke test tanpa browser |

## Quick start

```bash
git clone https://github.com/DaffaHeroik/cloak-use.git
cd cloak-use
pip install -r requirements.txt          # cuma websocket-client
python3 setup_check.py                  # cek: browser CDP :9222 hidup?
bash scripts/install.sh                  # (opsional) symlink cb + cbd ke /usr/local/bin
```

Butuh: 1 browser dengan `--remote-debugging-port=9222` di mesin yang sama.

MCP config (OpenCode / Claude / Cursor / Hermes):

```json
{
  "mcp": {
    "cloak-use": {
      "type": "local",
      "command": ["/path/to/cloak-use/server.py", "serve"]
    }
  }
}
```

Debug tanpa MCP:

```bash
python3 server.py call browser_status '{}'
python3 server.py call read_page '{}'
cb open https://example.com        # CLI
```

## Tools MCP (26)

| Tool | Kegunaan |
|---|---|
| `browser_status` | status browser + daftar tab, jalankan pertama |
| `list_tabs` / `open_tab` / `attach_tab` / `close_tab` | manajemen tab |
| `goto` | navigate tab aktif |
| `goto_fast` | navigate + baca halaman dalam 1 putaran (34% lebih cepat) |
| `read_page` | **baca halaman sebagai teks** (`include`: interactive/text/all) |
| `click_text` | klik element berdasarkan teks, tanpa selector CSS |
| `fill` / `select_option` / `upload_file` / `press_key` | input primitives (React-friendly) |
| `wait_for_text` | tunggu teks muncul/hilang — poll DOM 300ms |
| `scroll` / `eval` | scroll, JS arbitrary (power user) |
| `screenshot` | fallback canvas/chart/map only |
| `api_snapshot` | **scraping killer: semua response body API (JSON mentah)** |
| `watch_response` | tunggu 1 endpoint spesifik, ambil body-nya |
| `block_junk` | block image/font/css/analytics |
| `session_status` / `session_save` / `session_restore` | cookie vault — login sekali |
| `gmail_inbox` / `gmail_search` | Gmail API tanpa browser |
| `todo_summary` | Microsoft To Do via Graph API |

### Network layer — keunggulan utama untuk scraping

SPA mengambil data dari API JSON. Daripada render + parse DOM, ambil
response body-nya langsung — zero DOM parsing:

```
api_snapshot  →  /api/user/me, /api/user/dashboard, /api/notifications
                 JSON terstruktur, 7 detik, ~1.5K token
read_page     →  teks UI, 3.1 detik, ~150 token (untuk eksplorasi)
```

## Auth layer

Prinsip: **agent tidak pernah ngetik kredensial owner.**

1. `vault.py` — simpan kredensial + cookie per domain. Setelah login pertama,
   `session_restore` bikin 7 hari tanpa login ulang.
2. `auto_auth.py` — deteksi form login yang nyata (email/password/OTP/captcha),
   eskalasi via credential provider:
   - `CLOAK_CREDENTIALS_CMD` (env) — command custom, return JSON
     `{field: value}`. Escape hatch untuk PWA/secret manager/layanan lain.
   - CLI `vault-ask` (kalau ada di PATH) — form nembak HP owner.
   Hasilnya **di-fill, tidak di-submit**. Submit tetap keputusan sadar
   (`click_text`/`eval`), owner yang kontrol.
3. `auth.py` + `gmail_reader.py` + `todo_reader.py` — OAuth2 (Google) &
   MSAL (Microsoft) token refresh otomatis, API tanpa browser.

Setup token (opsional):

```bash
mkdir -p ~/.cloak-use
# Google: OAuth2 client + refresh_token → google_token.json
# Microsoft: MSAL cache → msal_token_cache.json
# Override path: env GOOGLE_TOKEN_PATH / MSAL_TOKEN_PATH
```

## Performance (ukur)

| Operasi | Waktu |
|---|---|
| Attach + baca tab existing | **354ms** |
| `js()` evaluate | **51ms** |
| Gmail flow (10 email via API) | **0.39s** |
| `cb` via daemon cbd | **~0.02s** per command |
| Buka tab baru + SPA load | 4-8s |
| Full agent loop (read→click→verify) | **9.3s, ~170 token** |

## Config

| Env | Default | Kegunaan |
|---|---|---|
| `CLOAK_HOST` / `CLOAK_PORT` | `127.0.0.1` / `9222` | CDP target |
| `CLOAK_USE_HOME` | `~/.cloak-use` | vault + cbd log |
| `CLOAK_VAULT_KEY` | built-in | XOR key vault (override) |
| `GOOGLE_TOKEN_PATH` | `~/.cloak-use/google_token.json` | token Google |
| `MSAL_TOKEN_PATH` | `~/.cloak-use/msal_token_cache.json` | cache MSAL |
| `CLOAK_CREDENTIALS_CMD` | — | credential provider custom |
| `CB_CDP` / `CB_PROFILE` | `http://127.0.0.1:9222` / `~/.chrome-novnc` | cb |

## Peringatan

Browser target punya session login asli. `eval` bisa menjalankan JS apa pun
di domain yang ter-attach. Jangan arahkan ke situs yang belum dipercaya.
`vault.py` pakai XOR obfuscation (bukan enkripsi kriptografis) — jangan
simpan kredensial kritis di situ, pakai secret manager.

## Contributing

Bugs, feature request, dan koreksi di [issues](../../issues).
PR: fork → branch → `python3 tests/test_smoke.py` (harus semua PASS) → PR.
Detail: [CONTRIBUTING.md](CONTRIBUTING.md).

## Lisensi

**MIT** — bebas dipakai, dimodifikasi, didistribusikan, bahkan untuk produk
komersial. Syarat: copyright notice tetap ada.
