"""PPT 워커 좀비 방지: 유휴 종료 · 정지 요청 · 버전 교대 · 재개 횟수 제한."""
from __future__ import annotations

import json
import os
import threading
import time

from core import presentation_worker as pw
from core.presentations import PresentationManager


def _job(root, job_id: str, **status):
    job_dir = root / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "status.json").write_text(json.dumps({
        "id": job_id, "title": "t", "source_name": "a.md",
        "created_at": "2026-11-01T00:00:00+00:00", **status,
    }, ensure_ascii=False), encoding="utf-8")


def _worker_state(root):
    return json.loads((root / "worker.json").read_text(encoding="utf-8"))


def _run_in_thread(tmp_path, **kw):
    t = threading.Thread(target=pw.run_worker, args=(tmp_path, None),
                         kwargs={"poll_seconds": 0.02, **kw}, daemon=True)
    t.start()
    return t


def test_idle_worker_exits_when_app_is_gone(tmp_path):
    # 하트비트가 없으면(앱이 꺼짐) 큐가 빈 워커는 바로 끝난다
    t = _run_in_thread(tmp_path, app_gone_seconds=0.1)
    t.join(timeout=5)
    assert not t.is_alive()
    state = _worker_state(tmp_path / "presentations")
    assert state["state"] == "stopped"
    assert state["code_version"] == pw.code_version()


def test_idle_worker_stays_while_app_heartbeat_is_fresh(tmp_path):
    root = tmp_path / "presentations"
    pw.touch_app_heartbeat(root)
    t = _run_in_thread(tmp_path, app_gone_seconds=30)
    time.sleep(0.3)
    assert t.is_alive()  # 앱이 켜져 있으면 대기
    pw.request_stop(root, "test")
    t.join(timeout=5)
    assert not t.is_alive()  # 정지 요청 파일로 깨끗하게 끝난다
    assert _worker_state(root)["state"] == "stopped"


def test_stale_heartbeat_counts_as_app_gone(tmp_path):
    root = tmp_path / "presentations"
    pw.touch_app_heartbeat(root)
    old = time.time() - 120
    os.utime(root / pw.APP_HEARTBEAT, (old, old))
    assert not pw.app_alive(root, gone_after=45)
    pw.touch_app_heartbeat(root)
    assert pw.app_alive(root, gone_after=45)


def test_interrupted_job_is_requeued_with_attempt_count(tmp_path):
    manager = PresentationManager(tmp_path, external_worker=True)
    _job(manager.root, "aaaaaaaaaaaa", status="running")
    recovered = pw._recover_interrupted(manager)
    assert recovered == {"aaaaaaaaaaaa"}
    job = manager.get("aaaaaaaaaaaa")
    assert job["status"] == "queued" and job["recover_attempts"] == 1


def test_job_interrupted_too_often_is_failed_not_restarted(tmp_path):
    # 같은 작업이 몇 달씩 처음부터 다시 돌던 문제 방지
    manager = PresentationManager(tmp_path, external_worker=True)
    _job(manager.root, "bbbbbbbbbbbb", status="running",
         recover_attempts=pw.MAX_RECOVER_ATTEMPTS)
    assert pw._recover_interrupted(manager) == set()
    job = manager.get("bbbbbbbbbbbb")
    assert job["status"] == "failed"
    assert "재시도" in job["error"]


def test_handoff_needed_only_for_a_different_running_version(tmp_path):
    root = tmp_path / "presentations"
    root.mkdir()
    assert not pw.handoff_needed(root, "new")  # worker.json 없음
    (root / "worker.json").write_text(json.dumps(
        {"state": "idle", "code_version": "old"}), encoding="utf-8")
    assert pw.handoff_needed(root, "new")
    assert not pw.handoff_needed(root, "old")
    (root / "worker.json").write_text(json.dumps(
        {"state": "idle"}), encoding="utf-8")  # 버전 기록 전의 옛 워커
    assert pw.handoff_needed(root, "new")


def test_new_worker_clears_leftover_stop_request(tmp_path):
    root = tmp_path / "presentations"
    pw.request_stop(root, "옛 워커에게 남긴 요청")
    t = _run_in_thread(tmp_path, app_gone_seconds=0.1)
    t.join(timeout=5)
    assert not (root / pw.STOP_FILE).exists()
