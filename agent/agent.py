import hashlib
import os
import signal
import time
import logging
import subprocess
import tempfile
import threading

import requests
from requests import Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

API_URL = os.environ.get("SCRIPTWATCH_API_URL", "http://scriptwatch:8080").rstrip("/")


def _post(url, **kwargs):
    """POST that preserves method through 3xx redirects (handles HTTP→HTTPS)."""
    resp = requests.post(url, allow_redirects=False, **kwargs)
    for _ in range(5):
        if resp.status_code not in (301, 302, 303, 307, 308):
            break
        location = resp.headers.get("Location")
        if not location:
            break
        resp = requests.post(location, allow_redirects=False, **kwargs)
    return resp
SERVER_NAME = os.environ.get("SCRIPTWATCH_SERVER_NAME", "unknown")
AGENT_TOKEN = os.environ.get("SCRIPTWATCH_AGENT_TOKEN", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "30"))
AGENT_VERSION = "1.0.1"
with open(__file__, "rb") as _f:
    AGENT_HASH = hashlib.sha256(_f.read()).hexdigest()

_auth_headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
_last_heartbeat = 0


def _job_env(job):
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("HOME", "LANG", "PATH", "PWD", "SHELL", "TERM", "TMPDIR", "TZ")
        or key.startswith("LC_")
    }
    env["SCRIPTWATCH_JOB_ID"] = str(job.get("id", ""))
    if job.get("triggered_by") in ("system", "uninstall"):
        env["SCRIPTWATCH_API_URL"] = API_URL
        env["SCRIPTWATCH_AGENT_TOKEN"] = AGENT_TOKEN
    env.update({k: str(v) for k, v in (job.get("parameters") or {}).items()})
    return env


def _kill_process_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        proc.kill()


def poll_pending_jobs():
    resp = requests.get(
        f"{API_URL}/api/jobs/pending/{SERVER_NAME}",
        headers=_auth_headers,
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    log.warning("Poll returned %s", resp.status_code)
    return []


def _check_cancel(job_id):
    try:
        resp = requests.get(f"{API_URL}/api/jobs/{job_id}", headers=_auth_headers, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("status") == "cancelling"
    except Exception:
        pass
    return False


def run_job(job):
    job_id = job["id"]
    script_content = job.get("script_content", "")
    timeout = job.get("timeout_seconds", 3600)

    log.info("Starting job %s: %s", job_id, job.get("script_name", ""))

    requests.put(f"{API_URL}/api/jobs/{job_id}/start", headers=_auth_headers, timeout=10)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, dir="/tmp", prefix="sw_"
    ) as f:
        f.write(script_content)
        script_path = f.name

    os.chmod(script_path, 0o700)

    env = _job_env(job)

    status = "success"
    exit_code = 0
    output = ""

    try:
        proc = subprocess.Popen(
            ["/bin/bash", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            start_new_session=True,
        )

        output_buf = []

        def _read(p, buf):
            try:
                buf.append(p.stdout.read())
            except Exception:
                pass

        reader = threading.Thread(target=_read, args=(proc, output_buf), daemon=True)
        reader.start()

        deadline = time.time() + timeout
        while True:
            try:
                proc.wait(timeout=3)
                reader.join(timeout=5)
                output = ("".join(output_buf))[-10000:]
                exit_code = proc.returncode
                status = "success" if exit_code == 0 else "failure"
                log.info("Job %s finished: %s (exit %s)", job_id, status, exit_code)
                break
            except subprocess.TimeoutExpired:
                if _check_cancel(job_id):
                    _kill_process_group(proc)
                    proc.wait()
                    reader.join(timeout=5)
                    output = ("".join(output_buf) + "\n[Cancelled by user]")[-10000:]
                    exit_code = -1
                    status = "cancelled"
                    log.info("Job %s cancelled", job_id)
                    break
                if time.time() >= deadline:
                    _kill_process_group(proc)
                    proc.wait()
                    reader.join(timeout=5)
                    output = f"Job timed out after {timeout}s"
                    exit_code = -1
                    status = "timeout"
                    log.warning("Job %s timed out", job_id)
                    break
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    requests.put(
        f"{API_URL}/api/jobs/{job_id}/complete",
        json={"status": status, "exit_code": exit_code, "output": output},
        headers=_auth_headers,
        timeout=15,
    )


def send_heartbeat():
    resp = _post(
        f"{API_URL}/api/servers/{SERVER_NAME}/heartbeat",
        json={"agent_hash": AGENT_HASH},
        headers=_auth_headers,
        timeout=10,
    )
    if resp.status_code == 404:
        log.warning("Heartbeat 404 — server not found in ScriptWatch, re-registering")
        register()
    elif resp.status_code != 200:
        log.warning("Heartbeat returned %s", resp.status_code)


def register():
    import socket
    hostname = socket.getfqdn()
    resp = _post(
        f"{API_URL}/api/servers/register",
        json={"name": SERVER_NAME, "hostname": hostname, "agent_version": AGENT_VERSION},
        headers=_auth_headers,
        timeout=10,
    )
    if resp.status_code in (200, 201):
        log.info("Registered as '%s' (hostname: %s)", SERVER_NAME, hostname)
    else:
        log.error("Registration failed: HTTP %s — check SCRIPTWATCH_API_URL and SCRIPTWATCH_AGENT_TOKEN", resp.status_code)


def main():
    global _last_heartbeat
    log.info("ScriptWatch agent v%s starting — server: %s", AGENT_VERSION, SERVER_NAME)
    register()

    while True:
        now = time.time()
        if now - _last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                send_heartbeat()
                _last_heartbeat = now
            except Exception as e:
                log.warning("Heartbeat failed: %s", e)

        try:
            jobs = poll_pending_jobs()
            for job in jobs:
                run_job(job)
        except Exception as e:
            log.error("Poll/run error: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
