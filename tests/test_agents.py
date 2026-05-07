from unittest.mock import patch


def test_latest_hash_requires_no_auth(client):
    with patch("api.routes.agents.get_latest_agent_hash") as mock_hash:
        mock_hash.return_value = "abc123"
        resp = client.get("/api/agent/latest-hash")
    assert resp.status_code == 200
    assert resp.get_json()["hash"] == "abc123"


def test_latest_hash_gitea_unreachable(client):
    with patch("api.routes.agents.get_latest_agent_hash") as mock_hash:
        mock_hash.return_value = None
        resp = client.get("/api/agent/latest-hash")
    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_download_requires_agent_token(client):
    resp = client.get("/api/agent/download")
    assert resp.status_code == 401


def test_download_returns_agent_content(client, app):
    with patch("api.routes.agents.get_latest_agent_content") as mock_content:
        mock_content.return_value = "#!/usr/bin/env python3\nprint('agent')"
        resp = client.get(
            "/api/agent/download",
            headers={"Authorization": f"Bearer {app.config['AGENT_TOKEN']}"},
        )
    assert resp.status_code == 200
    assert b"agent" in resp.data


def test_download_gitea_unreachable(client, app):
    with patch("api.routes.agents.get_latest_agent_content") as mock_content:
        mock_content.return_value = None
        resp = client.get(
            "/api/agent/download",
            headers={"Authorization": f"Bearer {app.config['AGENT_TOKEN']}"},
        )
    assert resp.status_code == 503
