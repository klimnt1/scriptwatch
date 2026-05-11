from api.models import Server, Script, Job
from api.extensions import db
from datetime import datetime, timedelta


def test_app_creates(app):
    assert app is not None

def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_server_model(app):
    with app.app_context():
        s = Server(name="plexusprime", hostname="192.168.1.10")
        db.session.add(s)
        db.session.commit()
        fetched = Server.query.filter_by(name="plexusprime").first()
        assert fetched is not None
        assert fetched.hostname == "192.168.1.10"


def test_server_is_online_no_heartbeat(app):
    with app.app_context():
        s = Server(name="dns-alpha")
        assert s.is_online is False


def test_server_is_online_recent_heartbeat(app):
    with app.app_context():
        s = Server(name="dns-beta", last_heartbeat=datetime.utcnow())
        assert s.is_online is True


def test_server_is_offline_old_heartbeat(app):
    with app.app_context():
        s = Server(name="backups-tower", last_heartbeat=datetime.utcnow() - timedelta(minutes=10))
        assert s.is_online is False


def test_script_model(app):
    with app.app_context():
        server = Server(name="plexusprime2", hostname="192.168.1.10")
        db.session.add(server)
        db.session.flush()
        script = Script(
            name="Postgres Dump",
            description="Daily pg_dump",
            gitea_path="scripts/postgres-dump.sh",
            schedule="0 2 * * *",
            timeout_seconds=1800,
            success_notification_message="Backup finished for {server}",
        )
        script.servers.append(server)
        db.session.add(script)
        db.session.commit()
        fetched = Script.query.filter_by(name="Postgres Dump").first()
        assert fetched.servers[0].name == "plexusprime2"
        assert fetched.enabled is True
        assert fetched.to_dict()["success_notification_message"] == "Backup finished for {server}"


def test_job_model(app):
    with app.app_context():
        server = Server(name="tower")
        db.session.add(server)
        db.session.flush()
        script = Script(name="test-script")
        db.session.add(script)
        db.session.flush()
        job = Job(script_id=script.id, server_id=server.id, triggered_by="manual")
        db.session.add(job)
        db.session.commit()
        fetched = Job.query.first()
        assert fetched.status == "pending"
        assert fetched.script.name == "test-script"


def test_job_to_dict(app):
    with app.app_context():
        server = Server(name="tower2")
        db.session.add(server)
        db.session.flush()
        script = Script(name="backup")
        db.session.add(script)
        db.session.flush()
        job = Job(script_id=script.id, server_id=server.id, status="success", exit_code=0)
        db.session.add(job)
        db.session.commit()
        d = job.to_dict()
        assert d["status"] == "success"
        assert d["script_name"] == "backup"
        assert d["server_name"] == "tower2"


