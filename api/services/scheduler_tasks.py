from datetime import datetime, timedelta
import pytz
from croniter import croniter
from api.services.notifier import notify_missed_run


def parse_schedule(schedule_str):
    """Parse a schedule string with optional TZ= prefix.

    Accepted formats:
        0 7 * * *                        (UTC assumed)
        TZ=America/New_York 0 7 * * *   (inline timezone)

    Returns (cron_5part_str, timezone_str).
    """
    s = (schedule_str or "").strip()
    tz = "UTC"
    if s.upper().startswith("TZ="):
        tokens = s.split()
        tz = tokens[0][3:]
        s = " ".join(tokens[1:])
    return s, tz


def make_pruner(app):
    def prune_old_jobs():
        with app.app_context():
            from api.extensions import db
            from api.models import Job
            cutoff = datetime.utcnow() - timedelta(days=app.config["JOB_RETENTION_DAYS"])
            deleted = Job.query.filter(Job.created_at < cutoff).delete()
            db.session.commit()
    return prune_old_jobs


def register_pruner(scheduler, app):
    scheduler.add_job(
        func=make_pruner(app),
        trigger="cron",
        hour=3,
        minute=0,
        id="job_pruner",
        replace_existing=True,
    )


def make_job_creator(app, script_id, server_id):
    def create_scheduled_job():
        with app.app_context():
            from api.extensions import db
            from api.models import Job, Script
            from api.services.gitea import GiteaClient
            script = db.session.get(Script, script_id)
            if script and script.enabled:
                content = None
                sha = script.gitea_sha
                try:
                    gitea = GiteaClient()
                    content, fetched_sha = gitea.get_file(script.gitea_path)
                    sha = fetched_sha or sha
                except Exception:
                    pass
                job = Job(
                    script_id=script_id,
                    server_id=server_id,
                    triggered_by="schedule",
                    gitea_sha=sha,
                    script_content=content,
                )
                db.session.add(job)
                db.session.commit()
    return create_scheduled_job


def register_script_schedules(scheduler, script, app):
    unregister_script_schedules(scheduler, script.id)
    if not script.enabled:
        return
    for sa in script.server_assignments:
        if not sa.schedule:
            continue
        cron_str, tz = parse_schedule(sa.schedule)
        parts = cron_str.split()
        if len(parts) != 5:
            continue
        minute, hour, day, month, day_of_week = parts
        job_id = f"script_{script.id}_server_{sa.server_id}"
        scheduler.add_job(
            func=make_job_creator(app, script.id, sa.server_id),
            trigger="cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=tz,
            id=job_id,
            replace_existing=True,
        )


def unregister_script_schedules(scheduler, script_id):
    prefix = f"script_{script_id}_server_"
    for job in scheduler.get_jobs():
        if job.id.startswith(prefix):
            scheduler.remove_job(job.id)


def make_missed_run_checker(app, grace_minutes=15):
    def check_missed_runs():
        with app.app_context():
            from api.extensions import db
            from api.models import ScriptServer, Job, MissedRun

            now = datetime.utcnow()
            grace = timedelta(minutes=grace_minutes)
            window = timedelta(minutes=2)

            for sa in ScriptServer.query.all():
                if not sa.script or not sa.script.enabled:
                    continue
                schedule = (sa.schedule or "").strip()
                cron_str, tz = parse_schedule(schedule)
                if len(cron_str.split()) != 5:
                    continue
                try:
                    tz_obj = pytz.timezone(tz)
                    now_local = datetime.now(tz_obj)
                    cron = croniter(cron_str, now_local)
                    prev_run_local = cron.get_prev(datetime)
                    prev_run = prev_run_local.astimezone(pytz.utc).replace(tzinfo=None)

                    if (now - prev_run) < grace:
                        continue

                    job_exists = Job.query.filter(
                        Job.script_id == sa.script_id,
                        Job.server_id == sa.server_id,
                        Job.triggered_by == "schedule",
                        Job.created_at >= prev_run - window,
                        Job.created_at <= prev_run + window,
                    ).first()

                    if job_exists:
                        continue

                    already_alerted = MissedRun.query.filter_by(
                        script_id=sa.script_id,
                        server_id=sa.server_id,
                        expected_at=prev_run,
                    ).first()

                    if already_alerted:
                        continue

                    missed = MissedRun(
                        script_id=sa.script_id,
                        server_id=sa.server_id,
                        expected_at=prev_run,
                        alerted_at=now,
                    )
                    db.session.add(missed)
                    db.session.commit()
                    notify_missed_run(app.config, sa.script, sa.server, prev_run)

                except Exception:
                    db.session.rollback()

    return check_missed_runs


def register_missed_run_checker(scheduler, app):
    grace = app.config.get("MISSED_RUN_GRACE_MINUTES", 15)
    scheduler.add_job(
        func=make_missed_run_checker(app, grace_minutes=grace),
        trigger="interval",
        minutes=5,
        id="missed_run_checker",
        replace_existing=True,
    )
