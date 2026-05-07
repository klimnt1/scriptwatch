import hmac
from functools import wraps
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from api.extensions import db
from api.models import Server, Job

servers_bp = Blueprint("servers", __name__)


def require_agent_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        expected = f"Bearer {current_app.config['AGENT_TOKEN']}"
        if not hmac.compare_digest(auth, expected):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@servers_bp.get("/")
def list_servers():
    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    return jsonify([s.to_dict() for s in servers])


@servers_bp.post("/register")
@require_agent_token
def register_server():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    server = Server.query.filter_by(name=name).first()
    if server:
        if server.pending_uninstall:
            return jsonify({"error": "server is pending uninstall"}), 410
        server.hostname = data.get("hostname", server.hostname)
        server.agent_version = data.get("agent_version", server.agent_version)
        server.last_heartbeat = datetime.utcnow()
        db.session.commit()
        return jsonify(server.to_dict()), 200

    server = Server(
        name=name,
        hostname=data.get("hostname"),
        agent_version=data.get("agent_version"),
        last_heartbeat=datetime.utcnow(),
    )
    db.session.add(server)
    db.session.commit()
    return jsonify(server.to_dict()), 201


@servers_bp.delete("/<string:name>")
def delete_server(name):
    server = Server.query.filter_by(name=name).first_or_404()
    Job.query.filter_by(server_id=server.id).delete()
    db.session.delete(server)
    db.session.commit()
    return "", 204


@servers_bp.post("/<string:name>/uninstall")
def uninstall_server(name):
    server = Server.query.filter_by(name=name).first_or_404()
    if server.pending_uninstall:
        existing = Job.query.filter(
            Job.server_id == server.id,
            Job.triggered_by == "uninstall",
            Job.status.in_(["pending", "running", "cancelling"]),
        ).first()
        return jsonify({"uninstall_queued": True, "job_id": existing.id if existing else None}), 200
    if server.is_online:
        server.pending_uninstall = True
        # Cancel any running jobs so the agent unblocks immediately
        running = Job.query.filter(
            Job.server_id == server.id,
            Job.status == "running",
            Job.triggered_by != "uninstall",
        ).all()
        for j in running:
            j.status = "cancelling"
        # Drop pending jobs — they haven't started yet
        Job.query.filter(Job.server_id == server.id, Job.status == "pending").delete()
        job = Job(
            script_id=None,
            server_id=server.id,
            triggered_by="uninstall",
            script_content=_UNINSTALL_SCRIPT,
        )
        db.session.add(job)
        db.session.commit()
        return jsonify({"uninstall_queued": True, "job_id": job.id}), 200
    Job.query.filter_by(server_id=server.id).delete()
    db.session.delete(server)
    db.session.commit()
    return jsonify({"uninstall_queued": False}), 200


@servers_bp.post("/<string:name>/heartbeat")
@require_agent_token
def heartbeat(name):
    server = Server.query.filter_by(name=name).first()
    if not server:
        return jsonify({"error": "not found"}), 404
    if server.pending_uninstall:
        return jsonify({"error": "server is pending uninstall"}), 410
    data = request.get_json(silent=True) or {}
    server.last_heartbeat = datetime.utcnow()
    if "agent_hash" in data:
        server.agent_hash = data["agent_hash"]
    db.session.commit()
    return jsonify(server.to_dict()), 200


@servers_bp.patch("/<string:name>/tags")
def update_tags(name):
    server = Server.query.filter_by(name=name).first()
    if not server:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    tags = [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()]
    server.tags = sorted(set(tags))
    db.session.commit()
    return jsonify(server.to_dict())


