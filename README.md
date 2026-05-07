# ScriptWatch Standalone

ScriptWatch Standalone manages shell scripts, schedules jobs, and dispatches them to lightweight agents without requiring PostgreSQL or Gitea.

Everything lives locally:

- SQLite database: `./data/scriptwatch.db`
- Script source and version snapshots: `./data/script-store`
- Agent token and app secrets: your local `.env`

## Quick Start

### Docker Compose

Use this path when you have the repo files on the machine running Docker. The compose file uses `build: .`, so Docker needs to see this repo's `Dockerfile`.

1. Create an environment file with fresh secrets and setup values:

   ```bash
   ./tools/setup-env.sh
   ```

   If you prefer a quick start, you can also copy `.env.example`:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set your app URL and any optional values:

   ```env
   BASE_URL=http://your-server-ip:8080
   ```

   Keep Docker container paths as `/app/data`; the compose file maps that to `./data` on the host.

3. Start the app:

   ```bash
   docker compose up -d
   ```

4. Open:

   ```text
   http://your-server-ip:8080
   ```

5. Go to Settings to set an admin password and copy the agent install command.

### Unraid

ScriptWatch can run as a single Unraid container. It does not need PostgreSQL, Gitea, Redis, or any other companion service.

There are two good Unraid paths:

- Use the Unraid Docker template at `agent/scriptwatch.xml`.
- Use Compose Manager with an already-built image.

If you use Compose Manager, do not paste the repo `docker-compose.yml` unchanged unless the whole repo is in that Compose project folder. In Compose Manager, `build: .` points at `/boot/config/plugins/compose.manager/projects/<stack-name>/`, and `./data` would also live there. For Unraid, use an image and map data to appdata instead.

Example Compose Manager stack:

```yaml
services:
  api:
    image: scriptwatch-standalone:latest
    container_name: scriptwatch
    restart: unless-stopped
    environment:
      DATA_DIR: /app/data
      DATABASE_URL: sqlite:////app/data/scriptwatch.db
      SCRIPT_STORE_DIR: /app/data/script-store
      AGENT_TOKEN: replace-with-a-long-random-value
      SECRET_KEY: replace-with-a-different-long-random-value
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: ""
      ADMIN_TOKEN: ""
      NTFY_URL: ""
      NTFY_TOKEN: ""
      DISCORD_WEBHOOK_URL: ""
      BASE_URL: http://tower:8080
      MISSED_RUN_GRACE_MINUTES: 15
      JOB_RETENTION_DAYS: 30
    volumes:
      - /mnt/user/appdata/scriptwatch:/app/data
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5))"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
```

Replace `image:` with your registry image if you pushed one, for example `your-registry.example.com/your-user/scriptwatch-standalone:latest`.

1. Build or provide an image for Unraid to run.

   If you are testing locally on the Unraid host, build the image from this repo and use `scriptwatch-standalone:latest` as the repository name:

   ```bash
   docker build -t scriptwatch-standalone:latest .
   ```

   If you publish the image to a registry, use that registry image instead in the Unraid template.

2. Add the container in Unraid, either with the Docker template or Compose Manager.

   The standalone template is at:

   ```text
   agent/scriptwatch.xml
   ```

   Important settings:

   - Map `/app/data` to persistent storage, for example `/mnt/user/appdata/scriptwatch`.
   - Set `BASE_URL` to the URL agents can reach, for example `http://tower:8080` or `http://192.168.1.50:8080`.
   - Generate unique values for `AGENT_TOKEN` and `SECRET_KEY`.
   - Leave `DATABASE_URL` as `sqlite:////app/data/scriptwatch.db` unless you intentionally move the SQLite file.

3. Start the container and open the Web UI from Unraid.

4. Go to Settings to set an admin password and copy the agent install command.

You can generate secret values on any machine with Python:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

On Unraid, this also works from the terminal:

```bash
openssl rand -base64 48
```

### Agent Installs

After the API is running, create a server in ScriptWatch and use the install command shown in Settings. The command includes your `BASE_URL` and `AGENT_TOKEN`, so set those before installing agents.

For Unraid agents, the template at `agent/scriptwatch-agent.xml` can be used on each target server. Set:

- `SCRIPTWATCH_API_URL` to the central ScriptWatch URL.
- `SCRIPTWATCH_SERVER_NAME` to the exact server name created in the dashboard.
- `SCRIPTWATCH_AGENT_TOKEN` to the API container's `AGENT_TOKEN`.

## Sharing

Do not share your `.env` file. Each install should generate its own `AGENT_TOKEN`, `SECRET_KEY`, and admin password.

Back up the persistent data directory, not the container:

- Docker Compose: `./data`
- Unraid: the host path mapped to `/app/data`, commonly `/mnt/user/appdata/scriptwatch`

## Notes

The app keeps the original internal `gitea_path`/`gitea_sha` names for compatibility, but this standalone edition stores script content and history on disk under `./data/script-store`.
