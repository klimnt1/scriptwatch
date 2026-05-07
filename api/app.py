import base64
import hashlib
import hmac
import logging
import os
import struct
import time
from datetime import timezone as _utc
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from .config import Config
from .extensions import db, scheduler

_ET = ZoneInfo("America/New_York")
_AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent")
_INSTALL_SH_PATH = os.path.join(_AGENT_DIR, "install.sh")


def _build_install_script(base_url, agent_token, server_name=None):
    with open(_INSTALL_SH_PATH) as f:
        script = f.read()
    # Redirect agent.py download to ScriptWatch so installs are self-contained.
    script = script.replace(
        'AGENT_URL="https://gitea.plexusprime.net/adrianoropesa/scriptwatch/raw/branch/main/agent/agent.py"',
        f'AGENT_URL="{base_url}/install/agent.py"',
    )
    script = script.replace(
        'prompt API_URL      "ScriptWatch API URL"   "http://192.168.20.244:8095"\n'
        'while [ -z "$API_URL" ]; do\n'
        '    warn "API URL is required."\n'
        '    prompt API_URL  "ScriptWatch API URL"   "http://192.168.20.244:8095"\n'
        'done',
        f'API_URL="{base_url}"\nok "API URL pre-configured: $API_URL"',
    )
    script = script.replace(
        'prompt AGENT_TOKEN  "Agent token" "" "true"\n'
        'while [ -z "$AGENT_TOKEN" ]; do\n'
        '    warn "Agent token is required."\n'
        '    prompt AGENT_TOKEN "Agent token" "" "true"\n'
        'done',
        f'AGENT_TOKEN="{agent_token}"\nok "Agent token pre-configured"',
    )
    if server_name:
        script = script.replace(
            'prompt SERVER_NAME  "Server name (e.g. dns-alpha)" ""\n'
            'while [ -z "$SERVER_NAME" ]; do\n'
            '    warn "Server name is required."\n'
            '    prompt SERVER_NAME "Server name (e.g. dns-alpha)" ""\n'
            'done',
            f'SERVER_NAME="{server_name}"\nok "Server name pre-configured: $SERVER_NAME"',
        )
        script = script.replace(
            'prompt POLL_INTERVAL      "Poll interval (seconds)"      "10"\n'
            'prompt HEARTBEAT_INTERVAL "Heartbeat interval (seconds)" "30"',
            'POLL_INTERVAL="10"\nHEARTBEAT_INTERVAL="30"',
        )
        script = script.replace(
            'echo -ne "Proceed with installation? [Y/n]: "\n'
            'read -r confirm\n'
            'if [[ "$confirm" =~ ^[Nn] ]]; then\n'
            '    echo "Aborted."\n'
            '    exit 0\n'
            'fi',
            '',
        )
    return script


def _to_et(dt):
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_utc.utc)
    return dt.astimezone(_ET).strftime("%Y-%m-%d %H:%M ET")


def create_app(config_override=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)

    db.init_app(app)
    app.jinja_env.filters["to_et"] = _to_et
    _install_optional_admin_auth(app)
    _warn_insecure_config(app)

    from .routes.servers import servers_bp
    from .routes.scripts import scripts_bp
    from .routes.jobs import jobs_bp
    from .routes.tags import tags_bp
    from .routes.ui import ui_bp
    from .routes.agents import agents_bp

    app.register_blueprint(servers_bp, url_prefix="/api/servers")
    app.register_blueprint(scripts_bp, url_prefix="/api/scripts")
    app.register_blueprint(jobs_bp, url_prefix="/api/jobs")
    app.register_blueprint(tags_bp, url_prefix="/api/tags")
    app.register_blueprint(agents_bp, url_prefix="/api/agent")
    app.register_blueprint(ui_bp)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    with app.app_context():
        os.makedirs(app.config["DATA_DIR"], exist_ok=True)
        os.makedirs(app.config["SCRIPT_STORE_DIR"], exist_ok=True)
        db.create_all()
        _run_migrations(db)
        _sync_server_tags_to_registry()
        if not app.config.get("TESTING"):
            _start_scheduler(app)

    return app


