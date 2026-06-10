#!/usr/bin/env bash
# Regenerate architecture-light.svg and architecture-dark.svg from architecture.tex.
# Requires: latex, dvisvgm. Preview with: uv run mkdocs serve
set -euo pipefail
cd "$(dirname "$0")"

latex -interaction=nonstopmode architecture.tex
dvisvgm --no-fonts architecture.dvi -o architecture-light.svg

latex -interaction=nonstopmode '\def\darkmode{1}\input{architecture.tex}'
dvisvgm --no-fonts architecture.dvi -o architecture-dark.svg

rm -f architecture.aux architecture.dvi architecture.log
echo "Wrote architecture-light.svg and architecture-dark.svg"
