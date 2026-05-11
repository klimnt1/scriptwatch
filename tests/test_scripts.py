from unittest.mock import patch
from api.models import Server, Script, Job, MissedRun, ScriptServer
from api.extensions import db


def make_servers(app, names=("plexusprime",)):
    with app.app_context():
        ids = []
        for name in names:
            s = Server(name=name, hostname="192.168.1.10")
            db.session.add(s)
            db.session.flush()
            ids.append(s.id)
        db.session.commit()
        return ids


@patch("api.routes.scripts.get_gitea_client")
def test_create_script(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha123"
    [server_id] = make_servers(app)
    resp = client.post("/api/scripts/", json={
        "name": "Postgres Dump",
        "description": "Daily pg_dump",
        "server_ids": [server_id],
        "content": "#!/bin/bash\npg_dump mydb > /backup/mydb.sql",
        "schedule": "0 2 * * *",
        "timeout_seconds": 1800,
        "notify_on_success": True,
        "success_notification_message": "Postgres backup finished on {server}",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "Postgres Dump"
    assert data["gitea_path"] == "scripts/postgres-dump.sh"
    assert data["gitea_sha"] == "sha123"
    assert server_id in data["server_ids"]
    assert data["success_notification_message"] == "Postgres backup finished on {server}"


@patch("api.routes.scripts.get_gitea_client")
def test_create_script_missing_name(mock_gitea, client, app):
    resp = client.post("/api/scripts/", json={"server_ids": []})
    assert resp.status_code == 400


@patch("api.routes.scripts.get_gitea_client")
def test_create_script_no_servers(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha123"
    resp = client.post("/api/scripts/", json={
        "name": "No Server Script",
        "content": "#!/bin/bash\necho hi",
    })
    assert resp.status_code == 201
    assert resp.get_json()["server_ids"] == []


@patch("api.routes.scripts.get_gitea_client")
def test_list_scripts(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha123"
    client.post("/api/scripts/", json={"name": "My Script", "content": "#!/bin/bash\necho hi"})
    resp = client.get("/api/scripts/")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


@patch("api.routes.scripts.get_gitea_client")
def test_get_script_with_content(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha456"
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho hello", "sha456")
    create_resp = client.post("/api/scripts/", json={
        "name": "Hello Script",
        "content": "#!/bin/bash\necho hello",
    })
    script_id = create_resp.get_json()["id"]
    resp = client.get(f"/api/scripts/{script_id}")
    assert resp.status_code == 200
    assert resp.get_json()["content"] == "#!/bin/bash\necho hello"


@patch("api.routes.scripts.get_gitea_client")
def test_update_script(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha789"
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho old", "sha456")
    create_resp = client.post("/api/scripts/", json={
        "name": "Update Me",
        "content": "#!/bin/bash\necho old",
    })
    script_id = create_resp.get_json()["id"]
    resp = client.put(f"/api/scripts/{script_id}", json={
        "content": "#!/bin/bash\necho new",
        "description": "Updated description",
        "success_notification_message": "Updated success message",
    })
    assert resp.status_code == 200
    assert resp.get_json()["description"] == "Updated description"
    assert resp.get_json()["success_notification_message"] == "Updated success message"


@patch("api.services.gitea.GiteaClient")
@patch("api.routes.scripts.get_gitea_client")
def test_script_detail_renders_success_notification_message(mock_gitea, mock_ui_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha789"
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho ok", "sha789")
    mock_ui_gitea.return_value.get_file.return_value = ("#!/bin/bash\necho ok", "sha789")
    create_resp = client.post("/api/scripts/", json={
        "name": "Notify Me",
        "content": "#!/bin/bash\necho ok",
        "notify_on_success": True,
        "success_notification_message": "Duplicacy summary is ready",
    })
    script_id = create_resp.get_json()["id"]

    resp = client.get(f"/scripts/{script_id}")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Success notification message" in html
    assert "Duplicacy summary is ready" in html


@patch("api.routes.scripts.get_gitea_client")
def test_delete_script(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha000"
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash", "sha000")
    create_resp = client.post("/api/scripts/", json={
        "name": "Delete Me",
        "content": "#!/bin/bash\necho bye",
    })
    script_id = create_resp.get_json()["id"]
    resp = client.delete(f"/api/scripts/{script_id}")
    assert resp.status_code == 200
    assert client.get(f"/api/scripts/{script_id}").status_code == 404


@patch("api.routes.scripts.get_gitea_client")
def test_trigger_script_on_server(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "trigsha"
    [server_id] = make_servers(app, ("trigger-server",))
    create_resp = client.post("/api/scripts/", json={
        "name": "Trigger Me",
        "server_ids": [server_id],
        "content": "#!/bin/bash\necho run",
    })
    script_id = create_resp.get_json()["id"]
    resp = client.post(f"/api/scripts/{script_id}/trigger", json={"server_ids": [server_id]})
    assert resp.status_code == 201
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["triggered_by"] == "manual"
    assert jobs[0]["server_name"] == "trigger-server"


@patch("api.routes.scripts.get_gitea_client")
def test_trigger_on_multiple_servers(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha111"
    server_ids = make_servers(app, ("srv-a", "srv-b"))
    create_resp = client.post("/api/scripts/", json={
        "name": "Multi Run",
        "server_ids": server_ids,
        "content": "#!/bin/bash\necho hi",
    })
    script_id = create_resp.get_json()["id"]
    resp = client.post(f"/api/scripts/{script_id}/trigger", json={"server_ids": server_ids})
    assert resp.status_code == 201
    assert len(resp.get_json()) == 2


@patch("api.routes.scripts.get_gitea_client")
def test_scripts_overview_renders_per_server_run_buttons(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha222"
    [server_id] = make_servers(app, ("overview-server",))
    create_resp = client.post("/api/scripts/", json={
        "name": "Overview Run",
        "server_ids": [server_id],
        "content": "#!/bin/bash\necho overview",
    })
    script_id = create_resp.get_json()["id"]

    resp = client.get("/scripts")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Run on overview-server" in html
    assert f"triggerAll({script_id}, [{server_id}])" in html


@patch("api.routes.scripts.get_gitea_client")
def test_trigger_disabled_returns_403(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha123"
    [server_id] = make_servers(app, ("no-trigger-server",))
    create_resp = client.post("/api/scripts/", json={
        "name": "No Trigger",
        "server_ids": [server_id],
        "content": "#!/bin/bash",
        "manual_trigger": False,
    })
    script_id = create_resp.get_json()["id"]
    resp = client.post(f"/api/scripts/{script_id}/trigger", json={"server_ids": [server_id]})
    assert resp.status_code == 403


@patch("api.routes.scripts.get_gitea_client")
def test_create_script_invalid_slug(mock_gitea, client, app):
    resp = client.post("/api/scripts/", json={
        "name": "!@#$%",
        "content": "#!/bin/bash",
    })
    assert resp.status_code == 400


@patch("api.routes.scripts.get_gitea_client")
def test_update_script_server_assignments(mock_gitea, client, app):
    mock_gitea.return_value.create_or_update_file.return_value = "sha999"
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash", "sha999")
    server_ids = make_servers(app, ("update-srv-a", "update-srv-b"))
    create_resp = client.post("/api/scripts/", json={
        "name": "Reassign Me",
        "server_ids": [server_ids[0]],
        "content": "#!/bin/bash",
    })
    script_id = create_resp.get_json()["id"]
    assert create_resp.get_json()["server_ids"] == [server_ids[0]]

    resp = client.put(f"/api/scripts/{script_id}", json={"server_ids": server_ids})
    assert resp.status_code == 200
    assert set(resp.get_json()["server_ids"]) == set(server_ids)


def test_script_parameters_default_empty(app):
    with app.app_context():
        from api.models import Script
        from api.extensions import db
        sc = Script(name="p-test", gitea_path="scripts/p-test.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.commit()
        assert sc.to_dict()["parameters"] == []


def test_job_parameters_default_empty(app):
    with app.app_context():
        from api.models import Script, Server, Job
        from api.extensions import db
        s = Server(name="param-server")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="pjob-test", gitea_path="scripts/pjob-test.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        job = Job(script_id=sc.id, server_id=s.id)
        db.session.add(job)
        db.session.commit()
        assert job.to_dict()["parameters"] == {}


@patch("api.routes.scripts.get_gitea_client")
def test_create_script_with_parameters(mock_gitea, client, app):
    mock_gitea.return_value.get_file.return_value = (None, None)
    mock_gitea.return_value.create_or_update_file.return_value = "sha1"
    resp = client.post("/api/scripts/", json={
        "name": "param-script",
        "content": "#!/bin/bash\necho $DAYS",
        "parameters": [{"name": "DAYS", "default": "7", "description": "Days to retain"}],
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["parameters"] == [{"name": "DAYS", "default": "7", "description": "Days to retain"}]


@patch("api.routes.scripts.get_gitea_client")
def test_update_script_parameters(mock_gitea, client, app):
    mock_gitea.return_value.get_file.return_value = ("#!/bin/bash", "sha1")
    mock_gitea.return_value.create_or_update_file.return_value = "sha2"
    r = client.post("/api/scripts/", json={"name": "upd-param", "content": "#!/bin/bash"})
    assert r.status_code == 201
    script_id = r.get_json()["id"]
    resp = client.put(f"/api/scripts/{script_id}", json={
        "parameters": [{"name": "TARGET", "default": "/tmp", "description": "Target dir"}],
    })
    assert resp.status_code == 200
    assert resp.get_json()["parameters"][0]["name"] == "TARGET"


def test_validate_script_success(client):
    resp = client.post("/api/scripts/validate", json={"content": "#!/bin/bash\necho ok"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is True
    assert data["output"] == ""


def test_validate_script_syntax_error(client):
    resp = client.post("/api/scripts/validate", json={"content": "#!/bin/bash\nif true; then\necho nope"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["valid"] is False
    assert "syntax error" in data["output"].lower()


def test_validate_script_warns_without_shebang(client):
    resp = client.post("/api/scripts/validate", json={"content": "echo ok"})
    assert resp.status_code == 200
    assert resp.get_json()["warnings"] == ["Script has no shebang; agents run it with /bin/bash."]


@patch("api.routes.scripts.get_gitea_client")
def test_create_script_assigns_servers_by_tag(mock_gitea, client, app):
    mock_gitea.return_value.get_file.return_value = (None, None)
    mock_gitea.return_value.create_or_update_file.return_value = "sha1"
    with app.app_context():
        dns = Server(name="dns-srv", tags=["dns"])
        db.session.add(dns)
        db.session.add(Server(name="db-srv", tags=["postgres"]))
        db.session.commit()
        dns_id = dns.id

    resp = client.post("/api/scripts/", json={
        "name": "dns-only",
        "content": "#!/bin/bash\necho dns",
        "server_tags": ["dns"],
    })
    assert resp.status_code == 201
    assert resp.get_json()["server_ids"] == [dns_id]


def test_trigger_by_tag_only_targets_assigned_servers(client, app):
    with app.app_context():
        dns = Server(name="dns-trigger", tags=["dns"])
        other = Server(name="other-trigger", tags=["dns"])
        db.session.add_all([dns, other])
        db.session.flush()
        sc = Script(name="tag-run", gitea_path="scripts/tag-run.sh", gitea_sha="sha1")
        sc.server_assignments = [ScriptServer(server_id=dns.id)]
        db.session.add(sc)
        db.session.commit()
        script_id = sc.id
        dns_id = dns.id

    resp = client.post(f"/api/scripts/{script_id}/trigger", json={"server_tags": ["dns"]})
    assert resp.status_code == 201
    jobs = resp.get_json()
    assert len(jobs) == 1
    assert jobs[0]["server_name"] == "dns-trigger"
    assert jobs[0]["server_id"] == dns_id


def test_script_server_status(client, app):
    with app.app_context():
        s = Server(name="status-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="status-script", gitea_path="scripts/status-script.sh", gitea_sha="sha1")
        sc.server_assignments = [ScriptServer(server_id=s.id, schedule="0 2 * * *")]
        db.session.add(sc)
        db.session.flush()
        db.session.add(Job(script_id=sc.id, server_id=s.id, status="success"))
        db.session.add(Job(script_id=sc.id, server_id=s.id, status="failure"))
        db.session.add(MissedRun(script_id=sc.id, server_id=s.id, expected_at=sc.created_at))
        db.session.commit()
        script_id = sc.id

    resp = client.get(f"/api/scripts/{script_id}/server-status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["server"]["name"] == "status-srv"
    assert data[0]["schedule"] == "0 2 * * *"
    assert data[0]["last_success"]["status"] == "success"
    assert data[0]["last_failure"]["status"] == "failure"
    assert data[0]["missed_run"] is not None


@patch("api.routes.scripts.get_gitea_client")
def test_script_history_lists_gitea_commits(mock_gitea, client, app):
    with app.app_context():
        sc = Script(name="hist-script", gitea_path="scripts/hist.sh", gitea_sha="sha1")
        db.session.add(sc)
        db.session.commit()
        script_id = sc.id

    mock_gitea.return_value.list_file_commits.return_value = [{
        "sha": "abcdef123456",
        "commit": {
            "message": "Update backup script\n\nbody",
            "author": {"name": "Admin", "date": "2026-05-05T10:00:00Z"},
        },
    }]

    resp = client.get(f"/api/scripts/{script_id}/history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["short_sha"] == "abcdef12"
    assert data[0]["message"] == "Update backup script"


@patch("api.routes.scripts.get_gitea_client")
def test_restore_script_version_updates_gitea_and_sha(mock_gitea, client, app):
    with app.app_context():
        sc = Script(name="restore-script", gitea_path="scripts/restore.sh", gitea_sha="current")
        db.session.add(sc)
        db.session.commit()
        script_id = sc.id

    def get_file(path, ref=None):
        if ref == "oldcommit":
            return "#!/bin/bash\necho old", "oldblob"
        return "#!/bin/bash\necho current", "currblob"

    mock_gitea.return_value.get_file.side_effect = get_file
    mock_gitea.return_value.create_or_update_file.return_value = "newsha"

    resp = client.post(f"/api/scripts/{script_id}/restore", json={"ref": "oldcommit"})
    assert resp.status_code == 200
    assert resp.get_json()["gitea_sha"] == "newsha"
    mock_gitea.return_value.create_or_update_file.assert_called_once()
    kwargs = mock_gitea.return_value.create_or_update_file.call_args.kwargs
    assert kwargs["content"] == "#!/bin/bash\necho old"
    assert kwargs["sha"] == "currblob"