def _install_optional_admin_auth(app):
    open_paths = {"/api/health"}
    agent_prefixes = ("/api/agent/download", "/api/jobs/pending/", "/api/servers/register", "/install/")

    @app.before_request
    def require_admin_auth():
        if request.endpoint in {"login", "login_post", "ui.static", "static"}:
            return None
        if request.path in open_paths or request.path.startswith(agent_prefixes):
            return None
        if request.path.startswith("/api/jobs/") and (
            request.path.endswith("/start") or request.path.endswith("/complete")
        ):
            return None
        if request.path.startswith("/api/servers/") and request.path.endswith("/heartbeat"):
            return None

        if not _auth_configured(app):
            return None

        auth = request.headers.get("Authorization", "")

        # Agent token grants access to all API endpoints (needed for cancel-check, etc.)
        agent_token = app.config.get("AGENT_TOKEN") or ""
        if agent_token and request.path.startswith("/api/") and hmac.compare_digest(auth, f"Bearer {agent_token}"):
            return None

        token = app.config.get("ADMIN_TOKEN") or ""
        if token and hmac.compare_digest(auth, f"Bearer {token}"):
            return None

        if session.get("admin_authenticated"):
            return None

        basic = request.authorization
        if basic and basic.type == "basic":
            if _verify_admin_credentials(app, basic.username or "", basic.password or "") and not _mfa_enabled():
                return None

        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))

    @app.context_processor
    def inject_auth_state():
        return {
            "admin_auth_enabled": _auth_configured(app),
            "admin_authenticated": bool(session.get("admin_authenticated")),
            "admin_password_set": _admin_password_configured(app),
        }

    @app.get("/login")
    def login():
        if not _auth_configured(app):
            flash("Set an admin password in Settings to enable login.", "info")
            return redirect(url_for("settings_page"))
        if session.get("admin_authenticated"):
            return redirect(_safe_next_url(request.args.get("next")) or url_for("ui.dashboard"))
        return render_template("login.html", next_url=request.args.get("next", ""))

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        otp = request.form.get("otp", "")
        if not _verify_admin_credentials(app, username, password):
            flash("Invalid username or password.", "danger")
            return render_template("login.html", next_url=request.form.get("next", "")), 401

        if _mfa_enabled() and not _verify_totp(_get_setting("mfa_totp_secret"), otp):
            flash("Enter a valid authenticator code.", "danger")
            return render_template("login.html", next_url=request.form.get("next", ""), mfa_required=True), 401

        session.clear()
        session["admin_authenticated"] = True
        session.permanent = True
        return redirect(_safe_next_url(request.form.get("next")) or url_for("ui.dashboard"))

    @app.post("/logout")
    def logout():
        session.clear()
        flash("Signed out.", "info")
        return redirect(url_for("login"))

    @app.get("/settings")
    def settings_page():
        pending_secret = session.get("pending_mfa_secret")
        base_url = (app.config.get("BASE_URL") or request.url_root).rstrip("/")
        agent_token = app.config.get("AGENT_TOKEN", "")
        return render_template(
            "settings.html",
            admin_username=app.config.get("ADMIN_USERNAME", "admin"),
            password_set=_admin_password_configured(app),
            auth_enabled=_auth_configured(app),
            mfa_enabled=_mfa_enabled(),
            pending_secret=pending_secret,
            provisioning_uri=_totp_uri(pending_secret) if pending_secret else "",
            agent_token=agent_token,
            agent_token_is_default=agent_token in ("", "changeme"),
            agent_base_url=base_url,
        )

    @app.post("/settings/password")
    def settings_password():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if _admin_password_configured(app) and not _verify_admin_password(app, current_password):
            flash("Enter your current admin password before changing it.", "danger")
            return redirect(url_for("settings_page"))
        if len(new_password) < 12:
            flash("Use at least 12 characters for the admin password.", "danger")
            return redirect(url_for("settings_page"))
        if new_password != confirm_password:
            flash("The new password fields did not match.", "danger")
            return redirect(url_for("settings_page"))

        _set_setting("admin_password_hash", generate_password_hash(new_password))
        session["admin_authenticated"] = True
        session.permanent = True
        flash("Admin password saved. Login is now enabled.", "success")
        return redirect(url_for("settings_page"))

    @app.post("/settings/mfa/start")
    def mfa_start():
        if not _admin_password_configured(app):
            flash("Set an admin password before adding MFA.", "warning")
            return redirect(url_for("settings_page"))
        session["pending_mfa_secret"] = _generate_totp_secret()
        return redirect(url_for("settings_page"))

    @app.post("/settings/mfa/enable")
    def mfa_enable():
        secret = session.get("pending_mfa_secret", "")
        code = request.form.get("otp", "")
        if not secret:
            flash("Start MFA setup before enabling it.", "warning")
            return redirect(url_for("settings_page"))
        if not _verify_totp(secret, code):
            flash("That authenticator code did not match. Try the next code from your app.", "danger")
            return redirect(url_for("settings_page"))
        _set_setting("mfa_enabled", "true")
        _set_setting("mfa_totp_secret", secret)
        session.pop("pending_mfa_secret", None)
        flash("MFA is enabled for the admin login.", "success")
        return redirect(url_for("settings_page"))

    @app.post("/settings/mfa/disable")
    def mfa_disable():
        password = request.form.get("password", "")
        if _admin_password_configured(app) and not _verify_admin_password(app, password):
            flash("Enter the admin password to disable MFA.", "danger")
            return redirect(url_for("settings_page"))
        _set_setting("mfa_enabled", "false")
        _delete_setting("mfa_totp_secret")
        session.pop("pending_mfa_secret", None)
        flash("MFA is disabled.", "info")
        return redirect(url_for("settings_page"))

    @app.get("/agent/download/install.sh")
    def agent_download_install_sh():
        base_url = (app.config.get("BASE_URL") or request.url_root).rstrip("/")
        agent_token = app.config.get("AGENT_TOKEN", "")
        server_name = request.args.get("name", "").strip() or None
        script = _build_install_script(base_url, agent_token, server_name=server_name)
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="install.sh"'},
        )

    @app.get("/install/agent.py")
    def agent_install_agent_py():
        with open(os.path.join(_AGENT_DIR, "agent.py")) as f:
            content = f.read()
        return Response(content, mimetype="text/x-python")

    @app.get("/install/<server_name>")
    def agent_install_bootstrap(server_name):
        base_url = (app.config.get("BASE_URL") or request.url_root).rstrip("/")
        agent_token = app.config.get("AGENT_TOKEN", "")
        script = _build_install_script(base_url, agent_token, server_name=server_name)
        return Response(
            script,
            mimetype="text/x-shellscript",
            headers={"Content-Disposition": f'attachment; filename="install-{server_name}.sh"'},
        )

    @app.get("/agent/download/docker-compose.yml")
    def agent_download_docker_compose():
        base_url = (app.config.get("BASE_URL") or request.url_root).rstrip("/")
        agent_token = app.config.get("AGENT_TOKEN", "")
        content = (
            "services:\n"
            "  scriptwatch-agent:\n"
            "    image: gitea.plexusprime.net/adrianoropesa/scriptwatch-agent:latest\n"
            "    container_name: ScriptWatch-Agent\n"
            "    restart: unless-stopped\n"
            "    environment:\n"
            f"      SCRIPTWATCH_API_URL: {base_url}\n"
            "      SCRIPTWATCH_SERVER_NAME: YOUR-SERVER-NAME\n"
            f"      SCRIPTWATCH_AGENT_TOKEN: {agent_token}\n"
            "      POLL_INTERVAL: 10\n"
            "      HEARTBEAT_INTERVAL: 30\n"
        )
        return Response(
            content,
            mimetype="text/yaml",
            headers={"Content-Disposition": 'attachment; filename="docker-compose.yml"'},
        )


