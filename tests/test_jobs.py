from datetime import datetime, timedelta
from unittest.mock import patch
from api.models import Server, Script, Job, ScriptServer
from api.extensions import db


def _auth_headers(app):
    return {"Authorization": f"Bearer {app.config['AGENT_TOKEN']}"}


def make_script(app, server_name="plexusprime"):
    with app.app_context():
        s = Server(name=server_name)
        db.session.add(s)
        db.session.flush()
        sc = Script(name="test-script", gitea_path="scripts/test-script.sh", gitea_sha="sha1")
        sc.servers.append(s)
        db.session.add(sc)
        db.session.commit()
        return sc.id, s.id


def test_pending_jobs_requires_auth(client):
    resp = client.get("/api/jobs/pending/plexusprime")
    assert resp.status_code == 401


def test_pending_jobs_returns_empty(client, app):
    resp = client.get("/api/jobs/pending/plexusprime", headers=_auth_headers(app))
    assert resp.status_code == 200
    assert resp.get_json() == []


@patch("api.routes.jobs.get_gitea_client")
def test_pending_jobs_returns_job_with_content(mock_gitea, client, app):
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho run", "sha1")
    script_id, server_id = make_script(app)
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="pending", gitea_sha="sha1")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.get("/api/jobs/pending/plexusprime", headers=_auth_headers(app))
    assert resp.status_code == 200
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["script_content"] == "#!/bin/bash\necho run"
    assert jobs[0]["timeout_seconds"] == 3600


def test_start_job(client, app):
    script_id, server_id = make_script(app, "tower")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="pending")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.put(f"/api/jobs/{job_id}/start", headers=_auth_headers(app))
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "running"
    assert resp.get_json()["started_at"] is not None


def test_complete_job_success(client, app):
    script_id, server_id = make_script(app, "alpha")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="running", started_at=datetime.utcnow())
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.put(f"/api/jobs/{job_id}/complete", json={
        "status": "success",
        "exit_code": 0,
        "output": "Backup complete.\n3 files written.",
    }, headers=_auth_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["exit_code"] == 0


def test_complete_job_failure(client, app):
    script_id, server_id = make_script(app, "beta")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="running", started_at=datetime.utcnow())
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.put(f"/api/jobs/{job_id}/complete", json={
        "status": "failure",
        "exit_code": 1,
        "output": "pg_dump: error: connection failed",
    }, headers=_auth_headers(app))
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "failure"


def test_complete_uninstall_marks_server_pending_until_offline_cleanup(client, app):
    with app.app_context():
        server = Server(
            name="uninstall-finish-srv",
            last_heartbeat=datetime.utcnow(),
            pending_uninstall=True,
        )
        db.session.add(server)
        db.session.flush()
        job = Job(
            script_id=None,
            server_id=server.id,
            status="running",
            triggered_by="uninstall",
            started_at=datetime.utcnow(),
            script_content="#!/bin/bash\necho uninstall",
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.put(f"/api/jobs/{job_id}/complete", json={
        "status": "success",
        "exit_code": 0,
        "output": "Uninstall scheduled.",
    }, headers=_auth_headers(app))
    assert resp.status_code == 200

    with app.app_context():
        server = Server.query.filter_by(name="uninstall-finish-srv").first()
        assert server is not None
        assert server.pending_uninstall is True
        server.last_heartbeat = datetime.utcnow() - timedelta(minutes=6)
        db.session.commit()

    stats = client.get("/api/jobs/stats")
    assert stats.status_code == 200

    with app.app_context():
        assert Server.query.filter_by(name="uninstall-finish-srv").first() is None
        job = db.session.get(Job, job_id)
        assert job is not None
        assert job.server_id is None
        assert job.status == "success"
        assert "Server record removed after uninstall cleanup: uninstall-finish-srv" in job.output


def test_get_job_includes_output(client, app):
    script_id, server_id = make_script(app, "gamma")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="success", output="done", exit_code=0)
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.get_json()["output"] == "done"


def test_list_jobs(client, app):
    script_id, server_id = make_script(app, "delta")
    with app.app_context():
        for status in ("success", "failure", "pending"):
            db.session.add(Job(script_id=script_id, server_id=server_id, status=status))
        db.session.commit()

    resp = client.get("/api/jobs/")
    assert resp.status_code == 200
    assert len(resp.get_json()["jobs"]) == 3


