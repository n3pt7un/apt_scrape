#!/usr/bin/env zsh

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$SCRIPT_DIR/.env" ]] && set -a && source "$SCRIPT_DIR/.env" && set +a
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
OUTPUT_DIR="results/latest/batch_casa"

# Search parameters (mirrors scrape_multiple_areas.sh)
CITY="milano"
OPERATION="affitto"
PROPERTY_TYPES="appartamenti,attici"
MIN_PRICE=700
MAX_PRICE=1000
MIN_SQM=55
MIN_ROOMS=2
SORT="piu-recenti"
SOURCE="casa"
START_PAGE=1
END_PAGE=10
DETAIL_CONCURRENCY=5   # parallel detail-page fetches per batch
VPN_ROTATE_BATCHES=3   # rotate VPN every N batches

# List of areas to scrape (same as main multi-area script; edit as needed)
AREAS=(
  "bicocca"
  "niguarda"       # maps to bicocca-ca-granda-parco-nord zone on casa.it
  "precotto"       # maps to gorla-greco-precotto zone
  "citta-studi"    # maps to citta-studi-corsica-susa zone
  "lambrate"
  "turro"          # maps to gorla-greco-precotto zone (same as precotto)
  "greco-segnano"  # maps to gorla-greco-precotto zone (same as precotto/turro)
  "crescenzago"    # maps to adriano-crescenzago-parco-lambro-cimiano zone
  "centrale"       # maps to centrale-repubblica zone
)

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Log file (full output goes here; terminal shows progress bar only)
LOG_FILE="${OUTPUT_DIR}/scrape_log_$(date +%Y%m%d_%H%M%S).txt"

TOTAL=${#AREAS[@]}
SUCCESS_COUNT=0
FAIL_COUNT=0
CURRENT=0

# — progress bar helpers —————————————————————————————————————————
# Draw a single progress bar line (overwrites in-place)
# Usage: draw_progress <done> <total> <label> <status_suffix>
draw_progress() {
  local done=$1 total=$2 label=$3 suffix=$4
  local bar_width=30
  local filled=$(( done * bar_width / total ))
  local empty=$(( bar_width - filled ))
  local bar="$(printf '%0.s█' $(seq 1 $filled))$(printf '%0.s░' $(seq 1 $empty))"
  local pct=$(( done * 100 / total ))
  printf "\r  [%s] %3d%%  %-20s  %s" "$bar" "$pct" "$label" "$suffix"
}

# Move cursor up N lines (to redraw area rows already printed)
cursor_up() { printf "\033[%dA" "$1"; }
# ————————————————————————————————————————————————————————————————

# Print header (goes to terminal AND log)
{
  echo "=== rent-fetch: multi-area scrape (casa.it) ==="
  echo "City         : $CITY"
  echo "Property     : $PROPERTY_TYPES"
  echo "Price / size : max €${MAX_PRICE}  min ${MIN_SQM}m²  min ${MIN_ROOMS} rooms"
  echo "Pages        : ${START_PAGE}–${END_PAGE}    Sort: $SORT"
  echo "Concurrency  : ${DETAIL_CONCURRENCY} parallel fetches / rotate VPN every ${VPN_ROTATE_BATCHES} batches"
  printf "Areas        : %d\n" "$TOTAL"
  echo "Started      : $(date '+%Y-%m-%d %H:%M:%S')"
  echo ""
} | tee "$LOG_FILE"

# Pre-print one placeholder line per area so we can redraw them in-place
for AREA in "${AREAS[@]}"; do
  printf "  [%s] %3d%%  %-20s  %s\n" \
    "$(printf '%0.s░' $(seq 1 30))" 0 "$AREA" "waiting..."
done

# Move cursor back up to the first area line
cursor_up $TOTAL

# Loop through each area
IDX=0
for AREA in "${AREAS[@]}"; do
  IDX=$(( IDX + 1 ))
  OUTPUT_FILE="${OUTPUT_DIR}/${CITY}_${AREA}_${PROPERTY_TYPES//,/_}_pages${START_PAGE}_${END_PAGE}_recent.json"

  # Show "running" state for this row, leave others intact
  draw_progress $IDX $TOTAL "$AREA" "running..."

  # Run scraper — all output goes to log only
  {
    echo ""
    echo "--- [$IDX/$TOTAL] $AREA  $(date '+%H:%M:%S') ---"
  } >> "$LOG_FILE"

  "$PYTHON_BIN" -m apt_scrape.cli search \
    --city "$CITY" \
    --area "$AREA" \
    --operation "$OPERATION" \
    --property-type "$PROPERTY_TYPES" \
    --min-price "$MIN_PRICE" \
    --max-price "$MAX_PRICE" \
    --min-sqm "$MIN_SQM" \
    --min-rooms "$MIN_ROOMS" \
    --sort "$SORT" \
    --source "$SOURCE" \
    --start-page "$START_PAGE" \
    --end-page "$END_PAGE" \
    --detail-concurrency "$DETAIL_CONCURRENCY" \
    --vpn-rotate-batches "$VPN_ROTATE_BATCHES" \
    -o "$OUTPUT_FILE" >> "$LOG_FILE" 2>&1
  EXIT_CODE=$?

  if [ $EXIT_CODE -eq 0 ]; then
    LABEL="✓ done"
    # Count listings saved (if jq available, else skip)
    if command -v jq &>/dev/null && [[ -f "$OUTPUT_FILE" ]]; then
      COUNT=$(jq 'if type=="array" then length else (.listings // [] | length) end' "$OUTPUT_FILE" 2>/dev/null || echo "?")
      LABEL="✓ ${COUNT} listings"
    fi
    draw_progress $IDX $TOTAL "$AREA" "$LABEL"
    echo "  ✓ $AREA → $OUTPUT_FILE  ($LABEL)" >> "$LOG_FILE"
    (( SUCCESS_COUNT++ ))
  else
    draw_progress $IDX $TOTAL "$AREA" "✗ failed (see log)"
    echo "  ✗ $AREA failed with exit code $EXIT_CODE" >> "$LOG_FILE"
    (( FAIL_COUNT++ ))
  fi

  # Move to next line so the next iteration draws on its own row
  printf "\n"
done

# Summary
{
  echo ""
  echo "=== Completed at $(date '+%Y-%m-%d %H:%M:%S') ==="
  echo "Success : $SUCCESS_COUNT / $TOTAL"
  echo "Failed  : $FAIL_COUNT"
  echo "Log     : $LOG_FILE"
} | tee -a "$LOG_FILE"

