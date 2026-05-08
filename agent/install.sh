#!/bin/bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="/opt/scriptwatch-agent"
ENV_FILE="/etc/scriptwatch.env"
SERVICE_FILE="/etc/systemd/system/scriptwatch-agent.service"
AGENT_URL="https://raw.githubusercontent.com/klimnt1/scriptwatch/main/agent/agent.py"

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║     ScriptWatch Agent Installer      ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${NC}"
    echo ""
}

step() {
    echo -e "${CYAN}▶ $1${NC}"
}

ok() {
    echo -e "${GREEN}✓ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

die() {
    echo -e "${RED}✗ Error: $1${NC}" >&2
    exit 1
}

prompt() {
    local var_name="$1"
    local label="$2"
    local default="$3"
    local secret="$4"

    if [ -n "$default" ]; then
        echo -ne "${BOLD}${label}${NC} [${default}]: "
    else
        echo -ne "${BOLD}${label}${NC}: "
    fi

    if [ "$secret" = "true" ]; then
        read -rs value
        echo ""
    else
        read -r value
    fi

    if [ -z "$value" ] && [ -n "$default" ]; then
        value="$default"
    fi

    eval "$var_name=\"\$value\""
}

# ── Preflight ──────────────────────────────────────────────────────────────────

print_header

if [ "$EUID" -ne 0 ]; then
    die "Please run as root: sudo bash install.sh"
fi

command -v python3 >/dev/null 2>&1 || die "python3 is not installed. Run: apt install python3"
command -v systemctl >/dev/null 2>&1 || die "systemd is required but not available on this system."

if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y python3-venv -qq || die "Failed to install python3-venv"
fi

ok "Preflight checks passed"
echo ""

# ── Gather config ─────────────────────────────────────────────────────────────

echo -e "${BOLD}Configure the agent:${NC}"
echo ""

prompt API_URL      "ScriptWatch API URL"   "http://192.168.20.244:8095"
while [ -z "$API_URL" ]; do
    warn "API URL is required."
    prompt API_URL  "ScriptWatch API URL"   "http://192.168.20.244:8095"
done

prompt SERVER_NAME  "Server name (e.g. dns-alpha)" ""
while [ -z "$SERVER_NAME" ]; do
    warn "Server name is required."
    prompt SERVER_NAME "Server name (e.g. dns-alpha)" ""
done

prompt AGENT_TOKEN  "Agent token" "" "true"
while [ -z "$AGENT_TOKEN" ]; do
    warn "Agent token is required."
    prompt AGENT_TOKEN "Agent token" "" "true"
done

prompt POLL_INTERVAL      "Poll interval (seconds)"      "10"
prompt HEARTBEAT_INTERVAL "Heartbeat interval (seconds)" "30"

echo ""
echo -e "${BOLD}Summary:${NC}"
echo "  API URL:            $API_URL"
echo "  Server name:        $SERVER_NAME"
echo "  Agent token:        ****"
echo "  Poll interval:      ${POLL_INTERVAL}s"
echo "  Heartbeat interval: ${HEARTBEAT_INTERVAL}s"
echo ""
echo -ne "Proceed with installation? [Y/n]: "
read -r confirm
if [[ "$confirm" =~ ^[Nn] ]]; then
    echo "Aborted."
    exit 0
fi

echo ""

# ── Install ────────────────────────────────────────────────────────────────────

step "Creating install directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
ok "Directory ready"

step "Downloading agent.py"
if curl -fsSL "$AGENT_URL" -o "$INSTALL_DIR/agent.py" 2>/dev/null; then
    ok "Downloaded from GitHub"
elif [ -f "$(dirname "$0")/agent.py" ]; then
    cp "$(dirname "$0")/agent.py" "$INSTALL_DIR/agent.py"
    ok "Copied from local installer directory"
else
    die "Could not download agent.py and no local copy found.\nRun from the same directory as agent.py, or ensure $AGENT_URL is reachable."
fi

step "Creating Python virtualenv"
python3 -m venv "$INSTALL_DIR/venv"
ok "Virtualenv created"

step "Installing Python dependencies"
"$INSTALL_DIR/venv/bin/pip" install requests==2.31.0 -q
ok "Dependencies installed"

step "Writing environment file: $ENV_FILE"
cat > "$ENV_FILE" <<EOF
SCRIPTWATCH_API_URL=${API_URL}
SCRIPTWATCH_SERVER_NAME=${SERVER_NAME}
SCRIPTWATCH_AGENT_TOKEN=${AGENT_TOKEN}
POLL_INTERVAL=${POLL_INTERVAL}
HEARTBEAT_INTERVAL=${HEARTBEAT_INTERVAL}
EOF
chmod 600 "$ENV_FILE"
ok "Environment file written (mode 600)"

step "Installing systemd service"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=ScriptWatch Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/scriptwatch-agent
EnvironmentFile=/etc/scriptwatch.env
ExecStart=/opt/scriptwatch-agent/venv/bin/python3 /opt/scriptwatch-agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
ok "Service file written"

step "Enabling and starting service"
systemctl daemon-reload
systemctl enable scriptwatch-agent --quiet
systemctl restart scriptwatch-agent

# Give it a moment to start
sleep 2

if systemctl is-active --quiet scriptwatch-agent; then
    ok "Service is running"
else
    warn "Service may have failed to start. Check logs:"
    echo "  journalctl -u scriptwatch-agent -n 30"
    exit 1
fi

# ── Done ───────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}Installation complete!${NC}"
echo ""
echo "Useful commands:"
echo "  Status:   systemctl status scriptwatch-agent"
echo "  Logs:     journalctl -u scriptwatch-agent -f"
echo "  Stop:     systemctl stop scriptwatch-agent"
echo "  Restart:  systemctl restart scriptwatch-agent"
echo "  Config:   $ENV_FILE"
echo ""
