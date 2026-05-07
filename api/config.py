import os


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
    AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "changeme")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
    JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", 30))
    NTFY_URL = os.environ.get("NTFY_URL", "")
    NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    BASE_URL = os.environ.get("BASE_URL", "")
    MISSED_RUN_GRACE_MINUTES = int(os.environ.get("MISSED_RUN_GRACE_MINUTES", "15"))
