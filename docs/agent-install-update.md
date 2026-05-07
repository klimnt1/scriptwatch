# ScriptWatch Agent — Install & Update Guide

The ScriptWatch agent is a lightweight Python process that runs on any server you want to monitor. It polls the central API every 10 seconds for pending jobs, executes them locally, and reports results back. It requires no inbound ports — only outbound HTTP to the ScriptWatch API.

This guide covers two installation methods:
- **Docker Compose** (recommended for servers already running Docker)
- **Systemd service** (bare-metal, no Docker required — works on any Debian machine)

---

## Prerequisites

- The server must have network access to the ScriptWatch API (`http://192.168.20.244:8095` or whichever host it runs on)
- You need the `AGENT_TOKEN` value from the ScriptWatch host's `.env` file

---

## Method A — Docker Compose (Recommended)

### Install

1. **SSH into the target server** (e.g. dns-alpha or dns-beta).

2. **Create a working directory:**
   ```bash
   mkdir -p /opt/scriptwatch-agent
   cd /opt/scriptwatch-agent
   ```

3. **Create the `docker-compose.yml`:**
   ```yaml
   services:
     scriptwatch-agent:
       image: gitea.plexusprime.net/adrianoropesa/scriptwatch-agent:latest
       container_name: ScriptWatch-Agent
       restart: unless-stopped
       environment:
         SCRIPTWATCH_API_URL: http://192.168.20.244:8095
         SCRIPTWATCH_SERVER_NAME: dns-alpha        # change to dns-beta on the other server
         SCRIPTWATCH_AGENT_TOKEN: your-agent-token-here
         POLL_INTERVAL: 10
         HEARTBEAT_INTERVAL: 30
   ```
   Replace `dns-alpha` with the exact server name registered in ScriptWatch, and fill in the real token.

4. **Pull and start:**
   ```bash
   docker compose up -d
   ```

5. **Verify it started:**
   ```bash
   docker logs ScriptWatch-Agent --tail 20
   ```
   You should see a line like:
   ```
   ScriptWatch agent v1.0.0 starting — server: dns-alpha
   Registered as 'dns-alpha' (hostname: ...)
   ```

### Update (Docker Compose method)

When a new agent image has been built and pushed to your container registry:

```bash
cd /opt/scriptwatch-agent
docker compose pull
docker compose up -d
```

That's it. The container restarts automatically with the new image.

---

## Method B — Systemd Service (No Docker)

Use this on any Debian machine that doesn't run Docker, including regular desktop/server Debian installs.

### Install

1. **SSH into the target server.**

2. **Install Python and pip:**
   ```bash
   apt update && apt install -y python3 python3-pip
   ```

3. **Create the agent directory and copy the agent file:**
   ```bash
   mkdir -p /opt/scriptwatch-agent
   ```
   Copy `agent.py` and `requirements.txt` from this repo's `agent/` folder to `/opt/scriptwatch-agent/` on the target server. One way:
   ```bash
   # Run from the ScriptWatch host (PlexusPrime), not the target server
   scp /mnt/appdata/scriptwatch/agent/agent.py your-user@dns-alpha:/opt/scriptwatch-agent/
   scp /mnt/appdata/scriptwatch/agent/requirements.txt your-user@dns-alpha:/opt/scriptwatch-agent/
   ```

4. **Install Python dependencies on the target server:**
   ```bash
   pip3 install -r /opt/scriptwatch-agent/requirements.txt
   ```

5. **Create the environment file at `/etc/scriptwatch.env`:**
   ```bash
   cat > /etc/scriptwatch.env << 'EOF'
   SCRIPTWATCH_API_URL=http://192.168.20.244:8095
   SCRIPTWATCH_SERVER_NAME=dns-alpha
   SCRIPTWATCH_AGENT_TOKEN=your-agent-token-here
   POLL_INTERVAL=10
   HEARTBEAT_INTERVAL=30
   EOF
   ```
   Replace `dns-alpha` and the token with the correct values. Set strict permissions:
   ```bash
   chmod 600 /etc/scriptwatch.env
   ```

6. **Install the systemd service:**
   Copy `agent/scriptwatch-agent.service` from this repo to the target server:
   ```bash
   scp /mnt/appdata/scriptwatch/agent/scriptwatch-agent.service your-user@dns-alpha:/etc/systemd/system/
   ```
   Then on the target server:
   ```bash
   systemctl daemon-reload
   systemctl enable scriptwatch-agent
   systemctl start scriptwatch-agent
   ```

7. **Verify it's running:**
   ```bash
   systemctl status scriptwatch-agent
   journalctl -u scriptwatch-agent -n 30
   ```
   You should see the agent registered and polling.

### Update (Systemd method)

1. **Copy the new `agent.py` to the target server:**
   ```bash
   scp /mnt/appdata/scriptwatch/agent/agent.py your-user@dns-alpha:/opt/scriptwatch-agent/
   ```

2. **Restart the service:**
   ```bash
   systemctl restart scriptwatch-agent
   ```

3. **Confirm:**
   ```bash
   journalctl -u scriptwatch-agent -n 10
   ```

---

## Server Name Reference

| Server     | `SCRIPTWATCH_SERVER_NAME` value |
|------------|----------------------------------|
| DNS Alpha  | `dns-alpha`                      |
| DNS Beta   | `dns-beta`                       |

Make sure this value matches exactly what is registered in ScriptWatch's server list — it's how the API routes pending jobs to the right server.

---

## Can the agent run on a regular Debian computer?

**Yes, with no changes.** The agent is just a Python script — it has no special hardware or OS requirements. Any machine running Debian (or any other Linux distro) can run it using Method B above.

The only requirements are:
- Python 3 (any version 3.8+)
- The `requests` pip package
- Network access to the ScriptWatch API URL

This means you can use ScriptWatch to monitor and remotely trigger scripts on:
- Home lab servers
- Regular desktop Debian machines
- VMs
- Raspberry Pis
- Any Linux host that can reach the API

Just register the machine in ScriptWatch with a unique name, assign scripts to it in the web UI, and install the agent using Method B.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Agent not appearing as online in dashboard | Check `SCRIPTWATCH_SERVER_NAME` matches the registered name exactly |
| "401 Unauthorized" in logs | `SCRIPTWATCH_AGENT_TOKEN` is wrong or missing |
| "Connection refused" / network errors | API URL is wrong, or firewall is blocking port 8095 |
| Jobs stuck in "pending" | Agent may be down — check `systemctl status` or `docker logs` |