def _safe_next_url(next_url):
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return None


def _auth_configured(app):
    return bool(app.config.get("ADMIN_TOKEN") or _admin_password_configured(app) or _mfa_enabled())


def _admin_password_configured(app):
    return bool(_get_setting("admin_password_hash") or app.config.get("ADMIN_PASSWORD"))


def _verify_admin_credentials(app, username, password):
    configured_username = app.config.get("ADMIN_USERNAME", "admin")
    return hmac.compare_digest(username or "", configured_username) and _verify_admin_password(app, password)


def _verify_admin_password(app, password):
    db_hash = _get_setting("admin_password_hash")
    if db_hash:
        return check_password_hash(db_hash, password or "")
    configured_password = app.config.get("ADMIN_PASSWORD") or ""
    return bool(configured_password) and hmac.compare_digest(password or "", configured_password)


def _get_setting(key, default=""):
    from .models import AppSetting
    setting = db.session.get(AppSetting, key)
    return setting.value if setting else default


def _set_setting(key, value):
    from .models import AppSetting
    setting = db.session.get(AppSetting, key)
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def _delete_setting(key):
    from .models import AppSetting
    setting = db.session.get(AppSetting, key)
    if setting:
        db.session.delete(setting)
        db.session.commit()


def _mfa_enabled():
    return _get_setting("mfa_enabled", "false") == "true" and bool(_get_setting("mfa_totp_secret"))


