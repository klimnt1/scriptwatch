# ScriptWatch Standalone Agent Notes

This repo is the self-contained edition of ScriptWatch.

## Standalone Goals

- No PostgreSQL dependency: SQLite is the default database.
- No Gitea dependency: script source and version snapshots live under `data/script-store`.
- No shared secrets: each install must generate its own `.env`.

## Useful Commands

```bash
pytest
docker compose up -d
```

## Important Paths

- `api/`: Flask app and routes.
- `agent/`: remote worker process and install assets.
- `data/`: runtime SQLite database and local script store, ignored by git.
- `api/services/gitea.py`: compatibility wrapper that now stores scripts locally.

## Conventions

- Do not commit `.env`, `data/`, tokens, passwords, or generated databases.
- Keep the standalone version free of required external services.
- If runtime behavior changes, update `README.md` and focused tests.
