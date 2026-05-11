import os
import secrets


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


class Config:
    DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(DATA_DIR, 'scriptwatch.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCRIPT_STORE_DIR = os.environ.get("SCRIPT_STORE_DIR", os.path.join(DATA_DIR, "script-store"))
    GITEA_URL = os.environ.get("GITEA_URL", "")
    GITEA_TOKEN = os.environ.get("GITEA_TOKEN", "")
    GITEA_REPO_OWNER = os.environ.get("GITEA_REPO_OWNER", "")
    GITEA_REPO_NAME = os.environ.get("GITEA_REPO_NAME", "")
    AGENT_TOKEN = os.environ.get("AGENT_TOKEN") or None
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
    JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", 30))
    NTFY_URL = os.environ.get("NTFY_URL", "")
    NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    BASE_URL = os.environ.get("BASE_URL", "")
    MISSED_RUN_GRACE_MINUTES = int(os.environ.get("MISSED_RUN_GRACE_MINUTES", "15"))
    DAILY_DIGEST_ENABLED = _env_bool("DAILY_DIGEST_ENABLED", False)
    DAILY_DIGEST_HOUR = int(os.environ.get("DAILY_DIGEST_HOUR", "8"))
    DAILY_DIGEST_MINUTE = int(os.environ.get("DAILY_DIGEST_MINUTE", "0"))
    DAILY_DIGEST_TIMEZONE = os.environ.get("DAILY_DIGEST_TIMEZONE", "America/New_York")
    DAILY_DIGEST_LOOKBACK_HOURS = int(os.environ.get("DAILY_DIGEST_LOOKBACK_HOURS", "24"))
    DAILY_DIGEST_INCLUDE_FAILURES = _env_bool("DAILY_DIGEST_INCLUDE_FAILURES", True)
    DAILY_DIGEST_INCLUDE_ANOMALIES = _env_bool("DAILY_DIGEST_INCLUDE_ANOMALIES", True)
    DAILY_DIGEST_INCLUDE_SCRIPTS = _env_bool("DAILY_DIGEST_INCLUDE_SCRIPTS", True)
