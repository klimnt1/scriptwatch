import hmac
from statistics import median
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import or_
from api.extensions import db
from api.models import Job, Script, Server, MissedRun
from api.services.gitea import GiteaClient

jobs_bp = Blueprint("jobs", __name__)


def get_gitea_client():
    return GiteaClient()


def require_agent_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {current_app.config['AGENT_TOKEN']}"
        if not hmac.compare_digest(auth, expected):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _duration_seconds(job):
    if job.started_at and job.completed_at:
        return max(0, int((job.completed_at - job.started_at).total_seconds()))
    return None


def _detect_duration_anomaly(job):
    duration = job.duration_seconds
    if not duration or not job.script_id or not job.server_id:
        return False, None

    history = (
        Job.query
        .filter(
            Job.id != job.id,
            Job.script_id == job.script_id,
            Job.server_id == job.server_id,
            Job.status == "success",
            Job.duration_seconds.isnot(None),
            Job.anomaly_detected == False,  # noqa: E712
        )
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(20)
        .all()
    )
    durations = [j.duration_seconds for j in history if j.duration_seconds and j.duration_seconds > 0]
    if len(durations) < 3:
        return False, None

    baseline = int(median(durations))
    if baseline <= 0:
        return False, None

    if duration >= max(baseline * 3, baseline + 1800):
        return True, f"Runtime {duration}s is unusually high; recent median is {baseline}s."
    return False, None


def _get_script_snapshot(script, ref=None):
    if not script:
        return None, None
    if current_app.config.get("TESTING"):
        return None, script.gitea_sha
    try:
        return get_gitea_client().get_file(script.gitea_path, ref=ref)
    except Exception:
        return None, script.gitea_sha


def _make_replay_job(job, mode):
    if job.script_id is None:
        return None, ("system jobs cannot be replayed", 400)
    if job.status in ("pending", "running", "cancelling"):
        return None, ("only completed jobs can be replayed", 400)

    mode = mode if mode in ("current", "exact") else "current"
    script_content = None
    gitea_sha = job.script.gitea_sha if job.script else job.gitea_sha
    if mode == "exact":
        script_content = job.script_content
        gitea_sha = job.gitea_sha
        if script_content is None and job.script:
            script_content, fetched_sha = _get_script_snapshot(job.script, ref=job.gitea_sha)
            gitea_sha = fetched_sha or gitea_sha

    new_job = Job(
        script_id=job.script_id,
        server_id=job.server_id,
        triggered_by="replay",
        gitea_sha=gitea_sha,
        script_content=script_content,
        parameters=job.parameters or {},
        replayed_from_job_id=job.id,
        replay_mode=mode,
    )
    db.session.add(new_job)
    db.session.commit()
    return new_job, None


def _append_job_output(job, output):
    if not output:
        return
    prefix = (job.output or "").rstrip()
    joined = f"{prefix}\n{output}" if prefix else output
    job.output = joined[-10000:]


