#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Servers to update ─────────────────────────────────────────────────────────
# Format: "user@host"
SERVERS=(
    "debian@dns-alpha"
    "debian@dns-beta"
    "debian@debian-vm"
)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_PY="$SCRIPT_DIR/agent.py"
UPDATE_SH="$SCRIPT_DIR/update.sh"

ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
die()  { echo -e "${RED}✗ $1${NC}"; }
step() { echo -e "${CYAN}▶ $1${NC}"; }

[ -f "$AGENT_PY" ]  || { echo -e "${RED}agent.py not found${NC}"; exit 1; }
[ -f "$UPDATE_SH" ] || { echo -e "${RED}update.sh not found${NC}"; exit 1; }

echo ""
echo -e "${CYAN}${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}║    ScriptWatch Agent Deployment      ║${NC}"
echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""
echo "Servers: ${SERVERS[*]}"
echo ""

PASS=0
FAIL=0
FAILED_SERVERS=()

for SERVER in "${SERVERS[@]}"; do
    echo -e "${BOLD}── $SERVER ──────────────────────────────${NC}"

    step "Copying files"
    if ! ssh "$SERVER" "mkdir -p /tmp/sw-update"; then
        die "SSH failed — skipping $SERVER"
        FAIL=$((FAIL + 1))
        FAILED_SERVERS+=("$SERVER")
        echo ""
        continue
    fi
    scp -q "$AGENT_PY" "$UPDATE_SH" "$SERVER:/tmp/sw-update/"

    step "Running update"
    if ssh "$SERVER" "sudo bash /tmp/sw-update/update.sh && rm -rf /tmp/sw-update"; then
        ok "$SERVER updated"
        PASS=$((PASS + 1))
    else
        die "$SERVER update failed"
        FAIL=$((FAIL + 1))
        FAILED_SERVERS+=("$SERVER")
    fi
    echo ""
done

echo -e "${BOLD}── Summary ──────────────────────────────${NC}"
echo -e "${GREEN}✓ $PASS succeeded${NC}"
if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}✗ $FAIL failed: ${FAILED_SERVERS[*]}${NC}"
fi
echo ""
