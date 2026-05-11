from datetime import datetime
from sqlalchemy.ext.associationproxy import association_proxy
from .extensions import db


class Tag(db.Model):
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScriptServer(db.Model):
    __tablename__ = "script_servers"

    script_id = db.Column(db.Integer, db.ForeignKey("scripts.id", ondelete="CASCADE"), primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id", ondelete="CASCADE"), primary_key=True)
    schedule = db.Column(db.String(100))

    server = db.relationship("Server")
    script = db.relationship("Script", back_populates="server_assignments")


class Server(db.Model):
    __tablename__ = "servers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    hostname = db.Column(db.String(255))
    last_heartbeat = db.Column(db.DateTime)
    agent_version = db.Column(db.String(50))
    agent_hash = db.Column(db.String(64))
    pending_uninstall = db.Column(db.Boolean, nullable=False, default=False)
    tags = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_online(self):
        if not self.last_heartbeat:
            return False
        return (datetime.utcnow() - self.last_heartbeat).total_seconds() < 300

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "is_online": self.is_online,
            "agent_version": self.agent_version,
            "agent_hash": self.agent_hash,
            "pending_uninstall": self.pending_uninstall,
            "tags": self.tags or [],
            "created_at": self.created_at.isoformat(),
        }


class Script(db.Model):
    __tablename__ = "scripts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    gitea_path = db.Column(db.String(500))
    gitea_sha = db.Column(db.String(40))
    timeout_seconds = db.Column(db.Integer, default=3600)
    enabled = db.Column(db.Boolean, default=True)
    manual_trigger = db.Column(db.Boolean, default=True)
    notify_on_failure = db.Column(db.Boolean, default=True)
    notify_on_success = db.Column(db.Boolean, default=False)
    success_notification_message = db.Column(db.Text)
    parameters = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    server_assignments = db.relationship("ScriptServer", cascade="all, delete-orphan", back_populates="script")
    jobs = db.relationship("Job", back_populates="script", cascade="all, delete-orphan")
    servers = association_proxy("server_assignments", "server", creator=lambda server: ScriptServer(server=server))

    def __init__(self, **kwargs):
        # Legacy compatibility: schedules now live on ScriptServer assignments.
        kwargs.pop("schedule", None)
        super().__init__(**kwargs)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "server_ids": [sa.server_id for sa in self.server_assignments],
            "server_names": [sa.server.name for sa in self.server_assignments],
            "server_schedules": {sa.server_id: sa.schedule for sa in self.server_assignments},
            "gitea_path": self.gitea_path,
            "gitea_sha": self.gitea_sha,
            "timeout_seconds": self.timeout_seconds,
            "enabled": self.enabled,
            "manual_trigger": self.manual_trigger,
            "notify_on_failure": self.notify_on_failure,
            "notify_on_success": self.notify_on_success,
            "success_notification_message": self.success_notification_message,
            "parameters": self.parameters or [],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    script_id = db.Column(db.Integer, db.ForeignKey("scripts.id"), nullable=True)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id", ondelete="CASCADE"), nullable=True)
    status = db.Column(db.String(50), default="pending")
    triggered_by = db.Column(db.String(100), default="manual")
    gitea_sha = db.Column(db.String(40))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    exit_code = db.Column(db.Integer)
    output = db.Column(db.Text)
    script_content = db.Column(db.Text)
    parameters = db.Column(db.JSON, default=dict)
    dismissed = db.Column(db.Boolean, nullable=False, default=False)
    duration_seconds = db.Column(db.Integer)
    anomaly_detected = db.Column(db.Boolean, nullable=False, default=False)
    anomaly_reason = db.Column(db.Text)
    replayed_from_job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=True)
    replay_mode = db.Column(db.String(20))

    script = db.relationship("Script", back_populates="jobs")
    server = db.relationship("Server")
    replayed_from = db.relationship("Job", remote_side=[id])

    def to_dict(self, include_output=False):
        d = {
            "id": self.id,
            "script_id": self.script_id,
            "server_id": self.server_id,
            "script_name": self.script.name if self.script else {"system": "Update Agent", "uninstall": "Uninstall Agent"}.get(self.triggered_by),
            "server_name": self.server.name if self.server else None,
            "status": self.status,
            "triggered_by": self.triggered_by,
            "gitea_sha": self.gitea_sha,
            "script_content": self.script_content,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "exit_code": self.exit_code,
            "parameters": self.parameters or {},
            "dismissed": self.dismissed,
            "duration_seconds": self.duration_seconds,
            "anomaly_detected": self.anomaly_detected,
            "anomaly_reason": self.anomaly_reason,
            "replayed_from_job_id": self.replayed_from_job_id,
            "replay_mode": self.replay_mode,
        }
        if include_output:
            d["output"] = self.output
        return d


class MissedRun(db.Model):
    __tablename__ = "missed_runs"

    id = db.Column(db.Integer, primary_key=True)
    script_id = db.Column(db.Integer, db.ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    server_id = db.Column(db.Integer, db.ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    expected_at = db.Column(db.DateTime, nullable=False)
    alerted_at = db.Column(db.DateTime)
    dismissed = db.Column(db.Boolean, nullable=False, default=False)

    script = db.relationship("Script")
    server = db.relationship("Server")

    __table_args__ = (
        db.UniqueConstraint("script_id", "server_id", "expected_at", name="uq_missed_run"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "script_id": self.script_id,
            "script_name": self.script.name if self.script else None,
            "server_id": self.server_id,
            "server_name": self.server.name if self.server else None,
            "expected_at": self.expected_at.isoformat(),
            "alerted_at": self.alerted_at.isoformat() if self.alerted_at else None,
        }
