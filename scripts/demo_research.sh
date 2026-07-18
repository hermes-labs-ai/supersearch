#!/usr/bin/env bash
# demo_research.sh — canonical research demo for supersearch v0.9+.
# Runs one topic through the full pipeline, tails the analysis summary,
# prints corpus stats. Reality gates fire automatically via the CLI.
#
# Usage:
#   bash scripts/demo_research.sh                        # default topic
#   bash scripts/demo_research.sh "your topic here"      # custom topic

set -euo pipefail

TOPIC="${1:-EU AI Act compliance vendors}"
OUT="/tmp/ssr-demo-$(date +%s)"

echo "🔎 Research topic: $TOPIC"
echo "📁 Output dir:     $OUT"
echo

python3 -m supersearch research "$TOPIC" --depth=1 --max-pages=30 --out="$OUT"

echo
echo "─── analysis.md (first 80 lines) ───────────────────────────────"
head -n 80 "$OUT/analysis.md"
echo "─────────────────────────────────────────────────────────────────"
echo

PAGES=$(ls "$OUT/pages" 2>/dev/null | wc -l | tr -d ' ')
BYTES=$(du -sh "$OUT" 2>/dev/null | awk '{print $1}')
echo "📊 Corpus stats:"
echo "   pages: $PAGES"
echo "   bytes: $BYTES"
echo "   out:   $OUT"