def _generate_totp_secret():
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _totp_uri(secret):
    if not secret:
        return ""
    label = quote("ScriptWatch:admin")
    query = urlencode({"secret": secret, "issuer": "ScriptWatch", "algorithm": "SHA1", "digits": 6, "period": 30})
    return f"otpauth://totp/{label}?{query}"


def _totp_code(secret, counter):
    padded_secret = secret + ("=" * ((8 - len(secret) % 8) % 8))
    key = base64.b32decode(padded_secret.upper())
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    token = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{token % 1000000:06d}"


def _verify_totp(secret, code, now=None):
    clean_code = (code or "").replace(" ", "")
    if not secret or not clean_code.isdigit() or len(clean_code) != 6:
        return False
    counter = int((now or time.time()) // 30)
    return any(hmac.compare_digest(_totp_code(secret, counter + drift), clean_code) for drift in (-1, 0, 1))


def _warn_insecure_config(app):
    if app.config.get("TESTING"):
        return
    warnings = []
    if app.config.get("AGENT_TOKEN") in ("", "changeme"):
        warnings.append("AGENT_TOKEN is empty or still set to the default.")
    if app.config.get("SECRET_KEY") in ("", "dev-secret-change-me"):
        warnings.append("SECRET_KEY is empty or still set to the development default.")
    if not (app.config.get("ADMIN_PASSWORD") or app.config.get("ADMIN_TOKEN")):
        warnings.append("Admin authentication is disabled; set ADMIN_PASSWORD or ADMIN_TOKEN to enable it.")
    for msg in warnings:
        logging.getLogger(__name__).warning("Security warning: %s", msg)


def _run_migrations(db):
    if db.engine.url.get_backend_name() == "sqlite":
        return
    migrations = [
        "ALTER TABLE scripts ADD COLUMN IF NOT EXISTS notify_on_failure BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE scripts ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '[]'::jsonb",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS parameters JSONB DEFAULT '{}'::jsonb",
        "ALTER TABLE scripts ADD COLUMN IF NOT EXISTS notify_on_success BOOLEAN DEFAULT FALSE",
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS agent_hash VARCHAR(64)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS script_content TEXT",
        "ALTER TABLE jobs ALTER COLUMN script_id DROP NOT NULL",
        "ALTER TABLE missed_runs ADD COLUMN IF NOT EXISTS dismissed BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dismissed BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS duration_seconds INTEGER",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS anomaly_detected BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS anomaly_reason TEXT",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS replayed_from_job_id INTEGER",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS replay_mode VARCHAR(20)",
        "ALTER TABLE servers ADD COLUMN IF NOT EXISTS pending_uninstall BOOLEAN NOT NULL DEFAULT FALSE",
    ]
    for sql in migrations:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def _sync_server_tags_to_registry():
    from .models import Server, Tag
    known = {t.name for t in Tag.query.all()}
    new_tags = []
    for server in Server.query.all():
        for tag in (server.tags or []):
            if tag and tag not in known:
                known.add(tag)
                new_tags.append(Tag(name=tag))
    if new_tags:
        db.session.add_all(new_tags)
        db.session.commit()


def _start_scheduler(app):
    from .models import Script
    from .services.scheduler_tasks import register_script_schedules, register_pruner
    from .services.scheduler_tasks import register_missed_run_checker
    if not scheduler.running:
        scheduler.start()
    register_pruner(scheduler, app)
    register_missed_run_checker(scheduler, app)
    with app.app_context():
        for script in Script.query.filter(Script.enabled == True).all():
            register_script_schedules(scheduler, script, app)