def test_job_server_name_from_job_not_script(app):
    with app.app_context():
        srv = Server(name="alpha")
        db.session.add(srv)
        db.session.flush()
        sc = Script(name="myscript", gitea_path="scripts/myscript.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        job = Job(script_id=sc.id, server_id=srv.id)
        db.session.add(job)
        db.session.commit()
        assert job.to_dict()["server_name"] == "alpha"


def test_missed_run_model(app):
    with app.app_context():
        from api.models import MissedRun
        s = Server(name="miss-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="miss-script", gitea_path="scripts/miss-script.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        expected = datetime(2026, 5, 1, 2, 0, 0)
        mr = MissedRun(script_id=sc.id, server_id=s.id, expected_at=expected, alerted_at=datetime.utcnow())
        db.session.add(mr)
        db.session.commit()
        d = mr.to_dict()
        assert d["script_name"] == "miss-script"
        assert d["server_name"] == "miss-srv"
        assert "2026-05-01" in d["expected_at"]


def test_missed_run_unique_constraint(app):
    with app.app_context():
        import pytest
        from api.models import MissedRun
        s = Server(name="miss-srv-2")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="miss-script-2", gitea_path="scripts/miss-script-2.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        expected = datetime(2026, 5, 1, 3, 0, 0)
        mr1 = MissedRun(script_id=sc.id, server_id=s.id, expected_at=expected)
        db.session.add(mr1)
        db.session.commit()
        mr2 = MissedRun(script_id=sc.id, server_id=s.id, expected_at=expected)
        db.session.add(mr2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_missed_run_checker_creates_record(app):
    with app.app_context():
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from api.models import Script, Server, ScriptServer, MissedRun
        from api.extensions import db
        from api.services.scheduler_tasks import make_missed_run_checker

        s = Server(name="checker-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="checker-script", gitea_path="scripts/checker.sh", gitea_sha="abc", enabled=True)
        db.session.add(sc)
        db.session.flush()
        sa = ScriptServer(script_id=sc.id, server_id=s.id, schedule="* * * * *")
        db.session.add(sa)
        db.session.commit()
        script_id, server_id = sc.id, s.id

        checker = make_missed_run_checker(app, grace_minutes=0)
        with patch("api.services.scheduler_tasks.notify_missed_run") as mock_notify:
            checker()
            assert mock_notify.called

        missed = MissedRun.query.filter_by(script_id=script_id, server_id=server_id).first()
        assert missed is not None

def test_missed_run_checker_no_duplicate(app):
    with app.app_context():
        from unittest.mock import patch
        from api.models import Script, Server, ScriptServer, MissedRun
        from api.extensions import db
        from api.services.scheduler_tasks import make_missed_run_checker

        s = Server(name="no-dup-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="no-dup-script", gitea_path="scripts/no-dup.sh", gitea_sha="abc", enabled=True)
        db.session.add(sc)
        db.session.flush()
        sa = ScriptServer(script_id=sc.id, server_id=s.id, schedule="* * * * *")
        db.session.add(sa)
        db.session.commit()

        checker = make_missed_run_checker(app, grace_minutes=0)
        with patch("api.services.scheduler_tasks.notify_missed_run") as mock_notify:
            checker()
            checker()
            assert mock_notify.call_count == 1

def test_missed_run_checker_skips_if_job_exists(app):
    with app.app_context():
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from croniter import croniter
        from api.models import Script, Server, ScriptServer, Job, MissedRun
        from api.extensions import db
        from api.services.scheduler_tasks import make_missed_run_checker

        s = Server(name="job-exists-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="job-exists-script", gitea_path="scripts/job-exists.sh", gitea_sha="abc", enabled=True)
        db.session.add(sc)
        db.session.flush()
        sa = ScriptServer(script_id=sc.id, server_id=s.id, schedule="* * * * *")
        db.session.add(sa)
        db.session.flush()

        now = datetime.utcnow()
        cron = croniter("* * * * *", now)
        prev = cron.get_prev(datetime)
        job = Job(script_id=sc.id, server_id=s.id, status="success",
                  triggered_by="schedule", created_at=prev, gitea_sha="abc")
        db.session.add(job)
        db.session.commit()
        script_id, server_id = sc.id, s.id

        checker = make_missed_run_checker(app, grace_minutes=0)
        with patch("api.services.scheduler_tasks.notify_missed_run") as mock_notify:
            checker()
            assert not mock_notify.called

        missed = MissedRun.query.filter_by(script_id=script_id, server_id=server_id).first()
        assert missed is None

def test_notify_missed_run_discord(app):
    with app.app_context():
        from unittest.mock import patch, MagicMock
        from api.services.notifier import notify_missed_run

        s = Server(name="miss-notify-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="miss-notify-script", gitea_path="scripts/x.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.commit()

        config = {"DISCORD_WEBHOOK_URL": "https://discord.example.com/webhook"}
        expected = datetime(2026, 5, 1, 2, 0, 0)
        with patch("api.services.notifier.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            notify_missed_run(config, sc, s, expected)
            assert mock_post.called
            body = mock_post.call_args[1]["json"]
            title = body["embeds"][0]["title"]
            assert "miss" in title.lower() or "missed" in title.lower()


def test_notify_job_result_uses_success_message(app):
    with app.app_context():
        from unittest.mock import patch, MagicMock
        from api.services.notifier import notify_job_result

        server = Server(name="notify-success-srv")
        db.session.add(server)
        db.session.flush()
        script = Script(
            name="notify-success-script",
            gitea_path="scripts/x.sh",
            gitea_sha="abc",
            notify_on_success=True,
            success_notification_message="{script} is green on {server}: {output}",
        )
        db.session.add(script)
        db.session.flush()
        job = Job(
            script_id=script.id,
            server_id=server.id,
            status="success",
            exit_code=0,
            output="all done",
        )
        db.session.add(job)
        db.session.commit()

        config = {"DISCORD_WEBHOOK_URL": "https://discord.example.com/webhook"}
        with patch("api.services.notifier.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=204)
            notify_job_result(config, job)

        assert mock_post.called
        body = mock_post.call_args[1]["json"]
        assert body["embeds"][0]["description"] == (
            "```\nnotify-success-script is green on notify-success-srv: all done\n```"
        )


def test_server_agent_hash_nullable(app):
    with app.app_context():
        s = Server(name="hash-test-srv")
        db.session.add(s)
        db.session.commit()
        assert s.agent_hash is None

def test_server_agent_hash_stores_value(app):
    with app.app_context():
        s = Server(name="hash-test-srv2", agent_hash="abc123")
        db.session.add(s)
        db.session.commit()
        fetched = Server.query.filter_by(name="hash-test-srv2").first()
        assert fetched.agent_hash == "abc123"

def test_system_job_no_script(app):
    with app.app_context():
        s = Server(name="sys-job-srv")
        db.session.add(s)
        db.session.flush()
        job = Job(
            script_id=None,
            server_id=s.id,
            triggered_by="system",
            script_content="#!/bin/bash\necho update",
        )
        db.session.add(job)
        db.session.commit()
        fetched = Job.query.filter_by(server_id=s.id).first()
        assert fetched.script_id is None
        assert fetched.script_content == "#!/bin/bash\necho update"
        assert fetched.triggered_by == "system"

def test_system_job_to_dict_null_script(app):
    with app.app_context():
        s = Server(name="sys-dict-srv")
        db.session.add(s)
        db.session.flush()
        job = Job(
            script_id=None,
            server_id=s.id,
            triggered_by="system",
            script_content="#!/bin/bash\necho hi",
        )
        db.session.add(job)
        db.session.commit()
        d = job.to_dict()
        assert d["script_name"] == "Update Agent"
        assert d["script_id"] is None
        assert d["script_content"] == "#!/bin/bash\necho hi"

def test_dashboard_shows_missed_runs(client, app):
    with app.app_context():
        from api.models import Script, Server, MissedRun
        from api.extensions import db
        s = Server(name="dash-miss-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="dash-miss-script", gitea_path="scripts/dm.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        mr = MissedRun(
            script_id=sc.id,
            server_id=s.id,
            expected_at=datetime.utcnow() - timedelta(hours=1),
            alerted_at=datetime.utcnow() - timedelta(hours=1),
        )
        db.session.add(mr)
        db.session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"dash-miss-script" in resp.data
    assert b"Missed scheduled runs" in resp.data


def test_dashboard_shows_active_failures(client, app):
    with app.app_context():
        s = Server(name="dash-fail-srv")
        db.session.add(s)
        db.session.flush()
        sc = Script(name="dash-fail-script", gitea_path="scripts/df.sh", gitea_sha="abc")
        db.session.add(sc)
        db.session.flush()
        job = Job(
            script_id=sc.id,
            server_id=s.id,
            status="failure",
            triggered_by="schedule",
            completed_at=datetime.utcnow(),
            exit_code=1,
        )
        db.session.add(job)
        db.session.commit()

    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Active Failures" in resp.data
    assert b"dash-fail-script" in resp.data
    assert b"Dismiss" in resp.data
