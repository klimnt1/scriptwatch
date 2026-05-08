import hashlib
import hmac
import os
import time

from flask import Blueprint, Response, current_app, jsonify, request
from functools import wraps

agents_bp = Blueprint("agents", __name__)

_AGENT_PATH = "agent/agent.py"
_CACHE_TTL = 300  # 5 minutes
_cache = {"hash": None, "content": None, "fetched_at": 0.0}


def _refresh_cache(config):
    try:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        with open(os.path.join(repo_root, _AGENT_PATH), encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return
    _cache["content"] = content
    _cache["hash"] = hashlib.sha256(content.encode()).hexdigest()
    _cache["fetched_at"] = time.time()


def get_latest_agent_hash(config):
    if not _cache["hash"] or time.time() - _cache["fetched_at"] >= _CACHE_TTL:
        _refresh_cache(config)
    return _cache["hash"]


def get_latest_agent_content(config):
    if not _cache["content"] or time.time() - _cache["fetched_at"] >= _CACHE_TTL:
        _refresh_cache(config)
    return _cache["content"]


def require_agent_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        configured_token = current_app.config.get("AGENT_TOKEN") or ""
        if not configured_token:
            return jsonify({"error": "unauthorized"}), 401
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {configured_token}"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@agents_bp.get("/latest-hash")
def latest_hash():
    h = get_latest_agent_hash(current_app.config)
    if h is None:
        return jsonify({"error": "could not load bundled agent"}), 503
    return jsonify({"hash": h})


@agents_bp.get("/download")
@require_agent_token
def download():
    content = get_latest_agent_content(current_app.config)
    if content is None:
        return jsonify({"error": "could not load bundled agent"}), 503
    return Response(content, mimetype="text/plain")