def test_list_jobs_filters(client, app):
    script_id, server_id = make_script(app, "filter-srv")
    with app.app_context():
        db.session.add(Job(script_id=script_id, server_id=server_id, status="success", triggered_by="manual"))
        db.session.add(Job(script_id=script_id, server_id=server_id, status="failure", triggered_by="schedule"))
        db.session.commit()

    resp = client.get(f"/api/jobs/?status=failure&server_id={server_id}&script_id={script_id}&triggered_by=schedule")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["jobs"][0]["status"] == "failure"
    assert data["jobs"][0]["triggered_by"] == "schedule"


def test_active_failures_lists_only_undismissed_failures(client, app):
    script_id, server_id = make_script(app, "fail-list")
    with app.app_context():
        db.session.add(Job(script_id=script_id, server_id=server_id, status="success"))
        db.session.add(Job(script_id=script_id, server_id=server_id, status="failure"))
        db.session.add(Job(script_id=script_id, server_id=server_id, status="timeout"))
        db.session.add(Job(script_id=script_id, server_id=server_id, status="failure", dismissed=True))
        db.session.commit()

    resp = client.get("/api/jobs/failures")
    assert resp.status_code == 200
    statuses = [j["status"] for j in resp.get_json()]
    assert statuses.count("failure") == 1
    assert statuses.count("timeout") == 1


def test_dismiss_failed_job(client, app):
    script_id, server_id = make_script(app, "fail-dismiss")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="failure")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/dismiss")
    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] is True

    failures = client.get("/api/jobs/failures").get_json()
    assert failures == []


def test_dismiss_success_job_returns_400(client, app):
    script_id, server_id = make_script(app, "success-dismiss")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="success")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/dismiss")
    assert resp.status_code == 400


def test_append_job_output_requires_agent_token(client, app):
    script_id, server_id = make_script(app, "append-auth-srv")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="success", output="start")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/output", json={"output": "more"})
    assert resp.status_code == 401


def test_append_job_output_preserves_existing_log(client, app):
    script_id, server_id = make_script(app, "append-srv")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="success", output="start")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(
        f"/api/jobs/{job_id}/output",
        json={"output": "Uninstall complete."},
        headers=_auth_headers(app),
    )
    assert resp.status_code == 200
    assert resp.get_json()["output"] == "start\nUninstall complete."


def test_dismiss_anomalous_success_job(client, app):
    script_id, server_id = make_script(app, "anomaly-dismiss")
    with app.app_context():
        job = Job(
            script_id=script_id,
            server_id=server_id,
            status="success",
            anomaly_detected=True,
            anomaly_reason="Runtime 3600s is unusually high.",
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/dismiss")
    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] is True

    anomalies = client.get("/api/jobs/anomalies").get_json()
    assert anomalies == []


@patch("api.routes.jobs.get_gitea_client")
def test_pending_jobs_includes_parameters(mock_gitea, client, app):
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho $DAYS", "sha1")
    with app.app_context():
        s = Server(name="param-agent")
        db.session.add(s)
        db.session.flush()
        sc = Script(
            name="param-run",
            gitea_path="scripts/param-run.sh",
            gitea_sha="sha1",
            parameters=[{"name": "DAYS", "default": "7", "description": ""}],
        )
        db.session.add(sc)
        db.session.flush()
        job = Job(
            script_id=sc.id,
            server_id=s.id,
            status="pending",
            gitea_sha="sha1",
            parameters={"DAYS": "14"},
        )
        db.session.add(job)
        db.session.commit()

    resp = client.get("/api/jobs/pending/param-agent", headers=_auth_headers(app))
    assert resp.status_code == 200
    jobs = resp.get_json()
    assert jobs[0]["parameters"] == {"DAYS": "14"}


