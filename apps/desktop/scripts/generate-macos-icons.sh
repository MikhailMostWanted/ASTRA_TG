#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
DESKTOP_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
SOURCE_SVG="$DESKTOP_DIR/assets/astra-icon.svg"
ICONS_DIR="$DESKTOP_DIR/src-tauri/icons"
ICONSET_DIR="$ICONS_DIR/Astra.iconset"
MASTER_PNG="$ICONS_DIR/icon-master-1024.png"

if [[ ! -f "$SOURCE_SVG" ]]; then
  echo "Icon source not found: $SOURCE_SVG" >&2
  exit 1
fi

rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

sips -s format png -z 1024 1024 "$SOURCE_SVG" --out "$MASTER_PNG" >/dev/null

for spec in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"
do
  size=${spec%% *}
  filename=${spec#* }
  sips -z "$size" "$size" "$MASTER_PNG" --out "$ICONSET_DIR/$filename" >/dev/null
done

iconutil -c icns "$ICONSET_DIR" -o "$ICONS_DIR/icon.icns"

sips -z 512 512 "$MASTER_PNG" --out "$ICONS_DIR/icon.png" >/dev/null
sips -z 256 256 "$MASTER_PNG" --out "$ICONS_DIR/128x128@2x.png" >/dev/null
sips -z 128 128 "$MASTER_PNG" --out "$ICONS_DIR/128x128.png" >/dev/null
sips -z 32 32 "$MASTER_PNG" --out "$ICONS_DIR/32x32.png" >/dev/null
sips -z 30 30 "$MASTER_PNG" --out "$ICONS_DIR/Square30x30Logo.png" >/dev/null
sips -z 44 44 "$MASTER_PNG" --out "$ICONS_DIR/Square44x44Logo.png" >/dev/null
sips -z 50 50 "$MASTER_PNG" --out "$ICONS_DIR/StoreLogo.png" >/dev/null
sips -z 71 71 "$MASTER_PNG" --out "$ICONS_DIR/Square71x71Logo.png" >/dev/null
sips -z 89 89 "$MASTER_PNG" --out "$ICONS_DIR/Square89x89Logo.png" >/dev/null
sips -z 107 107 "$MASTER_PNG" --out "$ICONS_DIR/Square107x107Logo.png" >/dev/null
sips -z 142 142 "$MASTER_PNG" --out "$ICONS_DIR/Square142x142Logo.png" >/dev/null
sips -z 150 150 "$MASTER_PNG" --out "$ICONS_DIR/Square150x150Logo.png" >/dev/null
sips -z 284 284 "$MASTER_PNG" --out "$ICONS_DIR/Square284x284Logo.png" >/dev/null
sips -z 310 310 "$MASTER_PNG" --out "$ICONS_DIR/Square310x310Logo.png" >/dev/null

rm -rf "$ICONSET_DIR"
rm -f "$MASTER_PNG"
echo "Updated icons in $ICONS_DIR"
