from collections import defaultdict
from datetime import datetime, timedelta, timezone as _utc
from zoneinfo import ZoneInfo
import requests

_ET = ZoneInfo("America/New_York")


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _db_setting(key):
    try:
        from api.extensions import db
        from api.models import AppSetting
        setting = db.session.get(AppSetting, key)
        return setting.value if setting else None
    except Exception:
        return None


def _fmt_et(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_utc.utc)
    return dt.astimezone(_ET).strftime("%Y-%m-%d %H:%M ET")


def _setting_bool(key, default):
    value = _db_setting(key)
    if value is None or value == "":
        return bool(default)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _setting_int(key, default, min_value=None, max_value=None):
    value = _db_setting(key)
    if value is None or value == "":
        value = default
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = int(default)
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _fmt_duration(seconds):
    if seconds is None:
        return "unknown duration"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minute}m"
    if minutes:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    return f"{sec}s"


def _format_custom_message(template, job, server_name, output):
    if not template:
        return None
    values = _SafeFormatDict({
        "script": job.script.name if job.script else "",
        "server": server_name,
        "status": job.status,
        "job_id": job.id,
        "exit_code": "" if job.exit_code is None else job.exit_code,
        "output": output,
    })
    try:
        return template.format_map(values).strip()
    except Exception:
        return template.strip()


def build_daily_digest(
    jobs,
    start,
    end,
    include_failures=True,
    include_anomalies=True,
    include_scripts=True,
):
    jobs = [job for job in jobs if job.script]
    title_date = start.date().isoformat()
    title = f"ScriptWatch Daily Digest - {title_date}"

    servers = sorted({job.server.name for job in jobs if job.server})
    counts = defaultdict(int)
    per_script = defaultdict(lambda: defaultdict(int))
    failures = []
    anomalies = []

    for job in jobs:
        status = job.status or "unknown"
        counts[status] += 1
        per_script[job.script.name]["total"] += 1
        per_script[job.script.name][status] += 1
        server_name = job.server.name if job.server else "unknown"
        if status in ("failure", "timeout", "cancelled"):
            failures.append(job)
        if job.anomaly_detected:
            anomalies.append(job)

    lines = [
        f"{len(jobs)} completed jobs across {len(servers)} server{'s' if len(servers) != 1 else ''}",
        "",
        f"Success: {counts['success']}",
        f"Failed: {counts['failure']}",
        f"Timed out: {counts['timeout']}",
        f"Cancelled: {counts['cancelled']}",
    ]

    if include_failures and failures:
        lines.extend(["", "Failures:"])
        for job in sorted(failures, key=lambda j: j.completed_at or j.created_at, reverse=True)[:10]:
            server_name = job.server.name if job.server else "unknown"
            exit_text = f", exit {job.exit_code}" if job.exit_code is not None else ""
            lines.append(f"- {job.script.name} on {server_name} {job.status}{exit_text}")

    if include_anomalies and anomalies:
        lines.extend(["", "Slow/anomalous:"])
        for job in sorted(anomalies, key=lambda j: j.completed_at or j.created_at, reverse=True)[:10]:
            server_name = job.server.name if job.server else "unknown"
            reason = f" - {job.anomaly_reason}" if job.anomaly_reason else ""
            lines.append(f"- {job.script.name} on {server_name} took {_fmt_duration(job.duration_seconds)}{reason}")

    if include_scripts and per_script:
        lines.extend(["", "By script:"])
        for script_name in sorted(per_script):
            row = per_script[script_name]
            bad = row["failure"] + row["timeout"] + row["cancelled"]
            lines.append(f"- {script_name}: {row['total']} total, {row['success']} success, {bad} problem")

    if not jobs:
        lines = [
            f"No completed script jobs from {start.isoformat(timespec='minutes')} to {end.isoformat(timespec='minutes')}.",
        ]

    return title, "\n".join(lines)


