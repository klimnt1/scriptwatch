from api.services.gitea import GiteaClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIPT_STORE_DIR", str(tmp_path / "script-store"))
    return GiteaClient()


def test_get_file_returns_content_and_sha(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    sha = client.create_or_update_file(
        path="plexusprime/test.sh",
        content="#!/bin/bash\necho hello",
        message="Add test.sh via ScriptWatch UI",
    )

    content, fetched_sha = client.get_file("plexusprime/test.sh")
    assert content == "#!/bin/bash\necho hello"
    assert fetched_sha == sha


def test_get_file_returns_none_for_missing_file(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    content, sha = client.get_file("nonexistent/file.sh")
    assert content is None
    assert sha is None


def test_create_file_records_local_version(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    sha = client.create_or_update_file(
        path="plexusprime/new.sh",
        content="#!/bin/bash\necho new",
        message="Add new.sh via ScriptWatch UI",
    )

    commits = client.list_file_commits("plexusprime/new.sh")
    assert len(commits) == 1
    assert commits[0]["sha"] == sha
    assert commits[0]["commit"]["message"] == "Add new.sh via ScriptWatch UI"


def test_update_file_keeps_old_version(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    old_sha = client.create_or_update_file(
        path="plexusprime/existing.sh",
        content="#!/bin/bash\necho old",
        message="Add existing.sh via ScriptWatch UI",
    )
    new_sha = client.create_or_update_file(
        path="plexusprime/existing.sh",
        content="#!/bin/bash\necho updated",
        message="Update existing.sh via ScriptWatch UI",
        sha=old_sha,
    )

    content, fetched_sha = client.get_file("plexusprime/existing.sh")
    old_content, fetched_old_sha = client.get_file("plexusprime/existing.sh", ref=old_sha)
    assert content == "#!/bin/bash\necho updated"
    assert fetched_sha == new_sha
    assert old_content == "#!/bin/bash\necho old"
    assert fetched_old_sha == old_sha


def test_delete_file_removes_current_file_but_keeps_versions(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    sha = client.create_or_update_file(
        path="plexusprime/old.sh",
        content="#!/bin/bash\necho old",
        message="Add old.sh via ScriptWatch UI",
    )
    client.delete_file("plexusprime/old.sh", sha, "Remove old.sh via ScriptWatch UI")

    content, fetched_sha = client.get_file("plexusprime/old.sh")
    version_content, version_sha = client.get_file("plexusprime/old.sh", ref=sha)
    assert content is None
    assert fetched_sha is None
    assert version_content == "#!/bin/bash\necho old"
    assert version_sha == sha
