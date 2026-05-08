# ScriptWatch Standalone

Manages shell scripts, schedules jobs, and dispatches them to lightweight agents. No PostgreSQL or Gitea required — everything is stored locally in SQLite.

## Quick Start

### Docker Compose

```bash
./tools/setup-env.sh   # generates AGENT_TOKEN and SECRET_KEY automatically
```

Edit `.env` and set your URL:

```env
BASE_URL=http://your-server-ip:8080
```

Then start:

```bash
docker compose up -d
```

Open `http://your-server-ip:8080` and go to **Settings** to set an admin password.

---

### Portainer (deploy from GitHub)

**Image:** `ghcr.io/klimnt1/scriptwatch:latest`

1. Create a new stack using the **Repository** build method, pointing to this repo.
2. Under **Environment variables**, set at minimum:

   | Variable | Description |
   |---|---|
   | `AGENT_TOKEN` | Shared secret agents use to authenticate — generate a random value |
   | `SECRET_KEY` | Signs browser session cookies — generate a different random value |
   | `BASE_URL` | Public URL of your ScriptWatch instance, e.g. `http://192.168.1.10:8080` |
   | `ADMIN_USERNAME` | Login username for the web UI (default: `admin`) |
   | `ADMIN_PASSWORD` | Password for the web UI (leave blank to disable auth) |

   Discord and ntfy can be configured from **Settings** inside the app — no env var needed.

3. Add a volume bind mount: **Container** `/app/data` → **Host** `/opt/scriptwatch/data`
4. Deploy and open `http://your-server-ip:8080`.

To generate secret values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Keep the same `AGENT_TOKEN`** when recreating the container — changing it requires reinstalling every agent.

---

### Agent Install

After the server is running, go to **Settings** and copy the agent install command. Run it with `sudo` on each target machine.

For Unraid, use the template at `agent/scriptwatch-agent.xml` and set `SCRIPTWATCH_API_URL`, `SCRIPTWATCH_SERVER_NAME`, and `SCRIPTWATCH_AGENT_TOKEN`.

---

## Data & Backups

Back up the data directory, not the container:

- Docker Compose: `./data`
- Portainer: the host path mapped to `/app/data` (e.g. `/opt/scriptwatch/data`)

Do not share your `.env`. Each install should have its own `AGENT_TOKEN` and `SECRET_KEY`.
