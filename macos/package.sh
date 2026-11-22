#!/bin/sh
set -eu

project_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

output_dir="$project_dir/macos/.build/distribution"
mkdir -p "$output_dir"
build_dir=$(mktemp -d "$output_dir/build.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT

uv run --frozen --with pyinstaller==6.22.3 python -m PyInstaller \
    --log-level WARN --onefile --name SQLAssistantBackend \
    --hidden-import psycopg_binary.pq --hidden-import psycopg_binary._psycopg \
    --hidden-import sqlglot.dialects.postgres \
    --distpath "$build_dir/python" --workpath "$build_dir/work" --specpath "$build_dir" \
    desktop.py

swift build --package-path macos -c release --product SQLAssistant
bin_dir=$(swift build --package-path macos -c release --show-bin-path)
app_dir="$build_dir/SQL Assistant.app"
mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Helpers"
cp "$bin_dir/SQLAssistant" "$app_dir/Contents/MacOS/SQLAssistant"
cp macos/Info.plist "$app_dir/Contents/Info.plist"
cp "$build_dir/python/SQLAssistantBackend" "$app_dir/Contents/Helpers/SQLAssistantBackend"
codesign --force --sign - "$app_dir"
codesign --verify --deep --strict "$app_dir"

archive="SQL-Assistant-macos-$(uname -m).zip"
ditto -c -k --keepParent "$app_dir" "$build_dir/$archive"
mv -f "$build_dir/$archive" "$output_dir/$archive"
printf '%s\n' "$output_dir/$archive"
