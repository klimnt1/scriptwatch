# ScriptWatch Standalone

ScriptWatch Standalone manages shell scripts, schedules jobs, and dispatches them to lightweight agents without requiring PostgreSQL or Gitea.

Everything lives locally:

- SQLite database: `./data/scriptwatch.db`
- Script source and version snapshots: `./data/script-store`
- Agent token and app secrets: your local `.env`

## Quick Start

1. Create an environment file with fresh secrets:

   ```bash
   ./tools/init-env.sh
   ```

2. Edit `.env` and set your app URL:

   ```env
   BASE_URL=http://your-server-ip:8080
   ```

3. Start the app:

   ```bash
   docker compose up -d
   ```

4. Open:

   ```text
   http://your-server-ip:8080
   ```

5. Go to Settings to set an admin password and copy the agent install command.

## Sharing

Do not share your `.env` file. Each install should generate its own `AGENT_TOKEN`, `SECRET_KEY`, and admin password.

## Notes

The app keeps the original internal `gitea_path`/`gitea_sha` names for compatibility, but this standalone edition stores script content and history on disk under `./data/script-store`.
