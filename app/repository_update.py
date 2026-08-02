"""Safe, repository-local update checks for a source checkout.

The service never accepts a repository URL or a branch from the browser.  It
only fast-forwards the canonical checkout and refuses to touch a dirty or
diverged worktree.  Dependency installation and automatic updates happen in
the launcher before the application process starts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any


CANONICAL_ORIGIN = "https://github.com/Kicgut/AiToolbox-You.git"
MAIN_BRANCH = "main"
_UPDATE_LOCK = threading.RLock()


class RepositoryUpdateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def repository_root() -> Path:
    configured = os.environ.get("AI_WORKBENCH_REPOSITORY_ROOT")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[1]


def settings_path() -> Path:
    configured = os.environ.get("AI_WORKBENCH_UPDATE_SETTINGS_PATH")
    return Path(configured) if configured else repository_root() / "data" / "ai_workbench" / "repository_update.json"


def load_settings() -> dict[str, bool]:
    try:
        document = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        document = {}
    return {"auto_update_enabled": bool(document.get("auto_update_enabled", False))}


def save_settings(*, auto_update_enabled: bool) -> dict[str, bool]:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"auto_update_enabled": auto_update_enabled}, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return {"auto_update_enabled": auto_update_enabled}


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryUpdateError("git_unavailable", "Git 不可用，无法检查仓库更新。") from exc
    if completed.returncode:
        message = (completed.stderr or completed.stdout).strip()
        raise RepositoryUpdateError("git_command_failed", message or "Git 命令执行失败。")
    return completed.stdout.strip()


def _normal_origin(value: str) -> str:
    value = value.strip()
    if value.startswith("https://") and "@" in value.split("/", 3)[2]:
        scheme, rest = value.split("://", 1)
        value = scheme + "://" + rest.split("@", 1)[1]
    if value == "git@github.com:Kicgut/AiToolbox-You.git":
        return CANONICAL_ORIGIN
    return value.rstrip("/")


def _base_status(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        raise RepositoryUpdateError("not_a_repository", "当前安装不是 Git 仓库，不能使用仓库内更新。")
    origin = _normal_origin(_git(root, "remote", "get-url", "origin"))
    branch = _git(root, "branch", "--show-current")
    dirty_entries = [line for line in _git(root, "status", "--porcelain").splitlines() if line]
    if origin != CANONICAL_ORIGIN:
        raise RepositoryUpdateError("unsupported_origin", "仅允许更新来自官方 AiToolbox-You 仓库的克隆。")
    return {
        "repository_available": True,
        "origin": CANONICAL_ORIGIN,
        "branch": branch,
        "worktree_clean": not dirty_entries,
        "changed_file_count": len(dirty_entries),
        "auto_update_enabled": load_settings()["auto_update_enabled"],
    }


def check_for_updates(*, refresh: bool) -> dict[str, Any]:
    root = repository_root()
    with _UPDATE_LOCK:
        try:
            result = _base_status(root)
            if refresh:
                _git(root, "fetch", "--quiet", "origin", MAIN_BRANCH)
            remote_known = bool(_git(root, "rev-parse", "--verify", f"origin/{MAIN_BRANCH}"))
            ahead = int(_git(root, "rev-list", "--count", f"origin/{MAIN_BRANCH}..HEAD")) if remote_known else 0
            behind = int(_git(root, "rev-list", "--count", f"HEAD..origin/{MAIN_BRANCH}")) if remote_known else 0
            result.update({
                "checked": refresh,
                "remote_known": remote_known,
                "ahead": ahead,
                "behind": behind,
                "update_available": behind > 0,
                "can_apply": bool(remote_known and behind > 0 and not ahead and result["worktree_clean"] and result["branch"] == MAIN_BRANCH),
                "restart_required": False,
                "error_code": None,
                "message": None,
            })
            return result
        except RepositoryUpdateError as exc:
            return {
                "repository_available": False, "checked": refresh, "remote_known": False,
                "update_available": False, "can_apply": False, "restart_required": False,
                "auto_update_enabled": load_settings()["auto_update_enabled"],
                "error_code": exc.code, "message": exc.message,
            }


def apply_update() -> dict[str, Any]:
    root = repository_root()
    with _UPDATE_LOCK:
        status = check_for_updates(refresh=True)
        if not status["repository_available"]:
            raise RepositoryUpdateError(status["error_code"] or "update_unavailable", status["message"] or "无法更新。")
        if not status["worktree_clean"]:
            raise RepositoryUpdateError("worktree_dirty", "检测到未提交改动；为保护本地工作，已拒绝更新。")
        if status["branch"] != MAIN_BRANCH or status["ahead"]:
            raise RepositoryUpdateError("branch_diverged", "当前分支不是可安全快进的 main；请先手动处理分支。")
        if not status["behind"]:
            return {**status, "updated": False, "restart_required": False, "message": "已是最新版本。"}
        _git(root, "pull", "--ff-only", "origin", MAIN_BRANCH)
        return {**check_for_updates(refresh=False), "updated": True, "restart_required": True, "message": "更新已下载；请重启应用以加载新版本。"}
