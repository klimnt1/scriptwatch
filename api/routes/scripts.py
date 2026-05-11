import re
import subprocess
import tempfile
from flask import Blueprint, jsonify, request, current_app
from api.extensions import db
from api.models import Script, Job, Server, ScriptServer, MissedRun
from api.services.gitea import GiteaClient

scripts_bp = Blueprint("scripts", __name__)


def get_gitea_client():
    return GiteaClient()


def _safe_get_file(gitea, path, ref=None):
    try:
        result = gitea.get_file(path, ref=ref)
        if isinstance(result, tuple) and len(result) == 2:
            return result
    except Exception:
        pass
    return None, None


def _current_script_snapshot(script):
    if current_app.config.get("TESTING"):
        return None, script.gitea_sha
    return _safe_get_file(get_gitea_client(), script.gitea_path)


def _make_gitea_path(script_name):
    slug = re.sub(r"[^a-z0-9]+", "-", script_name.lower()).strip("-")
    if not slug:
        raise ValueError("Script name produces an invalid path slug")
    return f"scripts/{slug}.sh"


def _build_server_assignments(server_ids, server_schedules):
    assignments = []
    for sid in server_ids:
        sid = int(sid)
        assignments.append(ScriptServer(
            server_id=sid,
            schedule=server_schedules.get(str(sid)) or server_schedules.get(sid) or None,
        ))
    return assignments


def _server_ids_from_tags(tags):
    tags = {str(t).strip() for t in (tags or []) if str(t).strip()}
    if not tags:
        return []
    servers = Server.query.filter(Server.pending_uninstall == False).all()  # noqa: E712
    return [s.id for s in servers if tags.intersection(set(s.tags or []))]


