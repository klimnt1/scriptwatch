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

### Portainer

**Image:**
```
ghcr.io/klimnt1/scriptwatch:latest
```

1. In Portainer, go to **Containers → Add container** (or **Stacks → Add stack → Repository**).
2. Set the image above.
2. Under **Environment variables**, click **Advanced mode** and paste:

   ```env
   AGENT_TOKEN=replace-with-random-value
   SECRET_KEY=replace-with-different-random-value
   BASE_URL=http://your-server-ip:8080
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=
   ```

   | Variable | Description |
   |---|---|
   | `AGENT_TOKEN` | Shared secret agents use to authenticate |
   | `SECRET_KEY` | Signs browser session cookies |
   | `BASE_URL` | Public URL of your ScriptWatch instance |
   | `ADMIN_USERNAME` | Login username (default: `admin`) |
   | `ADMIN_PASSWORD` | Password for the web UI (leave blank to disable auth) |

   Discord and ntfy can be configured from **Settings** inside the app — no env var needed.

3. Add a volume bind mount: **Container** `/app/data` → **Host** `/opt/scriptwatch/data`
4. Deploy and open `http://your-server-ip:8080`.

To generate secret values:

```bash
openssl rand -hex 32
```

Or with Python:

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
#test