@jobs_bp.get("/search")
def search_jobs():
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify({"error": "Query must be at least 3 characters"}), 400
    results = (
        Job.query
        .filter(Job.output.ilike(f"%{q}%"))
        .order_by(Job.created_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for job in results:
        output = job.output or ""
        idx = output.lower().find(q.lower())
        snippet = output[max(0, idx - 100):idx + 200].strip() if idx >= 0 else ""
        d = job.to_dict()
        d["snippet"] = snippet
        out.append(d)
    return jsonify(out)


@jobs_bp.get("/")
def list_jobs():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    query = Job.query

    status = request.args.get("status", "").strip()
    if status == "active":
        query = query.filter(Job.status.in_(["running", "pending", "cancelling"]))
    elif status:
        query = query.filter(Job.status == status)

    server_id = request.args.get("server_id", type=int)
    if server_id:
        query = query.filter(Job.server_id == server_id)

    script_id = request.args.get("script_id", type=int)
    if script_id:
        query = query.filter(Job.script_id == script_id)

    triggered_by = request.args.get("triggered_by", "").strip()
    if triggered_by:
        query = query.filter(Job.triggered_by == triggered_by)

    dismissed = request.args.get("dismissed", "").strip().lower()
    if dismissed in ("true", "1", "yes"):
        query = query.filter(Job.dismissed == True)  # noqa: E712
    elif dismissed in ("false", "0", "no"):
        query = query.filter(Job.dismissed == False)  # noqa: E712

    created_from = request.args.get("created_from", "").strip()
    if created_from:
        try:
            query = query.filter(Job.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            return jsonify({"error": "created_from must be an ISO date or datetime"}), 400

    created_to = request.args.get("created_to", "").strip()
    if created_to:
        try:
            query = query.filter(Job.created_at <= datetime.fromisoformat(created_to))
        except ValueError:
            return jsonify({"error": "created_to must be an ISO date or datetime"}), 400

    p = query.order_by(Job.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"jobs": [j.to_dict() for j in p.items], "total": p.total, "pages": p.pages})


@jobs_bp.get("/failures")
def active_failures():
    jobs = (
        Job.query
        .filter(Job.status.in_(["failure", "timeout"]), Job.dismissed == False)  # noqa: E712
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify([j.to_dict() for j in jobs])


@jobs_bp.get("/anomalies")
def active_anomalies():
    jobs = (
        Job.query
        .filter(Job.anomaly_detected == True, Job.dismissed == False)  # noqa: E712
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify([j.to_dict() for j in jobs])


@jobs_bp.get("/<int:job_id>")
def get_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job.to_dict(include_output=True))


@jobs_bp.post("/<int:job_id>/dismiss")
def dismiss_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    if job.status not in ("failure", "timeout") and not job.anomaly_detected:
        return jsonify({"error": "only failed, timed out, or anomalous jobs can be dismissed"}), 400
    job.dismissed = True
    db.session.commit()
    return jsonify(job.to_dict())


@jobs_bp.post("/<int:job_id>/output")
@require_agent_token
def append_job_output(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True) or {}
    _append_job_output(job, data.get("output") or "")
    db.session.commit()
    return jsonify(job.to_dict(include_output=True))


@jobs_bp.get("/pending/<string:server_name>")
@require_agent_token
def pending_jobs(server_name):
    server = Server.query.filter_by(name=server_name).first()
    if not server:
        return jsonify([])

    jobs = (
        Job.query
        .filter(Job.server_id == server.id, Job.status == "pending")
        .order_by(Job.created_at)
        .all()
    )

    result = []
    gitea = get_gitea_client()
    for job in jobs:
        if job.script_content is not None:
            content = job.script_content
            timeout = job.script.timeout_seconds if job.script else 300
        else:
            content, fetched_sha = gitea.get_file(job.script.gitea_path, ref=job.gitea_sha)
            if content is None and job.gitea_sha:
                content, fetched_sha = gitea.get_file(job.script.gitea_path)
            if fetched_sha and fetched_sha != job.gitea_sha:
                job.gitea_sha = fetched_sha
                db.session.commit()
            timeout = job.script.timeout_seconds
        result.append({
            **job.to_dict(),
            "script_content": content or "",
            "timeout_seconds": timeout,
            "parameters": job.parameters or {},
        })
    return jsonify(result)


@jobs_bp.put("/<int:job_id>/start")
@require_agent_token
def start_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    job.status = "running"
    job.started_at = datetime.utcnow()
    db.session.commit()
    return jsonify(job.to_dict())


@jobs_bp.post("/<int:job_id>/retry")
def retry_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    new_job, error = _make_replay_job(job, "current")
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify(new_job.to_dict()), 201


@jobs_bp.post("/<int:job_id>/replay")
def replay_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    new_job, error = _make_replay_job(job, data.get("mode", "current"))
    if error:
        message, status = error
        return jsonify({"error": message}), status
    return jsonify(new_job.to_dict()), 201


@jobs_bp.delete("/missed-runs")
def dismiss_missed_runs():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    MissedRun.query.filter(
        MissedRun.alerted_at >= cutoff,
        MissedRun.dismissed == False,  # noqa: E712
    ).update({"dismissed": True})
    db.session.commit()
    return jsonify({"ok": True})


def _cleanup_stuck_jobs():
    """Cancel stuck jobs and remove uninstalling servers after they stop heartbeating."""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    stuck = (
        Job.query
        .join(Server, Job.server_id == Server.id)
        .filter(
            Job.status.in_(["running", "cancelling"]),
            Server.last_heartbeat < cutoff,
        )
        .all()
    )
    for job in stuck:
        job.status = "cancelled" if job.triggered_by == "uninstall" else "failure"
        job.exit_code = -1
        job.completed_at = datetime.utcnow()
        job.duration_seconds = _duration_seconds(job)
        job.output = ((job.output or "") + "\n[Auto-cancelled: server went offline]").strip()
    db.session.commit()

    removable_servers = (
        Server.query
        .filter(
            Server.pending_uninstall == True,  # noqa: E712
            or_(Server.last_heartbeat == None, Server.last_heartbeat < cutoff),  # noqa: E711
        )
        .all()
    )
    for server in removable_servers:
        uninstall_jobs = Job.query.filter_by(server_id=server.id, triggered_by="uninstall").all()
        for job in uninstall_jobs:
            job.server_id = None
            job.completed_at = job.completed_at or datetime.utcnow()
            if job.status in ("pending", "running", "cancelling"):
                job.status = "cancelled"
                job.exit_code = -1
            _append_job_output(job, f"[Server record removed after uninstall cleanup: {server.name}]")
        Job.query.filter(Job.server_id == server.id, Job.triggered_by != "uninstall").delete()
        db.session.delete(server)
    db.session.commit()


@jobs_bp.get("/stats")
def job_stats():
    try:
        _cleanup_stuck_jobs()
    except Exception:
        db.session.rollback()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_jobs = Job.query.filter(Job.created_at >= today_start)
    return jsonify({
        "running_now": Job.query.filter(Job.status.in_(["running", "pending", "cancelling"])).count(),
        "today_total": today_jobs.count(),
        "today_successes": today_jobs.filter(Job.status == "success").count(),
        "today_failures": today_jobs.filter(
            Job.status.in_(["failure", "timeout"]),
            Job.dismissed == False,  # noqa: E712
        ).count(),
    })


@jobs_bp.get("/running")
def running_jobs():
    jobs = (
        Job.query
        .filter(Job.status.in_(["pending", "running", "cancelling"]))
        .order_by(Job.created_at)
        .all()
    )
    return jsonify([j.to_dict() for j in jobs])


@jobs_bp.post("/<int:job_id>/cancel")
def cancel_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    if job.status == "pending":
        # Never started — finish it immediately, no agent needed
        job.status = "cancelled"
        job.exit_code = -1
        job.completed_at = datetime.utcnow()
    elif job.status == "running":
        # Signal the agent to kill it
        job.status = "cancelling"
    elif job.status == "cancelling":
        # Agent died or job was never running — force-close it
        job.status = "cancelled"
        job.exit_code = -1
        job.completed_at = datetime.utcnow()
    else:
        return jsonify({"error": "job is not cancellable"}), 400
    db.session.commit()
    return jsonify(job.to_dict())


@jobs_bp.put("/<int:job_id>/complete")
@require_agent_token
def complete_job(job_id):
    job = db.session.get(Job, job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    job.status = data.get("status", "success")
    job.exit_code = data.get("exit_code")
    job.output = (data.get("output") or "")[-10000:]
    job.completed_at = datetime.utcnow()
    job.duration_seconds = _duration_seconds(job)
    job.anomaly_detected, job.anomaly_reason = _detect_duration_anomaly(job)
    db.session.commit()
    try:
        from api.services.notifier import notify_job_result
        notify_job_result(current_app.config, job)
    except Exception:
        pass
    result = job.to_dict()
    if job.triggered_by == "uninstall" and job.server_id:
        server = db.session.get(Server, job.server_id)
        if server:
            server.pending_uninstall = True
            db.session.commit()
    return jsonify(result)
