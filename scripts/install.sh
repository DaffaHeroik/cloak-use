#!/usr/bin/env bash
# install.sh — pasang cb + cbd dari repo ini ke /usr/local/bin.
set -euo pipefail
cd "$(dirname "$0")/.."

for f in bin/cb bin/cbd; do
  [[ -f "$f" ]] || { echo "missing $f" >&2; exit 1; }
  chmod +x "$f"
  ln -sf "$PWD/$f" /usr/local/bin/"$(basename "$f")"
  echo "linked /usr/local/bin/$(basename "$f") -> $PWD/$f"
done

mkdir -p ~/.cloak-use
python3 setup_check.py || echo "[warn] setup_check ada item [MISS] — cek manual"

# restart cbd daemon (kalau jalan di instance lama)
if [[ -S /run/cbd.sock || -S /tmp/cbd.sock ]]; then
  pkill -f "bin/cbd" 2>/dev/null || pkill -f "cbd$" 2>/dev/null || true
  sleep 0.5
fi
echo "siap. cb/cbd live dari repo — ubah kode di repo, langsung nempel."
