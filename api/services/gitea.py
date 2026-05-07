import json
import os
import posixpath
from datetime import datetime
from hashlib import sha1

from flask import current_app, has_app_context


class GiteaClient:
    """Local script/version store with the original GiteaClient interface."""

    def __init__(self, base_url=None, token=None, repo_owner=None, repo_name=None):
        configured_root = current_app.config.get("SCRIPT_STORE_DIR") if has_app_context() else None
        self.root = configured_root or os.environ.get("SCRIPT_STORE_DIR") or os.path.join(
            os.environ.get("DATA_DIR", "/app/data"),
            "script-store",
        )
        self.files_root = os.path.join(self.root, "files")
        self.versions_root = os.path.join(self.root, "versions")
        self.meta_path = os.path.join(self.root, "metadata.json")
        os.makedirs(self.files_root, exist_ok=True)
        os.makedirs(self.versions_root, exist_ok=True)

    def _safe_relpath(self, path):
        normalized = posixpath.normpath((path or "").replace("\\", "/")).lstrip("/")
        if normalized in ("", ".") or normalized.startswith("../") or "/../" in normalized:
            raise ValueError("invalid script path")
        return normalized

    def _file_path(self, path):
        return os.path.join(self.files_root, self._safe_relpath(path))

    def _load_meta(self):
        try:
            with open(self.meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {"files": {}}
        data.setdefault("files", {})
        return data

    def _save_meta(self, data):
        os.makedirs(self.root, exist_ok=True)
        tmp_path = f"{self.meta_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.meta_path)

    def _new_sha(self, path, content, message):
        stamp = datetime.utcnow().isoformat(timespec="microseconds")
        return sha1(f"{path}\0{stamp}\0{message}\0{content}".encode()).hexdigest()

    def _version_path(self, sha):
        return os.path.join(self.versions_root, f"{sha}.json")

    def _write_version(self, path, content, sha, message):
        created_at = datetime.utcnow().isoformat() + "Z"
        version = {
            "sha": sha,
            "path": self._safe_relpath(path),
            "content": content,
            "message": message,
            "created_at": created_at,
            "author": {"name": "ScriptWatch", "date": created_at},
        }
        with open(self._version_path(sha), "w", encoding="utf-8") as f:
            json.dump(version, f, indent=2, sort_keys=True)
        return version

    def _read_version(self, sha):
        with open(self._version_path(sha), encoding="utf-8") as f:
            return json.load(f)

    def get_file(self, path, ref=None):
        path = self._safe_relpath(path)
        meta = self._load_meta()
        entry = meta["files"].get(path)
        if ref:
            versions = (entry or {}).get("versions", [])
            sha = next((v for v in versions if v == ref or v.startswith(ref)), ref)
            try:
                version = self._read_version(sha)
            except FileNotFoundError:
                return None, None
            return version.get("content", ""), version["sha"]
        if not entry:
            return None, None
        try:
            with open(self._file_path(path), encoding="utf-8") as f:
                return f.read(), entry.get("sha")
        except FileNotFoundError:
            return None, None

    def list_file_commits(self, path, limit=20):
        path = self._safe_relpath(path)
        entry = self._load_meta()["files"].get(path) or {}
        commits = []
        for sha in reversed(entry.get("versions", [])[-limit:]):
            try:
                version = self._read_version(sha)
            except FileNotFoundError:
                continue
            commits.append({
                "sha": version["sha"],
                "commit": {
                    "message": version.get("message", ""),
                    "author": version.get("author") or {
                        "name": "ScriptWatch",
                        "date": version.get("created_at"),
                    },
                },
            })
        return commits

    def get_commit(self, sha):
        version = self._read_version(sha)
        return {
            "sha": version["sha"],
            "message": version.get("message", ""),
            "created": version.get("created_at"),
            "author": version.get("author") or {"name": "ScriptWatch"},
        }

    def create_or_update_file(self, path, content, message, sha=None):
        path = self._safe_relpath(path)
        meta = self._load_meta()
        new_sha = self._new_sha(path, content, message)
        self._write_version(path, content, new_sha, message)

        file_path = self._file_path(path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        entry = meta["files"].setdefault(path, {"versions": []})
        entry["sha"] = new_sha
        entry["versions"].append(new_sha)
        self._save_meta(meta)
        return new_sha

    def rename_file(self, old_path, new_path, content, old_sha, message):
        old_path = self._safe_relpath(old_path)
        new_path = self._safe_relpath(new_path)
        meta = self._load_meta()
        old_entry = meta["files"].pop(old_path, {"versions": []})
        self._save_meta(meta)
        new_sha = self.create_or_update_file(new_path, content, message)
        meta = self._load_meta()
        new_entry = meta["files"].setdefault(new_path, {"versions": []})
        old_versions = [v for v in old_entry.get("versions", []) if v not in new_entry["versions"]]
        new_entry["versions"] = old_versions + new_entry["versions"]
        new_entry["sha"] = new_sha
        self._save_meta(meta)
        try:
            os.remove(self._file_path(old_path))
        except FileNotFoundError:
            pass
        return new_sha

    def delete_file(self, path, sha=None, message=None):
        path = self._safe_relpath(path)
        meta = self._load_meta()
        meta["files"].pop(path, None)
        self._save_meta(meta)
        try:
            os.remove(self._file_path(path))
        except FileNotFoundError:
            pass
