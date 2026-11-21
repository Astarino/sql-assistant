#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

uv sync --frozen
swift build --package-path macos --product SQLAssistant
bin_dir=$(swift build --package-path macos --show-bin-path)
app_dir="$project_dir/macos/.build/SQL Assistant.app"
mkdir -p "$app_dir/Contents/MacOS"
cp "$bin_dir/SQLAssistant" "$app_dir/Contents/MacOS/SQLAssistant.new"
mv -f "$app_dir/Contents/MacOS/SQLAssistant.new" "$app_dir/Contents/MacOS/SQLAssistant"
cp macos/Info.plist "$app_dir/Contents/Info.plist"
codesign --force --sign - "$app_dir"
exec "$app_dir/Contents/MacOS/SQLAssistant"
