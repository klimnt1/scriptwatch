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

### Portainer

Use this path when you already have a ScriptWatch image available and want to create the container from Portainer's **Containers > Add container** screen.

1. Fill in the top section:

   ```text
   Name: scriptwatch
   Image: your-registry.example.com/your-user/scriptwatch-standalone:latest
   ```

   If the image is only local on the Docker host, use the local image name, for example `scriptwatch-standalone:latest`, and turn off **Always pull the image**.

2. Under **Network ports configuration**, add one port mapping:

   ```text
   Host port: 8080
   Container port: 8080
   Protocol: TCP
   ```

3. Under **Advanced container settings > Volumes**, add a bind mount:

   ```text
   Container: /app/data
   Host: /opt/scriptwatch/data
   ```

   You can use another host path if you prefer. This folder is the important backup target because it contains the SQLite database and local script snapshots.

4. Under **Advanced container settings > Env**, review these variables.

   Newer images include these environment variables as editable defaults in Portainer. If any are missing, add them manually:

   ```env
   DATA_DIR=/app/data
   DATABASE_URL=sqlite:////app/data/scriptwatch.db
   SCRIPT_STORE_DIR=/app/data/script-store
   AGENT_TOKEN=replace-with-a-long-random-value
   SECRET_KEY=replace-with-a-different-long-random-value
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=
   ADMIN_TOKEN=
   BASE_URL=http://your-server-ip:8080
   NTFY_URL=
   NTFY_TOKEN=
   DISCORD_WEBHOOK_URL=
   MISSED_RUN_GRACE_MINUTES=15
   JOB_RETENTION_DAYS=30
   ```

   Replace `AGENT_TOKEN`, `SECRET_KEY`, and `BASE_URL` before deploying. Leave the `/app/data` paths as-is unless you also change the volume mapping.

5. Under **Advanced container settings > Restart policy**, choose **Unless stopped**.

6. Deploy the container and open:

   ```text
   http://your-server-ip:8080
   ```

7. Go to Settings to set an admin password and copy the agent install command.

You can generate secret values on any machine with Python:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

If Python is not available, OpenSSL also works:

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
- Portainer: the host path mapped to `/app/data`, for example `/opt/scriptwatch/data`

## Notes

The app keeps the original internal `gitea_path`/`gitea_sha` names for compatibility, but this standalone edition stores script content and history on disk under `./data/script-store`.