_UNINSTALL_SCRIPT = """\
#!/bin/bash
CLEANUP=/tmp/scriptwatch-agent-uninstall.sh
cat > "$CLEANUP" <<'SCRIPTWATCH_UNINSTALL'
#!/bin/bash
set +e

append_log() {
  if [ -n "${SCRIPTWATCH_API_URL:-}" ] && [ -n "${SCRIPTWATCH_AGENT_TOKEN:-}" ] && [ -n "${SCRIPTWATCH_JOB_ID:-}" ] && command -v curl >/dev/null 2>&1; then
    curl -fsS -X POST \\
      -H "Authorization: Bearer $SCRIPTWATCH_AGENT_TOKEN" \\
      -H "Content-Type: application/json" \\
      --data "{\"output\":\"$1\"}" \\
      "$SCRIPTWATCH_API_URL/api/jobs/$SCRIPTWATCH_JOB_ID/output" >/dev/null 2>&1 || true
  fi
}

append_log "Cleanup started."
systemctl disable scriptwatch-agent
systemctl stop scriptwatch-agent
rm -f /etc/systemd/system/scriptwatch-agent.service
systemctl daemon-reload
rm -f /etc/scriptwatch.env
rm -rf /opt/scriptwatch-agent
append_log "Uninstall complete. Removed service, environment file, and agent directory."
rm -f /tmp/scriptwatch-agent-uninstall.sh
SCRIPTWATCH_UNINSTALL
chmod 700 "$CLEANUP"

if command -v systemd-run >/dev/null 2>&1; then
  UNIT="scriptwatch-agent-uninstall-$(date +%s)"
  systemd-run \\
    --unit="$UNIT" \\
    --description="Uninstall ScriptWatch Agent" \\
    --on-active=30s \\
    --setenv=SCRIPTWATCH_API_URL="$SCRIPTWATCH_API_URL" \\
    --setenv=SCRIPTWATCH_AGENT_TOKEN="$SCRIPTWATCH_AGENT_TOKEN" \\
    --setenv=SCRIPTWATCH_JOB_ID="$SCRIPTWATCH_JOB_ID" \\
    /bin/bash "$CLEANUP" >/dev/null
else
  (sleep 30; /bin/bash "$CLEANUP") </dev/null >/dev/null 2>&1 &
  disown
fi
echo "Uninstall scheduled."
"""

_UPDATE_SCRIPT = """\
#!/bin/bash
set -e
TMPFILE=$(mktemp /tmp/sw_agent_XXXXXX.py)
trap "rm -f $TMPFILE" EXIT
curl -fsSL -H "Authorization: Bearer $SCRIPTWATCH_AGENT_TOKEN" \\
  "$SCRIPTWATCH_API_URL/api/agent/download" -o "$TMPFILE"
python3 -c "import ast; ast.parse(open('$TMPFILE').read())"
cp "$TMPFILE" /opt/scriptwatch-agent/agent.py
nohup bash -c "sleep 5 && systemctl restart scriptwatch-agent" >/dev/null 2>&1 &
echo "Update applied. Restarting in 5 seconds..."
"""


@servers_bp.post("/<string:name>/update")
def update_agent(name):
    server = Server.query.filter_by(name=name).first()
    if not server:
        return jsonify({"error": "not found"}), 404
    if server.pending_uninstall:
        return jsonify({"error": "server is pending uninstall"}), 410
    job = Job(
        script_id=None,
        server_id=server.id,
        triggered_by="system",
        script_content=_UPDATE_SCRIPT,
    )
    db.session.add(job)
    db.session.commit()
    return jsonify(job.to_dict()), 201


@servers_bp.post("/update")
def update_agents():
    data = request.get_json(force=True) or {}
    server_ids = {int(sid) for sid in (data.get("server_ids") or [])}
    tags = {str(t).strip() for t in (data.get("tags") or []) if str(t).strip()}
    only_outdated = bool(data.get("only_outdated", False))
    latest_hash = data.get("latest_hash")

    servers = Server.query.filter(Server.pending_uninstall == False).order_by(Server.name).all()  # noqa: E712
    selected = []
    for server in servers:
        selected_by_id = not server_ids and not tags
        selected_by_id = selected_by_id or server.id in server_ids
        selected_by_tag = bool(tags.intersection(set(server.tags or [])))
        if not (selected_by_id or selected_by_tag):
            continue
        if only_outdated and latest_hash and server.agent_hash == latest_hash:
            continue
        selected.append(server)

    jobs = []
    for server in selected:
        job = Job(
            script_id=None,
            server_id=server.id,
            triggered_by="system",
            script_content=_UPDATE_SCRIPT,
        )
        db.session.add(job)
        jobs.append(job)
    db.session.commit()
    return jsonify([job.to_dict() for job in jobs]), 201