def notify_daily_digest(config, now=None):
    if not _setting_bool("daily_digest_enabled", config.get("DAILY_DIGEST_ENABLED", False)):
        return False

    from api.models import Job

    lookback_hours = _setting_int(
        "daily_digest_lookback_hours",
        config.get("DAILY_DIGEST_LOOKBACK_HOURS", 24),
        min_value=1,
        max_value=168,
    )
    end = now or datetime.utcnow()
    start = end - timedelta(hours=lookback_hours)
    jobs = (
        Job.query
        .filter(
            Job.completed_at >= start,
            Job.completed_at <= end,
            Job.status.in_(["success", "failure", "timeout", "cancelled"]),
            Job.script_id.isnot(None),
        )
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .all()
    )
    title, body = build_daily_digest(
        jobs,
        start,
        end,
        include_failures=_setting_bool("daily_digest_include_failures", config.get("DAILY_DIGEST_INCLUDE_FAILURES", True)),
        include_anomalies=_setting_bool("daily_digest_include_anomalies", config.get("DAILY_DIGEST_INCLUDE_ANOMALIES", True)),
        include_scripts=_setting_bool("daily_digest_include_scripts", config.get("DAILY_DIGEST_INCLUDE_SCRIPTS", True)),
    )

    discord_url = _db_setting("discord_webhook_url") or config.get("DISCORD_WEBHOOK_URL")
    ntfy_url = _db_setting("ntfy_url") or config.get("NTFY_URL")
    ntfy_token = _db_setting("ntfy_token") or config.get("NTFY_TOKEN")

    sent = False
    if discord_url:
        _notify_discord(discord_url, title, body, color=0x3498db)
        sent = True
    if ntfy_url:
        _notify_ntfy(ntfy_url, ntfy_token, title, body, tags="bar_chart", priority="default")
        sent = True
    return sent


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

    raw_output = (job.output or "").strip()
    output = raw_output
    if len(output) > 500:
        output = "…" + output[-500:]
    snippet = output or "No output captured."
    if job.status == "success":
        custom_message = _format_custom_message(
            getattr(job.script, "success_notification_message", None),
            job,
            server_name,
            raw_output,
        )
        if custom_message:
            snippet = custom_message

    base_url = config.get("BASE_URL", "").rstrip("/")
    job_url = f"{base_url}/jobs/{job.id}" if base_url else None

    discord_url = _db_setting("discord_webhook_url") or config.get("DISCORD_WEBHOOK_URL")
    ntfy_url = _db_setting("ntfy_url") or config.get("NTFY_URL")
    ntfy_token = _db_setting("ntfy_token") or config.get("NTFY_TOKEN")

    if discord_url:
        _notify_discord(discord_url, title, snippet, job_url, color)

    if ntfy_url:
        _notify_ntfy(ntfy_url, ntfy_token, title, snippet, job_url, ntfy_tags, ntfy_priority)


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


def _notify_ntfy(ntfy_url, ntfy_token, title, snippet, job_url=None, tags="bell", priority="default"):
    headers = {
        "Title": title,
        "Tags": tags,
        "Priority": priority,
    }
    if job_url:
        headers["Click"] = job_url
    if ntfy_token:
        headers["Authorization"] = f"Bearer {ntfy_token}"
    try:
        requests.post(ntfy_url, data=snippet.encode("utf-8"), headers=headers, timeout=5)
    except Exception:
        pass


def notify_missed_run(config, script, server, expected_at):
    server_name = server.name if server else "unknown"
    title = f"⚠️ Missed run: {script.name} on {server_name}"
    body = f"Expected at {_fmt_et(expected_at)} — no job was created."

    discord_url = _db_setting("discord_webhook_url") or config.get("DISCORD_WEBHOOK_URL")
    ntfy_url = _db_setting("ntfy_url") or config.get("NTFY_URL")
    ntfy_token = _db_setting("ntfy_token") or config.get("NTFY_TOKEN")

    if discord_url:
        _notify_discord(discord_url, title, body, job_url=None, color=0xf39c12)

    if ntfy_url:
        _notify_ntfy(ntfy_url, ntfy_token, title, body, job_url=None, tags="warning", priority="high")