def test_pending_jobs_returns_inline_script(client, app):
    with app.app_context():
        s = Server(name="inline-agent")
        db.session.add(s)
        db.session.flush()
        job = Job(
            script_id=None,
            server_id=s.id,
            status="pending",
            triggered_by="system",
            script_content="#!/bin/bash\necho update",
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.get("/api/jobs/pending/inline-agent", headers=_auth_headers(app))
    assert resp.status_code == 200
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["script_content"] == "#!/bin/bash\necho update"
    assert jobs[0]["timeout_seconds"] == 300

def test_retry_system_job_returns_400(client, app):
    with app.app_context():
        s = Server(name="retry-sys-srv")
        db.session.add(s)
        db.session.flush()
        job = Job(
            script_id=None,
            server_id=s.id,
            status="failure",
            triggered_by="system",
            script_content="#!/bin/bash\necho hi",
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/retry")
    assert resp.status_code == 400


def test_replay_failed_job_preserves_parameters_and_lineage(client, app):
    script_id, server_id = make_script(app, "replay-srv")
    with app.app_context():
        job = Job(
            script_id=script_id,
            server_id=server_id,
            status="failure",
            gitea_sha="oldsha",
            parameters={"TARGET": "/backup"},
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/replay", json={"mode": "current"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["triggered_by"] == "replay"
    assert data["parameters"] == {"TARGET": "/backup"}
    assert data["replayed_from_job_id"] == job_id
    assert data["replay_mode"] == "current"


def test_replay_successful_job_runs_again(client, app):
    script_id, server_id = make_script(app, "run-again-srv")
    with app.app_context():
        job = Job(
            script_id=script_id,
            server_id=server_id,
            status="success",
            gitea_sha="sha1",
            parameters={"MODE": "normal"},
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/replay", json={"mode": "current"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["triggered_by"] == "replay"
    assert data["parameters"] == {"MODE": "normal"}
    assert data["replayed_from_job_id"] == job_id


def test_replay_running_job_returns_400(client, app):
    script_id, server_id = make_script(app, "running-replay-srv")
    with app.app_context():
        job = Job(script_id=script_id, server_id=server_id, status="running")
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/replay", json={"mode": "current"})
    assert resp.status_code == 400
    assert "completed" in resp.get_json()["error"]


def test_exact_replay_uses_captured_script_content(client, app):
    script_id, server_id = make_script(app, "exact-replay-srv")
    with app.app_context():
        job = Job(
            script_id=script_id,
            server_id=server_id,
            status="timeout",
            gitea_sha="oldsha",
            script_content="#!/bin/bash\necho old",
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.post(f"/api/jobs/{job_id}/replay", json={"mode": "exact"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["script_content"] == "#!/bin/bash\necho old"
    assert data["gitea_sha"] == "oldsha"
    assert data["replay_mode"] == "exact"


def test_complete_job_flags_runtime_anomaly(client, app):
    script_id, server_id = make_script(app, "anomaly-srv")
    base = datetime.utcnow() - timedelta(hours=2)
    with app.app_context():
        for i in range(3):
            db.session.add(Job(
                script_id=script_id,
                server_id=server_id,
                status="success",
                started_at=base + timedelta(minutes=i * 10),
                completed_at=base + timedelta(minutes=i * 10, seconds=60),
                duration_seconds=60,
            ))
        job = Job(
            script_id=script_id,
            server_id=server_id,
            status="running",
            started_at=datetime.utcnow() - timedelta(hours=2),
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    resp = client.put(f"/api/jobs/{job_id}/complete", json={
        "status": "success",
        "exit_code": 0,
        "output": "slow but successful",
    }, headers=_auth_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["duration_seconds"] >= 7200
    assert data["anomaly_detected"] is True
    assert "recent median" in data["anomaly_reason"]

    anomalies = client.get("/api/jobs/anomalies")
    assert anomalies.status_code == 200
    assert anomalies.get_json()[0]["id"] == job_id


def test_trigger_stores_parameters(client, app):
    with app.app_context():
        s = Server(name="trig-param-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(
            name="trig-param",
            gitea_path="scripts/trig-param.sh",
            gitea_sha="sha1",
            parameters=[{"name": "MODE", "default": "fast", "description": ""}],
        )
        sc.server_assignments = [ScriptServer(server_id=s.id)]
        db.session.add(sc)
        db.session.commit()
        script_id, server_id = sc.id, s.id

    resp = client.post(f"/api/scripts/{script_id}/trigger", json={
        "server_ids": [server_id],
        "parameters": {"MODE": "slow"},
    })
    assert resp.status_code == 201
    jobs = resp.get_json()
    assert jobs[0]["parameters"] == {"MODE": "slow"}