def _validate_shell(content):
    warnings = []
    if content and not content.startswith("#!"):
        warnings.append("Script has no shebang; agents run it with /bin/bash.")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=True) as tmp:
        tmp.write(content or "")
        tmp.flush()
        proc = subprocess.run(
            ["/bin/bash", "-n", tmp.name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    return {
        "valid": proc.returncode == 0,
        "output": proc.stdout.strip(),
        "warnings": warnings,
    }


def _commit_summary(commit):
    sha = commit.get("sha") or commit.get("id") or ""
    commit_data = commit.get("commit") or {}
    author = commit_data.get("author") or commit.get("author") or {}
    return {
        "sha": sha,
        "short_sha": sha[:8],
        "message": (commit_data.get("message") or commit.get("message") or "").splitlines()[0],
        "author": author.get("name") or author.get("username") or "",
        "created_at": author.get("date") or commit.get("created") or commit.get("created_at"),
    }


@scripts_bp.get("/")
def list_scripts():
    return jsonify([s.to_dict() for s in Script.query.order_by(Script.name).all()])


@scripts_bp.post("/")
def create_script():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        gitea_path = _make_gitea_path(name)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    server_ids = data.get("server_ids") or []
    server_ids.extend(_server_ids_from_tags(data.get("server_tags") or []))
    server_ids = sorted(set(int(sid) for sid in server_ids))
    server_schedules = data.get("server_schedules") or {}

    content = data.get("content") or ""
    gitea = get_gitea_client()
    _, existing_sha = _safe_get_file(gitea, gitea_path)
    sha = gitea.create_or_update_file(
        path=gitea_path,
        content=content,
        message=f"Add {gitea_path} via ScriptWatch UI",
        sha=existing_sha,
    )

    script = Script(
        name=name,
        description=data.get("description"),
        gitea_path=gitea_path,
        gitea_sha=sha,
        timeout_seconds=data.get("timeout_seconds", 3600),
        manual_trigger=data.get("manual_trigger", True),
        notify_on_failure=data.get("notify_on_failure", True),
        notify_on_success=data.get("notify_on_success", False),
        success_notification_message=(data.get("success_notification_message") or "").strip() or None,
        parameters=data.get("parameters") or [],
    )
    script.server_assignments = _build_server_assignments(server_ids, server_schedules)
    db.session.add(script)
    db.session.commit()
    if not current_app.config.get("TESTING"):
        from api.extensions import scheduler
        from api.services.scheduler_tasks import register_script_schedules
        register_script_schedules(scheduler, script, current_app._get_current_object())
    return jsonify(script.to_dict()), 201


@scripts_bp.get("/<int:script_id>")
def get_script(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404
    gitea = get_gitea_client()
    content, _ = _safe_get_file(gitea, script.gitea_path)
    d = script.to_dict()
    d["content"] = content or ""
    return jsonify(d)


@scripts_bp.get("/<int:script_id>/history")
def script_history(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404
    limit = min(max(request.args.get("limit", 20, type=int), 1), 50)
    gitea = get_gitea_client()
    try:
        commits = gitea.list_file_commits(script.gitea_path, limit=limit)
    except Exception as e:
        return jsonify({"error": f"failed to load local script history: {e}"}), 502
    return jsonify([_commit_summary(c) for c in commits])


@scripts_bp.get("/<int:script_id>/versions/<string:ref>")
def script_version(script_id, ref):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404
    content, sha = _safe_get_file(get_gitea_client(), script.gitea_path, ref=ref)
    if content is None:
        return jsonify({"error": "version not found"}), 404
    return jsonify({"content": content, "sha": sha, "ref": ref})


@scripts_bp.post("/<int:script_id>/restore")
def restore_script_version(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True) or {}
    ref = (data.get("ref") or "").strip()
    if not ref:
        return jsonify({"error": "ref is required"}), 400

    gitea = get_gitea_client()
    content, _ = _safe_get_file(gitea, script.gitea_path, ref=ref)
    if content is None:
        return jsonify({"error": "version not found"}), 404
    _, current_sha = _safe_get_file(gitea, script.gitea_path)
    new_sha = gitea.create_or_update_file(
        path=script.gitea_path,
        content=content,
        message=f"Restore {script.gitea_path} to {ref[:8]} via ScriptWatch UI",
        sha=current_sha,
    )
    script.gitea_sha = new_sha
    db.session.commit()
    return jsonify(script.to_dict())


@scripts_bp.put("/<int:script_id>")
def update_script(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True)
    if "description" in data:
        script.description = data["description"]
    if "timeout_seconds" in data:
        script.timeout_seconds = data["timeout_seconds"]
    if "enabled" in data:
        script.enabled = data["enabled"]
    if "manual_trigger" in data:
        script.manual_trigger = data["manual_trigger"]
    if "notify_on_failure" in data:
        script.notify_on_failure = data["notify_on_failure"]
    if "notify_on_success" in data:
        script.notify_on_success = data["notify_on_success"]
    if "success_notification_message" in data:
        script.success_notification_message = (data.get("success_notification_message") or "").strip() or None
    if "parameters" in data:
        script.parameters = data["parameters"] or []

    if "server_ids" in data:
        server_schedules = data.get("server_schedules") or {}
        server_ids = data["server_ids"] or []
        server_ids.extend(_server_ids_from_tags(data.get("server_tags") or []))
        script.server_assignments = _build_server_assignments(sorted(set(int(sid) for sid in server_ids)), server_schedules)

    gitea = get_gitea_client()
    new_name = (data.get("name") or "").strip()
    is_rename = bool(new_name and new_name != script.name)

    if is_rename:
        try:
            new_path = _make_gitea_path(new_name)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        current_content, old_sha = _safe_get_file(gitea, script.gitea_path)
        content_to_write = data.get("content") if "content" in data else (current_content or "")
        new_sha = gitea.rename_file(
            old_path=script.gitea_path,
            new_path=new_path,
            content=content_to_write,
            old_sha=old_sha,
            message=f"Rename {script.gitea_path} to {new_path} via ScriptWatch UI",
        )
        script.name = new_name
        script.gitea_path = new_path
        script.gitea_sha = new_sha
    elif "content" in data:
        _, current_sha = _safe_get_file(gitea, script.gitea_path)
        sha = gitea.create_or_update_file(
            path=script.gitea_path,
            content=data["content"],
            message=f"Update {script.gitea_path} via ScriptWatch UI",
            sha=current_sha,
        )
        script.gitea_sha = sha

    db.session.commit()
    if not current_app.config.get("TESTING"):
        from api.extensions import scheduler
        from api.services.scheduler_tasks import register_script_schedules, unregister_script_schedules
        if script.enabled:
            register_script_schedules(scheduler, script, current_app._get_current_object())
        else:
            unregister_script_schedules(scheduler, script.id)
    return jsonify(script.to_dict())


@scripts_bp.post("/validate")
def validate_script():
    data = request.get_json(force=True) or {}
    try:
        return jsonify(_validate_shell(data.get("content") or ""))
    except subprocess.TimeoutExpired:
        return jsonify({"valid": False, "output": "Validation timed out.", "warnings": []}), 400


@scripts_bp.get("/<int:script_id>/server-status")
def script_server_status(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404

    rows = []
    for assignment in script.server_assignments:
        server = db.session.get(Server, assignment.server_id, populate_existing=True)
        if not server or server.pending_uninstall:
            continue
        last_job = (
            Job.query
            .filter(Job.script_id == script.id, Job.server_id == server.id)
            .order_by(Job.created_at.desc())
            .first()
        )
        last_success = (
            Job.query
            .filter(Job.script_id == script.id, Job.server_id == server.id, Job.status == "success")
            .order_by(Job.completed_at.desc(), Job.created_at.desc())
            .first()
        )
        last_failure = (
            Job.query
            .filter(Job.script_id == script.id, Job.server_id == server.id, Job.status.in_(["failure", "timeout"]))
            .order_by(Job.completed_at.desc(), Job.created_at.desc())
            .first()
        )
        missed = (
            MissedRun.query
            .filter(
                MissedRun.script_id == script.id,
                MissedRun.server_id == server.id,
                MissedRun.dismissed == False,  # noqa: E712
            )
            .order_by(MissedRun.expected_at.desc())
            .first()
        )
        rows.append({
            "server": server.to_dict(),
            "schedule": assignment.schedule,
            "last_job": last_job.to_dict() if last_job else None,
            "last_success": last_success.to_dict() if last_success else None,
            "last_failure": last_failure.to_dict() if last_failure else None,
            "missed_run": missed.to_dict() if missed else None,
        })
    return jsonify(rows)


@scripts_bp.delete("/<int:script_id>")
def delete_script(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404

    gitea = get_gitea_client()
    _, sha = _safe_get_file(gitea, script.gitea_path)
    if sha:
        gitea.delete_file(
            path=script.gitea_path,
            sha=sha,
            message=f"Remove {script.gitea_path} via ScriptWatch UI",
        )

    if not current_app.config.get("TESTING"):
        from api.extensions import scheduler
        from api.services.scheduler_tasks import unregister_script_schedules
        unregister_script_schedules(scheduler, script_id)
    db.session.delete(script)
    db.session.commit()
    return jsonify({"deleted": script_id})


@scripts_bp.post("/<int:script_id>/trigger")
def trigger_script(script_id):
    script = db.session.get(Script, script_id)
    if not script:
        return jsonify({"error": "not found"}), 404
    if not script.manual_trigger:
        return jsonify({"error": "manual trigger disabled for this script"}), 403

    data = request.get_json(force=True) or {}
    server_ids = data.get("server_ids") or []
    server_ids.extend(_server_ids_from_tags(data.get("server_tags") or []))
    assigned_ids = {sa.server_id for sa in script.server_assignments}
    server_ids = [sid for sid in sorted(set(int(sid) for sid in server_ids)) if sid in assigned_ids]
    params = data.get("parameters") or {}

    jobs = []
    content_snapshot, snapshot_sha = _current_script_snapshot(script)
    for sid in server_ids:
        job = Job(
            script_id=script_id,
            server_id=int(sid),
            triggered_by="manual",
            gitea_sha=snapshot_sha or script.gitea_sha,
            script_content=content_snapshot,
            parameters=params,
        )
        db.session.add(job)
        jobs.append(job)
    db.session.commit()
    return jsonify([j.to_dict() for j in jobs]), 201
