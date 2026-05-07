import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

import agent as agent_module
from unittest.mock import patch, MagicMock


def make_job(job_id=1, script_content="#!/bin/bash\necho hello", timeout=60):
    return {
        "id": job_id,
        "script_content": script_content,
        "timeout_seconds": timeout,
        "script_name": "test-script",
    }


@patch("agent.requests.get")
def test_poll_returns_empty_list(mock_get):
    mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
    result = agent_module.poll_pending_jobs()
    assert result == []


@patch("agent.requests.get")
def test_poll_returns_jobs(mock_get):
    job = make_job()
    mock_get.return_value = MagicMock(status_code=200, json=lambda: [job])
    result = agent_module.poll_pending_jobs()
    assert len(result) == 1
    assert result[0]["id"] == 1


@patch("agent.requests.put")
@patch("agent.requests.get")
def test_run_job_success(mock_get, mock_put):
    mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    job = make_job(script_content="#!/bin/bash\necho hello")
    agent_module.run_job(job)
    put_calls = mock_put.call_args_list
    assert "/start" in put_calls[0][0][0]
    assert "/complete" in put_calls[1][0][0]
    complete_json = put_calls[1][1]["json"]
    assert complete_json["status"] == "success"
    assert complete_json["exit_code"] == 0
    assert "hello" in complete_json["output"]


@patch("agent.requests.put")
@patch("agent.requests.get")
def test_run_job_failure(mock_get, mock_put):
    mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    job = make_job(script_content="#!/bin/bash\nexit 1")
    agent_module.run_job(job)
    put_calls = mock_put.call_args_list
    complete_json = put_calls[1][1]["json"]
    assert complete_json["status"] == "failure"
    assert complete_json["exit_code"] == 1


@patch("agent.requests.put")
@patch("agent.requests.get")
def test_run_job_timeout(mock_get, mock_put):
    mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    job = make_job(script_content="#!/bin/bash\nsleep 100", timeout=1)
    agent_module.run_job(job)
    put_calls = mock_put.call_args_list
    complete_json = put_calls[1][1]["json"]
    assert complete_json["status"] == "timeout"
    assert complete_json["exit_code"] == -1


@patch("agent.requests.put")
@patch("agent.requests.get")
def test_run_job_exports_parameters_as_env(mock_get, mock_put):
    mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    job = make_job(script_content="#!/bin/bash\necho $BACKUP_DAYS")
    job["parameters"] = {"BACKUP_DAYS": "30"}
    agent_module.run_job(job)
    put_calls = mock_put.call_args_list
    complete_json = put_calls[1][1]["json"]
    assert complete_json["status"] == "success"
    assert "30" in complete_json["output"]


@patch("agent.requests.put")
@patch("agent.requests.get")
def test_run_job_does_not_export_agent_token_to_user_scripts(mock_get, mock_put, monkeypatch):
    monkeypatch.setenv("SCRIPTWATCH_AGENT_TOKEN", "local-secret")
    mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
    job = make_job(script_content="#!/bin/bash\necho ${SCRIPTWATCH_AGENT_TOKEN:-missing}")
    agent_module.run_job(job)
    put_calls = mock_put.call_args_list
    complete_json = put_calls[1][1]["json"]
    assert "missing" in complete_json["output"]
    assert "local-secret" not in complete_json["output"]


def test_uninstall_job_exports_callback_env(monkeypatch):
    monkeypatch.setattr(agent_module, "API_URL", "https://scriptwatch.example")
    monkeypatch.setattr(agent_module, "AGENT_TOKEN", "agent-secret")
    env = agent_module._job_env({
        "id": 42,
        "triggered_by": "uninstall",
        "parameters": {},
    })
    assert env["SCRIPTWATCH_API_URL"] == "https://scriptwatch.example"
    assert env["SCRIPTWATCH_AGENT_TOKEN"] == "agent-secret"
    assert env["SCRIPTWATCH_JOB_ID"] == "42"


@patch("agent.requests.post")
def test_heartbeat(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    agent_module.send_heartbeat()
    assert mock_post.called
    url = mock_post.call_args[0][0]
    assert "/heartbeat" in url
