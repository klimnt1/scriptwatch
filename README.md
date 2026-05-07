# ScriptWatch Standalone

ScriptWatch Standalone manages shell scripts, schedules jobs, and dispatches them to lightweight agents without requiring PostgreSQL or Gitea.

Everything lives locally:

- SQLite database: `./data/scriptwatch.db`
- Script source and version snapshots: `./data/script-store`
- Agent token and app secrets: your local `.env`

## Quick Start

### Docker Compose

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

1. Build or provide an image for Unraid to run.

   If you are testing locally on the Unraid host, build the image from this repo and use `scriptwatch-standalone:latest` as the repository name:

   ```bash
   docker build -t scriptwatch-standalone:latest .
   ```

   If you publish the image to a registry, use that registry image instead in the Unraid template.

2. Add the container in Unraid.

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
