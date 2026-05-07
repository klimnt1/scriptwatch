from datetime import timezone as _utc
from zoneinfo import ZoneInfo
import requests

_ET = ZoneInfo("America/New_York")


def _fmt_et(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_utc.utc)
    return dt.astimezone(_ET).strftime("%Y-%m-%d %H:%M ET")


def notify_job_result(config, job):
    if job.status not in ("success", "failure", "timeout"):
        return
    if job.status == "success" and not getattr(job.script, "notify_on_success", False):
        return
    if job.status in ("failure", "timeout") and not getattr(job.script, "notify_on_failure", True):
        return

    server_name = job.server.name if job.server else "unknown"

    if job.status == "success":
        icon = "✅"
        title = f"{icon} {job.script.name} succeeded on {server_name}"
        color = 0x2ecc71
        ntfy_tags = "white_check_mark"
        ntfy_priority = "default"
    elif job.status == "timeout":
        icon = "⏱️"
        title = f"{icon} {job.script.name} timed out on {server_name}"
        color = 0xe67e22
        ntfy_tags = "hourglass"
        ntfy_priority = "high"
    else:
        icon = "❌"
        title = f"{icon} {job.script.name} failed on {server_name}"
        color = 0xe74c3c
        ntfy_tags = "rotating_light"
        ntfy_priority = "high"

    output = (job.output or "").strip()
    if len(output) > 500:
        output = "…" + output[-500:]
    snippet = output or "No output captured."

    base_url = config.get("BASE_URL", "").rstrip("/")
    job_url = f"{base_url}/jobs/{job.id}" if base_url else None

    if config.get("DISCORD_WEBHOOK_URL"):
        _notify_discord(config["DISCORD_WEBHOOK_URL"], title, snippet, job_url, color)

    if config.get("NTFY_URL"):
        _notify_ntfy(config, title, snippet, job_url, ntfy_tags, ntfy_priority)


def _notify_discord(webhook_url, title, snippet, job_url=None, color=0x95a5a6):
    embed = {
        "title": title,
        "description": f"```\n{snippet}\n```",
        "color": color,
    }
    if job_url:
        embed["url"] = job_url
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=5)
    except Exception:
        pass


def _notify_ntfy(config, title, snippet, job_url=None, tags="bell", priority="default"):
    headers = {
        "Title": title,
        "Tags": tags,
        "Priority": priority,
    }
    if job_url:
        headers["Click"] = job_url
    if config.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {config['NTFY_TOKEN']}"
    try:
        requests.post(config["NTFY_URL"], data=snippet.encode("utf-8"), headers=headers, timeout=5)
    except Exception:
        pass


def notify_missed_run(config, script, server, expected_at):
    server_name = server.name if server else "unknown"
    title = f"⚠️ Missed run: {script.name} on {server_name}"
    body = f"Expected at {_fmt_et(expected_at)} — no job was created."

    if config.get("DISCORD_WEBHOOK_URL"):
        _notify_discord(config["DISCORD_WEBHOOK_URL"], title, body, job_url=None, color=0xf39c12)

    if config.get("NTFY_URL"):
        _notify_ntfy(config, title, body, job_url=None, tags="warning", priority="high")
