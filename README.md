# Web automation untuk AI agent, text-first.

**Browser Use untuk browser** — tapi 10-100x lebih cepat dan 99% lebih murah.

Browser Use lambat karena **screenshot-driven**: setiap langkah butuh round trip
ke vision model dengan token gambar. cloak-use baca halaman sebagai **teks**
lewat Accessibility tree ( struktur DOM yang sama yang dipake screen reader ),
lalu kasih ke agent sebagai JSON. 90% kasus web automation gak butuh screenshot.

Bukan headless — ini ngopersiapkan **browser asli yang sudah login** (
Groq, GitHub, Telegram Web, apa saja yang session-nya tersimpan ). Artinya:

- Tidak perlu re-login, cookie real, fingerprint real.
- **Turnstile/anti-bot sering solve sendiri** karena browser-nya klien asli.
- Login flow, OTP, password manager — semua handled by browser manusia.

## Performance ( measured, GitHub + Groq console + Ryfinite dashboard )

| Operasi | cloak-use | Browser Use ( est ) |
|---|---|---|
| Baca 1 halaman ( 94 lines ) | **3.1s, 172 tok** | 15-30s, 5-10K tok |
| Full agent loop ( read→click→verify ) | **9.3s, ~170 tok** | 45-120s, 5-20K tok |
| Klik tombol by text | 2-7s | 5-15s + vision |
| Deteksi modal + captcha widget | 1 call AX tree | 1-3 screenshot |
| Buka dashboard ( session ada ) | **5.2s** | 30-60s |
| Navigasi + baca ( goto_fast ) | **7.7s** ( 34% faster dari goto+read ) | 45-90s |

**90% lebih cepat, 99% lebih murah.**

Kenapa cepat: zero screenshot, zero vision round trip. AX tree itu tree
traversal lokal di browser; text result langsung masuk LLM context sebagai
JSON kecil. Screenshot dipakai **hanya jika explicit** — canvas, chart, map.

## Install

```bash
git clone https://github.com/DaffaHeroik/cloak-use.git
cd cloak-use
pip install websocket-client
python3 setup_check.py
python3 server.py serve
```

Butuh: browser Chrome/Chromium dengan `--remote-debugging-port=9222` (
`Cloak` / anti-detect browser ) di mesin yang sama.

## Tools ( 11 )

| Tool | Kegunaan |
|---|---|
| `browser_status` | status browser + daftar tab, jalankan pertama |
| `list_tabs` | daftar tab ( url, title ) |
| `open_tab` | buka URL di tab baru |
| `attach_tab` | attach ke tab yang sudah terbuka |
| `goto` | navigate tab aktif |
| `goto_fast` | navigate + baca halaman dalam 1 putaran ( 34% faster ) |
| `read_page` | **baca halaman sebagai teks** ( `include`: interactive/text/all ) |
| `click_text` | klik element berdasarkan teks ( "Sign in", "Save" ) |
| `fill` | isi input ( React-friendly ) |
| `scroll` | scroll down/up |
| `eval` | jalankan JavaScript ( power user ) |
| `screenshot` | fallback untuk canvas/chart/map only |
| `api_snapshot` | **scoping killer: ambil semua response body API ( JSON mentah )** |
| `watch_response` | tunggu endpoint spesifik, ambil body JSON-nya |
| `block_junk` | block image/font/css/analytics, ringankan load |

## Network layer: keunggulan utama untuk scraping

SPA web3 / dashboard biasanya mengambil data dari API JSON. Daripada
me-render halaman dan mem-parsing teks-nya, **ambi response body-nya secara
langsung** — zero DOM parsing.

Diukur di ryfinite.com/app:

```
api_snapshot  → 6 API calls, JSON terstruktur:
  /api/user/me        → {user: {id, email, image, ...}}
  /api/user/dashboard → tokens: ETH=0, RFN=0, USDT=0
  /api/notifications  → {notifications: []}
  /api/mine           → 3108 bytes
```

| Metode | Waktu | Token | Datanya |
|---|---|---|---|
| `api_snapshot` | 7.0s | ~1569 | **JSON terstruktur ( akurat ) |
| `read_page` | 3.1s | ~151 | Teks UI ( harus diparse lagi ) |

`read_page` untuk eksplorasi ( token sangat hemat ), `api_snapshot` saat
butuh data akurat untuk scraping. Keduanya berbasis teks, keduanya 10-100x
lebih murah dari Browser Use.

`block_junk` memblokir 15+ resource sia-sia ( gambar/font/css/analytics )
agar halaman lebih ringan — untuk situs yang bandwidth/stat-nya berat.

## Contoh alur agent

```
1. browser_status      -> "18 tabs, Groq login, GitHub login"
2. attach_tab(groq)    -> attach ke console.groq.com
3. read_page           -> 94 lines: "button: Create API Key", "textbox: Display Name"
4. click_text          -> klik "Create API Key"
5. read_page           -> modal terbuka, ada textbox Display Name + Iframe Turnstile
6. fill(selector, name)-> isi form
7. click_text          -> klik Submit
8. read_page           -> verify halaman berubah / API key muncul
```

Setiap langkah ~3 detik, semuanya teks. Browser Use menit-menitan.

## Config

| Env | Default | Kegunaan |
|---|---|---|
| `CLOAK_HOST` | `127.0.0.1` | host browser CDP |
| `CLOAK_PORT` | `9222` | port CDP |

MCP config ( OpenCode / Hermes / Claude / Cursor ):

```json
{
  "mcp": {
    "cloak-use": {
      "type": "local",
      "command": ["/path/to/cloak-use/server.py", "serve"],
      "enabled": true
    }
  }
}
```

## Kenapa tidak Browser Use / Playwright ?

- **Playwright** butuh script manual untuk setiap situs; tidak bisa dipanggil
  agent secara dinamis.
- **Browser Use** screenshot-driven: lambat + mahal.
- ** cloak-use**: text-first, memanfaatkan browser yang sudah login,
  Turnstile sering lewat sendiri, dan jika perlu screenshot tetap bisa.

## Warning

Browser ini punya session login asli. `eval` bisa menjalankan JS apa pun di
domain tersebut. Jangan pointed ke situs yang belum dipercaya.

## License

MIT
