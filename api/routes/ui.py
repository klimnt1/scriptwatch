from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, current_app
from sqlalchemy import func
from api.extensions import db
from api.models import Server, Job, Script, MissedRun

ui_bp = Blueprint("ui", __name__, template_folder="../templates", static_folder="../static")


@ui_bp.get("/")
def dashboard():
    page = request.args.get("page", 1, type=int)
    per_page = 10
    job_query = Job.query
    job_filters = {
        "status": request.args.get("status", "").strip(),
        "server_id": request.args.get("server_id", type=int),
        "script_id": request.args.get("script_id", type=int),
        "triggered_by": request.args.get("triggered_by", "").strip(),
        "dismissed": request.args.get("dismissed", "").strip(),
    }
    if job_filters["status"] == "active":
        job_query = job_query.filter(Job.status.in_(["running", "pending", "cancelling"]))
    elif job_filters["status"]:
        job_query = job_query.filter(Job.status == job_filters["status"])
    if job_filters["server_id"]:
        job_query = job_query.filter(Job.server_id == job_filters["server_id"])
    if job_filters["script_id"]:
        job_query = job_query.filter(Job.script_id == job_filters["script_id"])
    if job_filters["triggered_by"]:
        job_query = job_query.filter(Job.triggered_by == job_filters["triggered_by"])
    if job_filters["dismissed"] == "true":
        job_query = job_query.filter(Job.dismissed == True)  # noqa: E712
    elif job_filters["dismissed"] == "false":
        job_query = job_query.filter(Job.dismissed == False)  # noqa: E712
    pagination = job_query.order_by(Job.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    scripts = Script.query.order_by(Script.name).all()

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_jobs = Job.query.filter(Job.created_at >= today_start)
    stats = {
        "today_total": today_jobs.count(),
        "today_successes": today_jobs.filter(Job.status == "success").count(),
        "today_failures": today_jobs.filter(
            Job.status.in_(["failure", "timeout"]),
            Job.dismissed == False,  # noqa: E712
        ).count(),
        "running_now": Job.query.filter(Job.status == "running").count(),
    }

    active_failures = (
        Job.query
        .filter(Job.status.in_(["failure", "timeout"]), Job.dismissed == False)  # noqa: E712
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(50)
        .all()
    )

    active_anomalies = (
        Job.query
        .filter(Job.anomaly_detected == True, Job.dismissed == False)  # noqa: E712
        .order_by(Job.completed_at.desc(), Job.created_at.desc())
        .limit(20)
        .all()
    )

    recent_missed = (
        MissedRun.query
        .filter(MissedRun.alerted_at >= datetime.utcnow() - timedelta(hours=24), MissedRun.dismissed == False)  # noqa: E712
        .order_by(MissedRun.alerted_at.desc())
        .limit(10)
        .all()
    )

    running_jobs = (
        Job.query
        .filter(Job.status.in_(["running", "pending", "cancelling"]))
        .order_by(Job.created_at)
        .all()
    )

    latest_agent_hash = None
    try:
        from api.routes.agents import get_latest_agent_hash
        latest_agent_hash = get_latest_agent_hash(current_app.config)
    except Exception:
        pass

    return render_template(
        "dashboard.html",
        servers=servers,
        scripts=scripts,
        recent_jobs=pagination.items,
        pagination=pagination,
        job_filters=job_filters,
        stats=stats,
        active_failures=active_failures,
        active_anomalies=active_anomalies,
        missed_runs=recent_missed,
        running_jobs=running_jobs,
        latest_agent_hash=latest_agent_hash,
    )


@ui_bp.get("/scripts")
def scripts_page():
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    scripts = Script.query.order_by(Script.name).all()
    return render_template("scripts.html", servers=servers, scripts=scripts)


@ui_bp.get("/scripts/new")
def new_script_page():
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    return render_template("script_detail.html", script=None, servers=servers, content="")


@ui_bp.get("/scripts/<int:script_id>")
def edit_script_page(script_id):
    from api.extensions import db
    from api.models import Script
    from api.services.gitea import GiteaClient
    from flask import current_app
    script = db.session.get(Script, script_id)
    if not script:
        return "Not found", 404
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    gitea = GiteaClient()
    content, _ = gitea.get_file(script.gitea_path)
    return render_template("script_detail.html", script=script, servers=servers, content=content or "")


@ui_bp.get("/search")
def search_page():
    return render_template("search.html")


@ui_bp.get("/jobs/<int:job_id>")
def job_detail_page(job_id):
    from api.extensions import db
    job = db.session.get(Job, job_id)
    if not job:
        return "Not found", 404
    return render_template("job_detail.html", job=job)
