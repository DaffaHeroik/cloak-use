# Contributing

Terima kasih mau bantu cloak-use. Repo ini open-source (MIT) — kontribusi
dari siapa saja disambut.

## Menemukan bug / meminta fitur

- Pakai [Issues](../../issues) — 1 issue = 1 masalah.
- Sertakan: OS, Python version, output `python3 setup_check.py`,
  dan cara replikasi (URL + langkah, atau snippet `cb`/MCP call).
- Untuk bug yang melibatkan halaman: `python3 server.py call read_page '{}'`
  + `browser_status` biasanya sudah cukup untuk diagnosa.

## Pull request

1. Fork → branch baru dari `main`.
2. Konvensi commit: `feat:` / `fix:` / `perf:` / `docs:` / `test:` —
   singkat, lowercase, fokus ke "mengapa".
3. **Semua PR harus `python3 tests/test_smoke.py` lulus** (6 test, tanpa
   browser — aman jalan di CI/lokal).
4. PR kecil lebih gampang review. 1 concern = 1 PR.

## Konvensi kode

- Python stdlib dulu, tanpa dependency baru kecuali benar-benar perlu
  (core saat ini cuma `websocket-client`).
- Gak ada type hint wajib, tapi docstring singkat + return value
  konsisten pakai dict JSON-serializable (tool MCP return dict).
- Bahasa: code comments boleh campur ID/EN seperti gaya yang ada;
  pesan error user-facing tetap jelas.
- Jangan nambahin screenshot-driven flow — text-first adalah inti project ini.

## Struktur yang disentuh

| File | Catatan |
|---|---|
| `cloak.py` | engine CDP — hati-hati, semua perf optim di sini |
| `server.py` | MCP tools — nambah tool = update TOOLS + dispatch + README tabel |
| `bin/cb` `bin/cbd` | CLI/daemon — ubah lalu `bash scripts/install.sh` |
| `tests/test_smoke.py` | tambahin case kalau tambahin fitur |

## Lisensi kontribusi

Dengan submit kode, lo setuju kode lo berada di bawah license MIT repo ini.
