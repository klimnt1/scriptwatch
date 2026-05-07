#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="/opt/scriptwatch-agent"

step() { echo -e "${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
die()  { echo -e "${RED}✗ Error: $1${NC}" >&2; exit 1; }

if [ "$EUID" -ne 0 ]; then
    die "Please run as root: sudo bash update.sh"
fi

[ -d "$INSTALL_DIR" ] || die "Agent not installed at $INSTALL_DIR. Run install.sh first."

SCRIPT_DIR="$(dirname "$0")"
NEW_AGENT="$SCRIPT_DIR/agent.py"

[ -f "$NEW_AGENT" ] || die "agent.py not found next to update.sh"

step "Updating agent.py"
cp "$NEW_AGENT" "$INSTALL_DIR/agent.py"
ok "agent.py updated"

step "Restarting service"
systemctl restart scriptwatch-agent
sleep 2

if systemctl is-active --quiet scriptwatch-agent; then
    ok "Service is running"
else
    echo -e "${RED}✗ Service failed to restart. Check: journalctl -u scriptwatch-agent -n 20${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}Update complete!${NC}"
