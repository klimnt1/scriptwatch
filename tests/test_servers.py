import json
from datetime import datetime
from api.models import Server, Job
from api.extensions import db


def _auth_headers(app):
    return {"Authorization": f"Bearer {app.config['AGENT_TOKEN']}"}


def test_list_servers_empty(client):
    resp = client.get("/api/servers/")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_register_requires_agent_token(client):
    resp = client.post("/api/servers/register", json={"name": "plexusprime"})
    assert resp.status_code == 401


def test_register_new_server(client, app):
    resp = client.post("/api/servers/register", json={
        "name": "plexusprime",
        "hostname": "192.168.1.10",
        "agent_version": "1.0.0",
    }, headers=_auth_headers(app))
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "plexusprime"
    assert data["hostname"] == "192.168.1.10"


def test_register_existing_server_updates(client, app):
    with app.app_context():
        s = Server(name="dns-alpha", hostname="192.168.1.50")
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/register", json={
        "name": "dns-alpha",
        "hostname": "192.168.1.51",
        "agent_version": "1.1.0",
    }, headers=_auth_headers(app))
    assert resp.status_code == 200
    assert resp.get_json()["hostname"] == "192.168.1.51"
    assert resp.get_json()["agent_version"] == "1.1.0"


def test_heartbeat_requires_agent_token(client, app):
    with app.app_context():
        s = Server(name="auth-heartbeat")
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/auth-heartbeat/heartbeat")
    assert resp.status_code == 401


def test_heartbeat_updates_timestamp(client, app):
    with app.app_context():
        s = Server(name="backups-tower")
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/backups-tower/heartbeat", headers=_auth_headers(app))
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["last_heartbeat"] is not None


def test_heartbeat_unknown_server_returns_404(client, app):
    resp = client.post("/api/servers/nonexistent/heartbeat", headers=_auth_headers(app))
    assert resp.status_code == 404


def test_pending_uninstall_server_is_hidden_and_rejects_agent_recreate(client, app):
    with app.app_context():
        s = Server(
            name="debian-vmtest",
            hostname="debian-test",
            last_heartbeat=datetime.utcnow(),
        )
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/debian-vmtest/uninstall")
    assert resp.status_code == 200
    assert resp.get_json()["uninstall_queued"] is True

    servers = client.get("/api/servers/").get_json()
    assert [s["name"] for s in servers] == []

    heartbeat = client.post("/api/servers/debian-vmtest/heartbeat", headers=_auth_headers(app))
    assert heartbeat.status_code == 410

    register = client.post(
        "/api/servers/register",
        json={"name": "debian-vmtest", "hostname": "debian-test"},
        headers=_auth_headers(app),
    )
    assert register.status_code == 410

    with app.app_context():
        server = Server.query.filter_by(name="debian-vmtest").first()
        assert server is not None
        assert server.pending_uninstall is True
        job = Job.query.filter_by(server_id=server.id, triggered_by="uninstall").first()
        assert job is not None
        assert job.status == "pending"
        assert "systemd-run" in job.script_content
        assert "scriptwatch-agent-uninstall" in job.script_content
        assert "systemctl stop scriptwatch-agent" in job.script_content
        assert "/api/jobs/$SCRIPTWATCH_JOB_ID/output" in job.script_content
        assert "Uninstall complete. Removed service, environment file, and agent directory." in job.script_content


def test_list_servers_shows_registered(client, app):
    client.post(
        "/api/servers/register",
        json={"name": "dns-beta", "hostname": "192.168.1.60"},
        headers=_auth_headers(app),
    )
    resp = client.get("/api/servers/")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.get_json()]
    assert "dns-beta" in names


def test_server_tags_default_empty(app):
    with app.app_context():
        s = Server(name="tag-test-server")
        db.session.add(s)
        db.session.commit()
        d = s.to_dict()
        assert d["tags"] == []


def test_update_server_tags(client, app):
    with app.app_context():
        s = Server(name="tag-srv")
        db.session.add(s)
        db.session.commit()

    resp = client.patch("/api/servers/tag-srv/tags", json={"tags": ["dns", "production"]})
    assert resp.status_code == 200
    assert sorted(resp.get_json()["tags"]) == ["dns", "production"]


def test_update_server_tags_not_found(client, app):
    resp = client.patch("/api/servers/nonexistent/tags", json={"tags": ["x"]})
    assert resp.status_code == 404


def test_update_server_tags_clears(client, app):
    with app.app_context():
        s = Server(name="tag-clear-srv", tags=["old"])
        db.session.add(s)
        db.session.commit()

    resp = client.patch("/api/servers/tag-clear-srv/tags", json={"tags": []})
    assert resp.status_code == 200
    assert resp.get_json()["tags"] == []


def test_heartbeat_saves_agent_hash(client, app):
    with app.app_context():
        s = Server(name="hash-heartbeat-srv")
        db.session.add(s)
        db.session.commit()

    resp = client.post(
        "/api/servers/hash-heartbeat-srv/heartbeat",
        json={"agent_hash": "deadbeef1234"},
        headers=_auth_headers(app),
    )
    assert resp.status_code == 200
    assert resp.get_json()["agent_hash"] == "deadbeef1234"

def test_heartbeat_without_hash_leaves_hash_null(client, app):
    with app.app_context():
        s = Server(name="no-hash-srv")
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/no-hash-srv/heartbeat", headers=_auth_headers(app))
    assert resp.status_code == 200
    assert resp.get_json()["agent_hash"] is None


def test_update_creates_system_job(client, app):
    with app.app_context():
        s = Server(name="update-srv")
        db.session.add(s)
        db.session.commit()

    resp = client.post("/api/servers/update-srv/update")
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["triggered_by"] == "system"
    assert data["status"] == "pending"

    with app.app_context():
        job = Job.query.filter_by(server_id=Server.query.filter_by(name="update-srv").first().id).first()
        assert job is not None
        assert job.script_content is not None
        assert "scriptwatch-agent" in job.script_content


def test_update_unknown_server_returns_404(client):
    resp = client.post("/api/servers/ghost/update")
    assert resp.status_code == 404


def test_bulk_update_agents_by_tag(client, app):
    with app.app_context():
        db.session.add(Server(name="dns-update", tags=["dns"], agent_hash="old"))
        db.session.add(Server(name="db-update", tags=["db"], agent_hash="old"))
        db.session.commit()

    resp = client.post("/api/servers/update", json={"tags": ["dns"]})
    assert resp.status_code == 201
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["server_name"] == "dns-update"


def test_bulk_update_agents_only_outdated(client, app):
    with app.app_context():
        db.session.add(Server(name="fresh-agent", agent_hash="latest"))
        db.session.add(Server(name="old-agent", agent_hash="old"))
        db.session.commit()

    resp = client.post("/api/servers/update", json={"only_outdated": True, "latest_hash": "latest"})
    assert resp.status_code == 201
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["server_name"] == "old-agent"
