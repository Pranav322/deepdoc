#!/usr/bin/env bash
# Build and export in a throwaway copy of the project.
#
# `next build` regenerates .source (fumadocs-mdx's generated collection). A
# running `next dev` hot-reloads it and then dies with
# "TypeError: a[d] is not a function", because the production-mode module does
# not match the dev runtime. distDir does not help — .source is the shared
# state. Copying the project sidesteps all of it.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TMP="${TMPDIR:-/tmp}/deepdoc-docs-verify"

rm -rf "$TMP"
mkdir -p "$TMP"
rsync -a --exclude node_modules --exclude .next --exclude .next-build \
        --exclude .source --exclude out "$SRC/" "$TMP/"
ln -s "$SRC/node_modules" "$TMP/node_modules"

( cd "$TMP" && EXPORT_DIR=.next-build NEXT_DIST_DIR=.next-build npx next build >/dev/null 2>&1 )
echo "$TMP/.next-build"
