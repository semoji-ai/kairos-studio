"""Persistent Kairos presentation worker.

This process is launched independently from the Tauri API sidecar. It owns the
PPT queue, survives UI/API restarts, and recovers interrupted jobs after a
worker or machine restart.

좀비 방지 (2026-11): 앱이 실수로 꺼져도 하던 작업은 끝까지 하되, 끝없이 남지는 않는다.
- 앱(사이드카)은 살아 있는 동안 presentations/app.heartbeat 를 주기적으로 갱신한다.
  큐가 비었고 그 하트비트가 APP_GONE_SECONDS 넘게 멈췄으면 워커는 스스로 끝난다.
- presentations/worker.stop 이 생기면 하던 작업만 마치고 끝난다 (Windows에는 SIGTERM으로
  깨끗하게 멈출 방법이 없어서 파일로 요청한다).
- 새 버전 앱이 띄운 워커가 옛 버전 워커를 만나면 worker.stop 을 남기고 자리가 빌 때까지
  기다렸다가 큐를 넘겨받는다 (업데이트 뒤 옛 코드가 PPT를 계속 만드는 문제 방지).
- 중단 후 자동 재개는 MAX_RECOVER_ATTEMPTS 번까지 — 넘으면 실패로 표시하고 사용자가
  '재시도'로 다시 시작한다 (같은 작업이 몇 달씩 처음부터 반복되던 문제 방지).
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import hashlib
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

from core import settings
from core.presentations import PresentationManager

APP_HEARTBEAT = "app.heartbeat"
STOP_FILE = "worker.stop"
APP_GONE_SECONDS = 45.0
MAX_RECOVER_ATTEMPTS = 2
HANDOFF_WAIT_SECONDS = 30 * 60.0
HANDOFF_POLL_SECONDS = 2.0


def code_version() -> str:
    """이 워커가 실행 중인 PPT 코드의 지문 — 앱을 업데이트하면 바뀐다."""
    h = hashlib.sha1()
    here = Path(__file__).resolve().parent
    for name in ("presentation_worker.py", "presentations.py", "presentation_fleet.py"):
        try:
            h.update((here / name).read_bytes())
        except OSError:
            continue
    return h.hexdigest()[:12]


def app_alive(root: Path, gone_after: float = APP_GONE_SECONDS) -> bool:
    try:
        return time.time() - (root / APP_HEARTBEAT).stat().st_mtime < gone_after
    except OSError:
        return False


def touch_app_heartbeat(root: Path) -> None:
    """사이드카가 부른다 — 앱이 켜져 있다는 신호."""
    root.mkdir(parents=True, exist_ok=True)
    (root / APP_HEARTBEAT).write_text(_now(), encoding="utf-8")


def handoff_needed(root: Path, mine: str) -> bool:
    """자리를 쥔 워커가 다른(옛) 버전이면 True."""
    try:
        running = json.loads((root / "worker.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return running.get("code_version") != mine and running.get("state") != "stopped"


def request_stop(root: Path, reason: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / STOP_FILE).write_text(reason, encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SingletonLock(AbstractContextManager):
    def __init__(self, path: Path):
        self.path = path
        self.mutex = None
        if os.name == "nt":
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b" ")
            self.file.flush()
        self.file.seek(0)

    def __enter__(self):
        if os.name == "nt":
            import ctypes

            name_hash = hashlib.sha256(
                str(self.path.resolve()).casefold().encode("utf-8")
            ).hexdigest()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            mutex = kernel32.CreateMutexW(None, False, f"Local\\KairosPptWorker-{name_hash}")
            if not mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(mutex)
                raise BlockingIOError("another presentation worker is already running")
            self.mutex = mutex
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return self

    def __exit__(self, exc_type, exc, tb):
        if os.name == "nt":
            if self.mutex:
                import ctypes

                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self.mutex)
                self.mutex = None
            return False
        try:
            self.file.seek(0)
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
        return False


def _write_worker_state(root: Path, **patch):
    path = root / "worker.json"
    current = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    current.update(patch)
    current["pid"] = os.getpid()
    current["heartbeat"] = _now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _recover_interrupted(manager: PresentationManager) -> set[str]:
    """지난번에 '진행 중'으로 끊긴 작업을 다시 큐에 넣는다 — 횟수 제한."""
    recovered: set[str] = set()
    for job in manager.list():
        if job.get("status") != "running":
            continue
        attempts = int(job.get("recover_attempts") or 0) + 1
        if attempts > MAX_RECOVER_ATTEMPTS:
            manager._write_status(
                job["id"], status="failed", stage="중단이 반복되어 멈춤",
                error=("작업이 여러 번 중간에 끊겨 자동 재시작을 멈췄습니다. "
                       "다시 하려면 '재시도'를 눌러 주세요."),
                recover_attempts=attempts,
            )
            continue
        manager._write_status(
            job["id"], status="queued", stage="백그라운드 워커 재개 대기",
            error=None, recover_attempts=attempts,
        )
        recovered.add(job["id"])
    return recovered


def run_worker(data_dir: Path, bundle_dir: Path | None, poll_seconds: float = 1.0,
               app_gone_seconds: float = APP_GONE_SECONDS):
    manager = PresentationManager(data_dir, bundle_dir, external_worker=True)
    stop = False

    def on_signal(_signum, _frame):
        nonlocal stop
        stop = True

    if threading.current_thread() is threading.main_thread():  # 신호는 메인 스레드에서만
        signal.signal(signal.SIGTERM, on_signal)
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, on_signal)

    root = manager.root
    with SingletonLock(root / "worker.lock"):
        # 넘겨받은 자리라면 옛 워커에게 남긴 정지 요청은 이제 필요 없다
        (root / STOP_FILE).unlink(missing_ok=True)
        _write_worker_state(root, state="idle", started_at=_now(),
                            code_version=code_version(), job_id=None)
        recovered_ids = _recover_interrupted(manager)

        while not stop:
            if (root / STOP_FILE).exists():
                break  # 하던 작업은 이미 끝난 시점 — 새 작업은 잡지 않는다
            queued = [
                job for job in reversed(manager.list())
                if job.get("status") == "queued"
            ]
            if queued:
                job_id = queued[0]["id"]
                _write_worker_state(manager.root, state="working", job_id=job_id)
                manager.run_job(job_id, recovered=job_id in recovered_ids)
                recovered_ids.discard(job_id)
                _write_worker_state(manager.root, state="idle", job_id=None)
            else:
                if not app_alive(root, app_gone_seconds):
                    break  # 앱이 꺼졌고 할 일도 없다 — 좀비로 남지 않는다
                _write_worker_state(manager.root, state="idle", job_id=None)
                time.sleep(poll_seconds)
        _write_worker_state(root, state="stopped", job_id=None)


def main() -> int:
    data_dir = Path(os.environ["KAIROS_DATA_DIR"]).expanduser()
    if "data_dir" in settings.explicit_keys():
        configured = settings.load().get("data_dir")
        if configured:
            data_dir = Path(configured).expanduser()
    bundle = os.environ.get("KAIROS_BUNDLE_DIR")
    root = data_dir / "presentations"
    mine = code_version()
    deadline = None
    while True:
        try:
            run_worker(data_dir, Path(bundle) if bundle else None)
            return 0
        except (BlockingIOError, OSError) as exc:
            if not (getattr(exc, "winerror", None) in {33, 36}
                    or isinstance(exc, BlockingIOError)):
                raise
        # 자리를 쥔 워커가 같은 버전이면 그 워커가 큐를 맡는다
        if deadline is None:
            if not handoff_needed(root, mine):
                return 0
            request_stop(root, f"새 버전 워커({mine})가 교대를 요청했습니다")
            deadline = time.monotonic() + HANDOFF_WAIT_SECONDS
        if time.monotonic() > deadline:
            return 0
        time.sleep(HANDOFF_POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
