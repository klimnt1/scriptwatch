import base64
import time

from api.app import _totp_code, create_app
from api.extensions import db


def _make_app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'security.db'}",
        "DATA_DIR": str(tmp_path / "data"),
        "SCRIPT_STORE_DIR": str(tmp_path / "data" / "script-store"),
        "AGENT_TOKEN": "test-agent-token",
        "SECRET_KEY": "test-secret",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "secret-password",
    })
    with app.app_context():
        db.create_all()
    return app


def test_admin_auth_is_optional_by_default(client):
    resp = client.get("/api/servers/")
    assert resp.status_code == 200


def test_settings_is_visible_before_auth_is_configured(client):
    resp = client.get("/settings")

    assert resp.status_code == 200
    assert b"Set password" in resp.data
    assert b"Login off" in resp.data
    assert b"test-agent-token" not in resp.data
    assert b"Set an admin password before viewing the agent token." in resp.data


def test_setting_password_enables_login_for_default_install(client):
    resp = client.post("/settings/password", data={
        "new_password": "new-secret-password",
        "confirm_password": "new-secret-password",
    })
    assert resp.status_code == 302
    assert client.get("/").status_code == 200

    client.post("/logout")
    blocked = client.get("/")
    assert blocked.status_code == 302
    assert "/login?next=/" in blocked.headers["Location"]

    bad_login = client.post("/login", data={"username": "admin", "password": "wrong-password"})
    assert bad_login.status_code == 401
    good_login = client.post("/login", data={"username": "admin", "password": "new-secret-password"})
    assert good_login.status_code == 302
    assert client.get("/").status_code == 200


def test_admin_auth_blocks_ui_and_admin_api_when_configured(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login?next=/" in resp.headers["Location"]
    assert client.get("/api/servers/").status_code == 401
    assert client.get("/api/health").status_code == 200


def test_admin_auth_accepts_basic_auth_when_configured(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    token = base64.b64encode(b"admin:secret-password").decode()

    resp = client.get("/api/servers/", headers={"Authorization": f"Basic {token}"})
    assert resp.status_code == 200


def test_agent_routes_still_use_agent_token_when_admin_auth_configured(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    resp = client.post(
        "/api/servers/register",
        json={"name": "agent-auth-srv"},
        headers={"Authorization": f"Bearer {app.config['AGENT_TOKEN']}"},
    )
    assert resp.status_code == 201


def test_admin_login_sets_session_when_configured(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    resp = client.post("/login", data={
        "username": "admin",
        "password": "secret-password",
        "next": "/scripts",
    })

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/scripts"
    assert client.get("/scripts").status_code == 200


def test_settings_shows_agent_onboarding_after_password_is_set(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    client.post("/login", data={"username": "admin", "password": "secret-password"})
    resp = client.get("/settings")

    assert resp.status_code == 200
    assert b"Agent onboarding" in resp.data
    assert b"test-agent-token" in resp.data
    assert b"Agent environment" not in resp.data


def test_settings_can_enable_mfa_and_require_code_on_next_login(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    client.post("/login", data={"username": "admin", "password": "secret-password"})
    assert client.post("/settings/mfa/start").status_code == 302
    with client.session_transaction() as sess:
        secret = sess["pending_mfa_secret"]
    code = _totp_code(secret, int(time.time()) // 30)

    resp = client.post("/settings/mfa/enable", data={"otp": code})
    assert resp.status_code == 302

    client.post("/logout")
    assert client.post("/login", data={"username": "admin", "password": "secret-password"}).status_code == 401
    code = _totp_code(secret, int(time.time()) // 30)
    resp = client.post("/login", data={"username": "admin", "password": "secret-password", "otp": code})
    assert resp.status_code == 302


def test_settings_can_reset_mfa(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    client.post("/login", data={"username": "admin", "password": "secret-password"})
    client.post("/settings/mfa/start")
    with client.session_transaction() as sess:
        secret = sess["pending_mfa_secret"]
    client.post("/settings/mfa/enable", data={"otp": _totp_code(secret, int(time.time()) // 30)})

    resp = client.post("/settings/mfa/disable", data={"password": "secret-password"})

    assert resp.status_code == 302
    client.post("/logout")
    assert client.post("/login", data={"username": "admin", "password": "secret-password"}).status_code == 302


def test_install_sh_download_returns_prefilled_script(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "secret-password"})

    resp = client.get("/agent/download/install.sh")

    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"] == 'attachment; filename="install.sh"'
    body = resp.data.decode()
    assert 'API_URL="http://localhost"' in body  # request.url_root in test client is http://localhost/
    assert 'AGENT_TOKEN="test-agent-token"' in body
    assert "prompt API_URL" not in body
    assert "prompt AGENT_TOKEN" not in body
    assert '192.168.20.244' not in body  # old hardcoded default is gone
    assert 'prompt SERVER_NAME  "Server name (e.g. dns-alpha)"' in body


def test_docker_compose_download_returns_prefilled_yaml(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "secret-password"})

    resp = client.get("/agent/download/docker-compose.yml")

    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"] == 'attachment; filename="docker-compose.yml"'
    body = resp.data.decode()
    assert "SCRIPTWATCH_API_URL:" in body
    assert "test-agent-token" in body
    assert "YOUR-SERVER-NAME" in body

    # Verify YAML structure and values
    import yaml
    parsed = yaml.safe_load(body)
    assert "services" in parsed
    env = parsed["services"]["scriptwatch-agent"]["environment"]
    assert env["SCRIPTWATCH_API_URL"] == "http://localhost"
    assert env["SCRIPTWATCH_AGENT_TOKEN"] == "test-agent-token"
    assert env["SCRIPTWATCH_SERVER_NAME"] == "YOUR-SERVER-NAME"


def test_download_routes_require_auth(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    assert client.get("/agent/download/install.sh").status_code in (302, 401)
    assert client.get("/agent/download/docker-compose.yml").status_code in (302, 401)


def test_bootstrap_route_is_public_and_fully_noninteractive(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    resp = client.get("/install/dns-alpha")

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'API_URL="http://localhost"' in body
    assert 'AGENT_TOKEN="test-agent-token"' in body
    assert 'SERVER_NAME="dns-alpha"' in body
    assert 'prompt SERVER_NAME' not in body
    assert 'POLL_INTERVAL="10"' in body
    assert 'HEARTBEAT_INTERVAL="30"' in body
    assert 'read -r confirm' not in body
