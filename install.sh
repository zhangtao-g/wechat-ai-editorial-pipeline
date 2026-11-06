#!/usr/bin/env bash
# Install the pipeline into ~/.hermes by symlinking code and templates.
# Existing regular files are backed up, never silently overwritten.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
STAMP="$(date +%Y%m%d%H%M%S)"

link() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    local bak="$dst.bak.$STAMP"
    cp -a "$dst" "$bak"
    echo "  backup  $dst -> $bak"
  fi
  ln -sfn "$src" "$dst"
  echo "  link    $dst"
}

echo "Repo:        $REPO"
echo "HERMES_HOME: $HERMES_HOME"
echo

mkdir -p \
  "$HERMES_HOME/scripts" \
  "$HERMES_HOME/templates" \
  "$HERMES_HOME/news" \
  "$HERMES_HOME/workspace/covers" \
  "$HERMES_HOME/workspace/drafts" \
  "$HERMES_HOME/workspace/history" \
  "$HERMES_HOME/workspace/source_articles"

echo "Linking scripts..."
for f in "$REPO"/scripts/*.py; do
  link "$f" "$HERMES_HOME/scripts/$(basename "$f")"
done

echo "Linking templates..."
for f in "$REPO"/templates/*; do
  link "$f" "$HERMES_HOME/templates/$(basename "$f")"
done

echo "Linking cover tools..."
link "$REPO/covers/make_cover.py" "$HERMES_HOME/workspace/covers/make_cover.py"
link "$REPO/scripts/render_hot_cover_html.py" "$HERMES_HOME/scripts/render_hot_cover_html.py"

echo "Seeding config (only if missing)..."
if [ ! -f "$HERMES_HOME/news/sources.json" ]; then
  cp "$REPO/config/sources.example.json" "$HERMES_HOME/news/sources.json"
  echo "  created $HERMES_HOME/news/sources.json"
fi
if [ ! -f "$HERMES_HOME/news/hot-sources.json" ]; then
  cp "$REPO/config/hot-sources.example.json" "$HERMES_HOME/news/hot-sources.json"
  echo "  created $HERMES_HOME/news/hot-sources.json"
fi
if [ ! -f "$HERMES_HOME/notification_config.json" ]; then
  cp "$REPO/config/notification.example.json" "$HERMES_HOME/notification_config.json"
  chmod 600 "$HERMES_HOME/notification_config.json"
  echo "  created $HERMES_HOME/notification_config.json (edit the webhook before use)"
fi

if [ "${1:-}" = "--with-deps" ]; then
  echo "Installing Python dependencies..."
  python3 -m pip install -r "$REPO/requirements.txt"
fi

cat <<EOF

Done.

Next steps:
  1. Edit $HERMES_HOME/news/sources.json  (set horizon_path)
  2. Set WECHAT_APPID / WECHAT_APPSECRET, or create
     $HERMES_HOME/wechat_credentials.json  with chmod 600
  3. Smoke test:
     python3 $REPO/scripts/render_article.py --input $REPO/examples/article.example.md \\
       --out /tmp/body.html --preview /tmp/preview.html --date 2026.11.06 --column AI热点
  4. Verify credentials:
     python3 $REPO/scripts/wechat_credentials.py
EOF
