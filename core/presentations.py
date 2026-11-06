"""Lecture document intake and PPT Master orchestration."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core import providers
from core.doc_convert import extract_text
from core.presentation_styles import (
    default_image_style,
    default_presentation_style,
    get_image_style,
    get_presentation_style,
    image_style_prompt,
    list_image_styles,
    list_presentation_styles,
    presentation_style_prompt,
)

_SUPPORTED = {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown"}
_JOBS_LOCK = threading.Lock()

# 역할 분담: hybrid = Opus(Claude)가 아트 디렉션(디자인 명세·이미지 프롬프트)을 잡고
# Codex가 그 명세대로 슬라이드를 제작한다. 이미지는 어느 경우든 Codex 이미지 모델이 그린다.
PROVIDERS = {"hybrid", "codex", "claude"}
PROVIDER_LABELS = {"claude": "Opus", "codex": "Codex"}


# 'AI 사진'처럼 보이지 않게 — 설계(아트 디렉션)·수정 계획 단계에서 쓴다
IMAGE_CRAFT = (
    "## 이미지 프롬프트 작성 원칙 — 'AI 사진'처럼 보이지 않게\n"
    "생성 이미지가 흔히 AI처럼 보이는 이유는 모든 장면에 같은 조명, 과한 대비와 채도, "
    "매끈한 피부, 정면 중앙 포즈, 비어 있는 듯 깨끗한 공간이 반복되기 때문입니다. "
    "실제 사진가가 현장에서 찍은 것처럼 쓰세요.\n"
    "- 빛: 장면마다 빛의 출처를 먼저 정하고 그 빛으로만 묘사하세요 "
    "(예: 흐린 오전 창으로 들어오는 확산광, 늦은 오후 낮게 깔리는 햇빛, 저녁 식탁 위 "
    "백열 펜던트등, 교실 형광등과 창가 자연광의 섞임). 시간대·날씨·실내외가 다르면 "
    "빛도 달라야 합니다. 덱의 통일감은 아래 Visual DNA(카메라·색 응답)가 맡습니다.\n"
    "- 대비: 사람 눈으로 보는 수준의 자연스러운 대비 — 그림자는 깊되 안의 디테일이 "
    "보이고, 하이라이트는 부드럽게 넘어가게. HDR처럼 모든 곳이 밝은 화면, 과포화, "
    "청록-주황 색보정 대신 실제 장소의 색을 그대로 기술하세요.\n"
    "- 사람: 연출되지 않은 순간 — 무언가를 하고 있는 손, 서로를 보거나 다른 곳을 보는 "
    "시선, 사선 시점, 프레임 가장자리에 걸린 인물. 피부는 결과 잔주름, 옷은 구김과 "
    "닳은 자국까지 보이게.\n"
    "- 공간: 생활감 있는 실제 장소의 구체적 디테일(손때 묻은 책상, 벽의 달력, 반쯤 "
    "마신 찻잔)을 두세 가지 넣으세요. 원고 내용(가정·교회·교실 등)에 맞는 한국의 "
    "일상 공간이면 더 좋습니다.\n"
    "- 표현: Prompt Kit tier 0 검증 때문에 prompt 안에서는 영어 부정 표현 "
    "(`no`, `without`, `avoid`, `exclude`, `never`, `free of`, `devoid of`, `do not`, "
    "`don't`)을 쓰지 말고 원하는 상태만 긍정형으로 쓰세요. 이미지 안에 글자는 넣지 "
    "않습니다(제목·본문은 편집 가능한 SVG 텍스트).\n"
)


# PowerPoint 변환에서 실제로 깨졌던 지점들 — 슬라이드를 만드는 단계에서만 쓴다
BUILD_QA = """
## 제작 QA (PowerPoint 변환에서 실제로 깨졌던 지점)
한글 원고가 주언어이면 구조적 제목·부제·본문은 설치된 `Noto Sans KR` 한 서체로
통일하고, 제목 700·본문 400/500처럼 굵기로 위계를 만드세요. 한글 구조 텍스트에
`Aptos`, `Aptos Display`, `Malgun Gothic`을 섞지 마세요. 제목과 부제는 각각 의도한
모듈 폭을 가진 별도 프레임으로 두고, 실제 한글 글자 폭을 기준으로 줄바꿈한 뒤 최소
16px의 시각 간격을 확보하세요. 본문 프레임은 컨테이너 안쪽 여백과 예상 줄 수를
반영한 폭·높이를 가져야 하며 글자가 카드 밖으로 잘리면 안 됩니다.
FLOW·단계·수렴 다이어그램은 항목 중심점, 동일 간격, 연결선 시작/끝점, 결과 박스의
수직 중심을 수치로 맞추고, 모든 라벨과 설명이 각 도형 안에서 완전히 보여야 합니다.
숫자 원·배지는 숫자 글리프의 시각 중심을 원 중심에 맞추세요. SVG 텍스트 기준선은
`y = circle cy + 약 0.32 × font-size`를 출발점으로 실제 렌더를 확인하세요. 카드 제목이
넘치면 글자 크기를 과도하게 줄이지 말고 의미 단위로 수동 줄바꿈하고 카드 높이와 아래
본문 위치를 함께 조정하세요. SVG 캔버스 검사 통과만으로 완료하지 말고 PowerPoint 변환
후 텍스트 재배치까지 고려해 넉넉한 프레임을 설계하세요.
원본 이미지는 의미와 출처를 유지해 우선 활용하되, 생성 이미지와 함께 쓰일 때는 동일한
크롭 비율·모서리·여백 체계로 프레이밍해 한 덱의 시각 언어로 보이게 하세요. 표는
가능하면 편집 가능한 표로 만드세요.
"""


def normalize_provider(value) -> str:
    value = str(value or "hybrid")
    return value if value in PROVIDERS else "hybrid"


def phase_providers(provider: str) -> tuple[str, str]:
    """(설계 담당, 제작 담당) — 이미지 없는 한 번짜리 실행은 설계 담당이 맡는다."""
    provider = normalize_provider(provider)
    if provider == "hybrid":
        return "claude", "codex"
    return provider, provider


_IO_RETRIES = 20
_IO_RETRY_SECONDS = 0.05


def _replace_with_retry(src: Path, dst: Path) -> None:
    """Windows에서는 누가 dst를 열어 둔 순간 교체가 PermissionError로 실패한다 — 잠깐 뒤 다시."""
    for attempt in range(_IO_RETRIES):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if attempt + 1 == _IO_RETRIES:
                raise
            time.sleep(_IO_RETRY_SECONDS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", Path(name).name).strip(".-")
    return cleaned[:120] or "lecture"


def normalize_document(source: Path, out_dir: Path) -> dict:
    suffix = source.suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")
    out_dir.mkdir(parents=True, exist_ok=True)
    text, assets = extract_text(source, out_dir)

    md_path = out_dir / "lecture.md"
    md_path.write_text(text, encoding="utf-8")
    manifest = {
        "source": source.name,
        "markdown": md_path.name,
        "assets": assets,
        "created_at": _now(),
    }
    (out_dir / "assets.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class PresentationManager:
    def __init__(self, data_dir: Path, bundle_dir: Path | None = None,
                 external_worker: bool | None = None):
        self.root = data_dir / "presentations"
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundle_dir = bundle_dir
        self.external_worker = (
            os.environ.get("KAIROS_PRESENTATION_EXTERNAL_WORKER") == "1"
            if external_worker is None else external_worker
        )
        self._stream_logs: dict[str, tuple[list[str], str]] = {}

    def _engine_dir(self, name: str) -> Path | None:
        env = os.environ.get(f"KAIROS_{name.upper().replace('-', '_')}_DIR")
        candidates = [Path(env).expanduser()] if env else []
        if self.bundle_dir:
            candidates.append(self.bundle_dir / name)
        candidates.append(Path(__file__).resolve().parent.parent / "vendor" / name)
        candidates.append(Path(__file__).resolve().parent.parent.parent / name)
        if os.name == "nt":
            candidates.append(Path("D:/projects") / name)
        return next((p.resolve() for p in candidates if p.is_dir()), None)

    def engines(self) -> dict:
        ppt = self._engine_dir("ppt-master")
        fleet = self._engine_dir("codex-fleet")
        prompt_kit = self._engine_dir("gongnyang-prompt-kit")
        worker = self.worker_status()
        return {
            "ppt_master": {"available": bool(ppt), "path": str(ppt) if ppt else None},
            "codex_fleet": {"available": bool(fleet), "path": str(fleet) if fleet else None},
            "prompt_kit": {"available": bool(prompt_kit), "path": str(prompt_kit) if prompt_kit else None},
            "worker": worker,
            "styles": list_presentation_styles(),
            "default_style": default_presentation_style(),
            "image_styles": list_image_styles(),
            "default_image_style": default_image_style(),
        }

    def worker_status(self) -> dict:
        path = self.root / "worker.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            heartbeat = datetime.fromisoformat(str(state["heartbeat"]))
            alive = (datetime.now(timezone.utc) - heartbeat).total_seconds() < 10
            if not alive and state.get("state") == "working":
                try:
                    alive = _pid_alive(int(state["pid"]))
                except (TypeError, ValueError):
                    alive = False
            return {**state, "available": alive}
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return {"available": not self.external_worker}

    def _job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _status_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "status.json"

    def _write_status(self, job_id: str, **patch) -> dict:
        with _JOBS_LOCK:
            path = self._status_path(job_id)
            current = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
            current.update(patch)
            current["updated_at"] = _now()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            _replace_with_retry(tmp, path)
            return current

    def get(self, job_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            return None
        path = self._status_path(job_id)
        # 같은 프로세스의 쓰기와 겹치지 않게 잠그고, 다른 프로세스(PPT 워커)가 바꾸는 순간에
        # 걸리면 잠깐 뒤 다시 읽는다 — Windows는 열려 있는 파일을 교체·읽기할 때 실패한다.
        for attempt in range(_IO_RETRIES):
            with _JOBS_LOCK:
                if not path.is_file():
                    if attempt + 1 < _IO_RETRIES and path.with_suffix(".tmp").is_file():
                        pass  # 교체 중 — 다시 시도
                    else:
                        return None
                else:
                    try:
                        return json.loads(path.read_text(encoding="utf-8-sig"))
                    except (OSError, json.JSONDecodeError):
                        pass
            time.sleep(_IO_RETRY_SECONDS)
        return None

    def list(self) -> list[dict]:
        jobs = []
        for path in self.root.glob("*/status.json"):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)

    def create(self, filename: str, content: bytes, options: dict,
               prepare=None, extra: dict | None = None) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in _SUPPORTED:
            raise ValueError("PDF, DOCX, HWP, HWPX, MD 파일만 지원합니다")
        if not content:
            raise ValueError("빈 파일입니다")
        if len(content) > 100 * 1024 * 1024:
            raise ValueError("파일은 100MB 이하여야 합니다")
        style = get_presentation_style(str(options.get("style_preset") or ""))
        options = dict(options)
        options["style_preset"] = style["id"]
        image_style = get_image_style(str(options.get("image_style") or ""))
        options["image_style"] = image_style["id"]
        if not str(options.get("tone") or "").strip():
            options["tone"] = style.get("tone") or "명료하고 현대적인 교육 자료"
        options["provider"] = normalize_provider(options.get("provider"))
        job_id = uuid.uuid4().hex[:12]
        job_dir = self._job_dir(job_id)
        upload_dir = job_dir / "upload"
        upload_dir.mkdir(parents=True)
        safe_name = _safe_name(filename)
        source = upload_dir / safe_name
        source.write_bytes(content)
        if prepare:
            prepare(job_dir)  # 수정본: 원본 프로젝트를 복사해 둔다 (작업 시작 전에)
        status = self._write_status(
            job_id,
            id=job_id,
            title=str(options.get("title") or source.stem)[:120],
            source_name=safe_name,
            status="queued",
            stage="업로드 완료",
            progress=5,
            provider=options["provider"],
            options=options,
            created_at=_now(),
            log=[],
            result=None,
            error=None,
            **(extra or {}),
        )
        self._dispatch(job_id, source, options)
        return status

    def remake(self, job_id: str, provider: str | None = None) -> dict:
        """같은 원고·설정으로 새 작업을 만든다 (원래 결과는 그대로 남는다)."""
        parent = self.get(job_id)
        if not parent:
            raise ValueError("작업을 찾을 수 없습니다")
        if parent.get("status") in {"queued", "running"}:
            raise ValueError("제작 중인 작업은 다시 만들 수 없습니다")
        source = self._job_dir(job_id) / "upload" / str(parent["source_name"])
        if not source.is_file():
            raise ValueError("원본 업로드 파일을 찾을 수 없습니다")
        options = {k: v for k, v in dict(parent.get("options") or {}).items()
                   if k not in {"revision_request", "revision_of"}}
        options["title"] = parent.get("root_title") or parent.get("title") or source.stem
        if provider:
            options["provider"] = provider
        return self.create(parent["source_name"], source.read_bytes(), options,
                           extra={"remade_from": job_id})

    def revise(self, job_id: str, request: str) -> dict:
        """완성된 덱에 수정 요청을 반영한 새 버전을 만든다 — 원본 프로젝트를 복사해서."""
        parent = self.get(job_id)
        if not parent:
            raise ValueError("작업을 찾을 수 없습니다")
        if parent.get("status") != "completed":
            raise ValueError("완성된 작업만 수정할 수 있습니다")
        request = str(request or "").strip()
        if not request:
            raise ValueError("수정할 내용을 적어 주세요")
        if len(request) > 2000:
            raise ValueError("수정 요청은 2,000자 이내로 적어 주세요")
        parent_workspace = self._job_dir(job_id) / "workspace"
        if not parent_workspace.is_dir():
            raise ValueError("원본 PPT 프로젝트를 찾을 수 없습니다")
        source = self._job_dir(job_id) / "upload" / str(parent["source_name"])
        if not source.is_file():
            raise ValueError("원본 업로드 파일을 찾을 수 없습니다")
        revision = int(parent.get("revision") or 0) + 1
        root_title = parent.get("root_title") or parent.get("title") or source.stem
        options = dict(parent.get("options") or {})
        options.update(revision_request=request, revision_of=job_id,
                       title=f"{root_title} (수정 {revision})")

        def copy_project(job_dir: Path):
            shutil.copytree(parent_workspace, job_dir / "workspace")

        return self.create(parent["source_name"], source.read_bytes(), options,
                           prepare=copy_project,
                           extra={"revision_of": job_id, "revision": revision,
                                  "root_title": root_title, "revision_request": request})

    def retry(self, job_id: str) -> dict:
        current = self.get(job_id)
        if not current:
            raise ValueError("작업을 찾을 수 없습니다")
        if current.get("status") not in {"failed"}:
            raise ValueError("실패한 작업만 재시도할 수 있습니다")
        source = self._job_dir(job_id) / "upload" / str(current["source_name"])
        if not source.is_file():
            raise ValueError("원본 업로드 파일을 찾을 수 없습니다")
        workspace = self._job_dir(job_id) / "workspace"
        if workspace.is_dir():
            shutil.rmtree(workspace)
        # 재시도는 새로 시작한다 — 화면에 남던 이전 실패 로그·오류는 지우고, 원인 추적용으로
        # 마지막 몇 번의 실패 기록만 retry_history 에 남긴다 (화면에는 보이지 않음).
        history = list(current.get("retry_history") or [])
        if current.get("error"):
            history.append({"at": _now(), "error": str(current["error"])[:2000]})
        self._write_status(job_id, status="queued", stage="재시도 대기 중", progress=5,
                           error=None, recover_attempts=0, retry_history=history[-5:],
                           log=["작업을 처음부터 다시 시작합니다\n"])
        self._dispatch(job_id, source, dict(current.get("options") or {}))
        return self.get(job_id) or current

    def _dispatch(self, job_id: str, source: Path, options: dict):
        if self.external_worker:
            return
        threading.Thread(
            target=self._run, args=(job_id, source, options), daemon=True,
        ).start()

    def run_job(self, job_id: str, recovered: bool = False) -> dict:
        current = self.get(job_id)
        if not current:
            raise ValueError("작업을 찾을 수 없습니다")
        if current.get("status") not in {"queued", "running"}:
            return current
        source = self._job_dir(job_id) / "upload" / str(current["source_name"])
        if not source.is_file():
            self._write_status(
                job_id, status="failed", stage="실패",
                error="원본 업로드 파일을 찾을 수 없습니다",
            )
            return self.get(job_id) or current
        if recovered:
            workspace = self._job_dir(job_id) / "workspace"
            if workspace.is_dir():
                shutil.rmtree(workspace)
        self._write_status(
            job_id, status="running", stage="백그라운드 워커가 작업 시작",
            worker_pid=os.getpid(), error=None,
        )
        self._run(job_id, source, dict(current.get("options") or {}))
        return self.get(job_id) or current

    def _log(self, job_id: str, text: str):
        current = self.get(job_id) or {}
        logs = list(current.get("log") or [])
        logs.append(text[-2000:] + "\n")
        self._write_status(job_id, log=logs[-80:])

    def _begin_stream_log(self, job_id: str):
        current = self.get(job_id) or {}
        self._stream_logs[job_id] = (list(current.get("log") or [])[-79:], "")

    def _stream_log(self, job_id: str, text: str, project: Path, slide_count: int):
        base, accumulated = self._stream_logs.get(job_id, ([], ""))
        accumulated = (accumulated + text)[-12000:]
        self._stream_logs[job_id] = (base, accumulated)
        current = self.get(job_id) or {}
        progress = int(current.get("progress") or 40)
        stage = str(current.get("stage") or "슬라이드 설계 중")
        if (project / "design_spec.md").is_file():
            progress = max(progress, 45)
            stage = "슬라이드 설계 확정 중"
        image_manifest = project / "images" / "image_prompts.json"
        if image_manifest.is_file():
            try:
                image_items = json.loads(image_manifest.read_text(encoding="utf-8")).get("items") or []
            except (OSError, json.JSONDecodeError):
                image_items = []
            generated = sum(
                1 for item in image_items
                if (project / "images" / Path(str(item.get("filename", ""))).name).is_file()
            )
            if image_items:
                progress = max(progress, 48 + int(17 * generated / len(image_items)))
                stage = f"AI 이미지 생성 중 ({generated}/{len(image_items)})"
        svg_count = len(list((project / "svg_output").glob("*.svg")))
        if svg_count:
            total = max(1, slide_count)
            progress = max(progress, 66 + min(24, int(24 * svg_count / total)))
            stage = f"슬라이드 제작 중 ({min(svg_count, total)}/{total})"
        if list((project / "exports").glob("*.pptx")):
            progress = max(progress, 95)
            stage = "PowerPoint 최종 검사 중"
        self._write_status(
            job_id, log=(base + [accumulated])[-80:],
            progress=progress, stage=stage,
        )

    def _run(self, job_id: str, source: Path, options: dict):
        try:
            normalized = self._job_dir(job_id) / "normalized"
            self._write_status(job_id, status="running", stage="문서와 이미지 추출 중", progress=12)
            manifest = normalize_document(source, normalized)
            self._log(job_id, f"Markdown 변환 완료 · 이미지 {len(manifest['assets'])}개")

            if os.environ.get("KAIROS_PRESENTATION_FAKE") == "1":
                result = self._job_dir(job_id) / "result.pptx"
                result.write_bytes(b"PK\x03\x04fake-pptx")
                self._write_status(job_id, status="completed", stage="완료", progress=100,
                                   result=str(result), project_dir=str(normalized))
                return

            ppt_root = self._engine_dir("ppt-master")
            fleet_root = self._engine_dir("codex-fleet")
            prompt_kit = self._engine_dir("gongnyang-prompt-kit")
            if not ppt_root:
                raise RuntimeError("ppt-master를 찾을 수 없습니다")
            if options.get("use_ai_images", True) and not fleet_root:
                raise RuntimeError("codex-fleet를 찾을 수 없습니다")
            if options.get("use_ai_images", True) and not prompt_kit:
                raise RuntimeError("gongnyang-prompt-kit을 찾을 수 없습니다")

            pm_script = ppt_root / "skills" / "ppt-master" / "scripts" / "project_manager.py"
            base = self._job_dir(job_id) / "workspace"
            slug = "lecture"
            fmt = "ppt43" if options.get("aspect") == "4:3" else "ppt169"
            base.mkdir(parents=True, exist_ok=True)
            existing = sorted(
                (path for path in base.iterdir()
                 if path.is_dir() and (path / "sources").is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if existing:
                project = existing[0]
                self._write_status(
                    job_id, stage="기존 PPT Master 프로젝트에서 재개 중", progress=25,
                )
            else:
                self._write_status(job_id, stage="PPT Master 프로젝트 준비 중", progress=25)
                try:
                    subprocess.run([sys.executable, str(pm_script), "init", slug,
                                    "--format", fmt, "--dir", str(base)],
                                   check=True, capture_output=True, timeout=180,
                                   stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or exc.stdout or "").strip()
                    raise RuntimeError(f"PPT Master 프로젝트 초기화 실패: {detail[-1200:]}") from exc
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError("PPT Master 프로젝트 초기화가 180초 안에 끝나지 않았습니다") from exc
                project = next(
                    path for path in base.iterdir()
                    if path.is_dir() and (path / "sources").is_dir()
                )
            shutil.copy2(normalized / "lecture.md", project / "sources" / "lecture.md")
            shutil.copy2(normalized / "assets.json", project / "sources" / "assets.json")
            if (normalized / "assets").is_dir():
                for asset in (normalized / "assets").iterdir():
                    shutil.copy2(asset, project / "images" / asset.name)

            helper = Path(__file__).resolve().parent / "presentation_fleet.py"
            # Kairos vendors the codex-fleet runner entrypoint so compatibility
            # fixes (for example Codex's current `call_*.png` output names) do
            # not depend on an external checkout being updated in lockstep.
            runner = Path(__file__).resolve().parent / "codex_imagegen_runner.py"
            if not runner.is_file():
                runner = (fleet_root / "runners" / "codex_imagegen_runner.py") if fleet_root else None
            plan_provider, build_provider = phase_providers(options.get("provider"))
            plan_label = PROVIDER_LABELS[plan_provider]
            build_label = PROVIDER_LABELS[build_provider]
            cfg = {
                "workspace_dir": str(project),
                "codex_sandbox": "workspace-write",
                "claude_permission_mode": "acceptEdits",
                "claude_allowed_tools": [
                    f"Bash({sys.executable} {ppt_root / 'skills' / 'ppt-master' / 'scripts'}/*:*)",
                    f"Bash({sys.executable} {helper}:*)",
                ],
                # Claude는 헤드리스에서 작업 폴더 밖 문서를 읽으려면 미리 열어 둬야 한다
                "claude_add_dirs": [str(d) for d in (ppt_root, prompt_kit) if d],
            }
            self._begin_stream_log(job_id)

            def run_agent(agent_prompt: str, stage: str, progress: int, provider_name: str):
                self._write_status(
                    job_id, stage=stage, progress=progress, project_dir=str(project),
                )
                final = None
                for event in providers.get(provider_name).chat(agent_prompt, cfg=cfg):
                    if event["type"] in {"delta", "progress"}:
                        self._stream_log(
                            job_id, event.get("text", ""), project,
                            int(options.get("slide_count") or 10),
                        )
                    elif event["type"] == "error":
                        raise RuntimeError(event.get("error", "에이전트 실행 실패"))
                    elif event["type"] == "done":
                        final = event
                if not final:
                    raise RuntimeError("에이전트가 결과 없이 종료했습니다")

            def export_pptx():
                """Run PPT Master's exporter outside the nested Codex session."""
                exporter = (
                    ppt_root / "skills" / "ppt-master" / "scripts" / "svg_to_pptx.py"
                )
                if not exporter.is_file():
                    raise RuntimeError(f"PPTX exporter not found: {exporter}")
                export_result = subprocess.run(
                    [sys.executable, str(exporter), str(project)],
                    cwd=str(project),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=300,
                )
                if export_result.returncode:
                    detail = (
                        export_result.stderr or export_result.stdout or ""
                    ).strip()
                    raise RuntimeError(f"PPTX export failed: {detail[-2400:]}")

            def run_image_fleet(image_manifest: Path, image_style_lock: Path):
                """manifest의 이미지를 독립 워커(Codex 이미지 모델)로 생성하고 결과를 검증한다.
                이미 있는 PNG는 러너가 건너뛰므로 수정본에서는 바뀐 항목만 새로 그린다."""
                self._write_status(
                    job_id, stage="독립 워커가 AI 이미지 생성 중 (0/5)", progress=48,
                )
                fleet_result = subprocess.run(
                    [
                        sys.executable, str(helper),
                        "--manifest", str(image_manifest),
                        "--outdir", str(project / "images"),
                        "--runner", str(runner),
                        "--prompt-kit", str(prompt_kit),
                        "--style-lock", str(image_style_lock),
                    ],
                    cwd=str(project),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=1500,
                )
                if fleet_result.returncode:
                    detail = (fleet_result.stderr or fleet_result.stdout or "").strip()
                    raise RuntimeError(f"AI 이미지 생성 실패: {detail[-2400:]}")
                image_payload = json.loads(image_manifest.read_text(encoding="utf-8"))
                image_items = image_payload.get("items") or []
                missing = [
                    Path(str(item.get("filename", ""))).name
                    for item in image_items
                    if item.get("status") != "Generated"
                    or not (project / "images" / Path(
                        str(item.get("filename", ""))
                    ).name).is_file()
                ]
                if not image_items or missing:
                    raise RuntimeError(
                        f"AI 이미지 결과가 불완전합니다: {', '.join(missing) or 'manifest 비어 있음'}"
                    )
                self._write_status(
                    job_id,
                    stage=f"AI 이미지 생성 완료 ({len(image_items)}/{len(image_items)})",
                    progress=65,
                )

            use_ai = bool(options.get("use_ai_images", True))
            if options.get("revision_request"):
                # 수정본: 복사해 온 완성 프로젝트에 요청만 반영한다
                run_agent(
                    self._revision_prompt(project, ppt_root, helper, runner, prompt_kit,
                                          options, phase="plan"),
                    f"{plan_label}가 수정 요청 반영 계획 중", 40, plan_provider,
                )
                image_manifest = project / "images" / "image_prompts.json"
                image_style_lock = project / "images" / "image_style_lock.json"
                if (use_ai and runner and prompt_kit and image_manifest.is_file()
                        and image_style_lock.is_file()):
                    payload = json.loads(image_manifest.read_text(encoding="utf-8"))
                    changed = [
                        item for item in payload.get("items") or []
                        if item.get("status") != "Generated"
                        or not (project / "images" / Path(
                            str(item.get("filename", ""))).name).is_file()
                    ]
                    if changed:
                        run_image_fleet(image_manifest, image_style_lock)
                run_agent(
                    self._revision_prompt(project, ppt_root, helper, runner, prompt_kit,
                                          options, phase="execute"),
                    f"{build_label}가 슬라이드 수정 중", 66, build_provider,
                )
                self._write_status(job_id, stage="PPTX 내보내기 중", progress=94)
                export_pptx()
            elif use_ai:
                if not runner or not runner.is_file() or not prompt_kit:
                    raise RuntimeError("AI 이미지 생성 실행 파일을 찾을 수 없습니다")
                selected_image_style = get_image_style(
                    str(options.get("image_style") or "")
                )
                image_style_lock = project / "images" / "image_style_lock.json"
                image_style_lock.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "image_style_id": selected_image_style["id"],
                            "name": selected_image_style["name"],
                            "visual_dna": selected_image_style["visual_dna"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                        phase="plan",
                    ),
                    f"{plan_label}가 슬라이드·이미지 아트 디렉션 중",
                    40,
                    plan_provider,
                )
                image_manifest = project / "images" / "image_prompts.json"
                if not image_manifest.is_file():
                    raise RuntimeError("이미지 설계 manifest가 생성되지 않았습니다")
                run_image_fleet(image_manifest, image_style_lock)
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                        phase="execute",
                    ),
                    f"{build_label}가 슬라이드 제작 중",
                    66,
                    build_provider,
                )
                self._write_status(
                    job_id, stage="PPTX 내보내기 중", progress=94,
                )
                export_pptx()
            else:
                run_agent(
                    self._agent_prompt(
                        project, ppt_root, helper, runner, prompt_kit, options,
                    ),
                    f"{plan_label}가 슬라이드 설계·제작 중",
                    40,
                    plan_provider,
                )

            exports = sorted(project.glob("exports/*.pptx"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            if not exports:
                raise RuntimeError("PPT Master가 PPTX를 생성하지 못했습니다")
            result = self._job_dir(job_id) / f"{_safe_name(options.get('title') or source.stem)}.pptx"
            shutil.copy2(exports[0], result)
            self._write_status(job_id, status="completed", stage="완료", progress=100,
                               result=str(result))
        except Exception as exc:
            self._write_status(job_id, status="failed", stage="실패", error=str(exc))
        finally:
            self._stream_logs.pop(job_id, None)

    @staticmethod
    def _agent_prompt(project: Path, ppt_root: Path, helper: Path,
                      runner: Path | None, prompt_kit: Path | None,
                      options: dict, phase: str = "full") -> str:
        """단계별 에이전트 지시문.

        plan(설계) — 아트 디렉터: 원고를 읽고 디자인 명세와 이미지 프롬프트를 잡는다
                     (hybrid 모드에서는 Opus). 세부 레이아웃 규칙으로 묶지 않고 판단을 맡긴다.
        execute(제작) — 명세를 그대로 구현하는 제작자 (hybrid 모드에서는 Codex).
                     PowerPoint 변환에서 실제로 깨졌던 지점의 QA 규칙은 여기서만 준다.
        """
        use_ai = bool(options.get("use_ai_images", True) and runner and prompt_kit)
        target_assets = max(3, min(6, (int(options.get("slide_count") or 10) + 1) // 2))


        if use_ai and phase == "execute":
            image_instruction = (
                "독립 백그라운드 워커가 `images/image_prompts.json`의 모든 AI 이미지를 "
                "이미 생성했고 각 항목을 `Generated`로 검증했습니다. manifest와 실제 PNG를 "
                "읽어 계획된 슬라이드에 배치하세요. 이미지 프롬프트를 수정하거나 Fleet, "
                "imagegen, image_gen.py를 다시 실행하지 마세요. 기존 `design_spec.md`와 "
                "`spec_lock.md`를 이어받아 SVG 제작, 검증, 후처리, PPTX export를 완료하세요. "
                "사진은 명세에 적힌 크롭·배치 그대로 쓰고, 색 오버레이나 필터로 톤을 바꾸지 마세요."
            )
        elif use_ai:
            image_instruction = (
                "AI 시각 자산 생성은 사용자가 선택한 필수 제작 단계이며 생략할 수 없습니다. "
                f"이미지 목적과 배치가 정해지면 Prompt Kit `{prompt_kit / 'skills' / 'image-prompt' / 'SKILL.md'}`를 "
                "처음부터 끝까지 읽고, 라우팅 규칙에 따라 C12와 선택한 룩 프리셋 및 필요한 "
                "참조 문서를 읽은 뒤 각 장면을 Prompt Kit 포맷 A의 완성 프롬프트로 쓰세요. "
                "최종 prompt는 반드시 `AR 16:9`로 끝나야 합니다. "
                f"약 {target_assets}개의 핵심 시각 자산을 계획하세요 — 표지 히어로 이미지와 "
                "강의의 핵심 장면 위주로, 모든 장에 장식 이미지를 반복하지 마세요.\n"
                + IMAGE_CRAFT +
                "맞춤형 스폿 아이콘이나 오브젝트가 꼭 필요하면 배경 분리가 쉬운 단색 배경의 독립 "
                "피사체로 생성하고, 일반 UI 아이콘은 PPT Master의 벡터 아이콘을 사용하세요. "
                "PPT Master 규칙대로 `design_spec.md`, `spec_lock.md`, "
                "`images/image_prompts.json`을 작성하고 manifest의 항목은 `Pending`으로 두세요. "
                "이 계획 단계에서는 Fleet, imagegen, image_gen.py를 실행하지 말고 SVG나 PPTX도 "
                "아직 만들지 마세요. 필요한 이미지와 배치 설계가 끝나면 최종 답변을 정확히 "
                "`KAIROS_IMAGE_PLAN_READY`로 마치세요. 이미지 생성은 독립 워커가 다음 단계에서 "
                "수행합니다."
            )
        else:
            image_instruction = "원본 문서에서 추출된 이미지만 사용하세요."

        if phase == "plan":
            route_instruction = (
                "당신은 이 덱의 아트 디렉터입니다. 이번 단계에서는 Generate PPTX의 "
                "Strategist/이미지 계획 단계까지만 수행하세요. 원고를 끝까지 읽고 강의의 흐름, "
                "슬라이드별 역할, 타이포그래피·색·여백의 위계, 이미지의 장면과 배치를 직접 "
                "판단해 정하세요. 아래 디자인 시스템은 출발점입니다 — 색과 서체는 지키되, "
                "레이아웃과 구성은 오늘날 잘 만든 강연 자료(애플 키노트, TED, 고급 매거진 "
                "편집)의 감각으로 원고에 맞게 새로 설계하세요. 제작자(다른 에이전트)가 이 명세만 "
                "보고 그대로 구현할 수 있게 `design_spec.md`와 `spec_lock.md`에 슬라이드마다 "
                "레이아웃·텍스트 위치·이미지 크롭을 구체적으로 적으세요."
            )
            finish_instruction = (
                "SVG 검증이나 PPTX export는 수행하지 말고 이미지 계획 준비 완료를 알리세요."
            )
        elif phase == "execute":
            route_instruction = (
                "당신은 제작자입니다. 아트 디렉터가 쓴 `design_spec.md`와 `spec_lock.md`를 "
                "그대로 구현하세요 — 디자인 판단을 새로 하지 말고 명세의 레이아웃·위계·이미지 "
                "크롭을 정확히 옮기는 데 집중하세요. "
                "SVG 슬라이드, 발표자 노트, svg_final 산출물 생성과 검증까지만 수행하세요. "
                "svg_to_pptx.py를 실행하거나 PPTX를 만들지 마세요. PPTX 내보내기는 "
                "독립 카이로스 워커가 담당합니다."
            )
            finish_instruction = (
                "SVG 검증, 노트 분리, svg_final 생성까지 완료한 뒤 최종 답변을 정확히 "
                "`KAIROS_PPT_SOURCES_READY`로 마치세요."
            )
        else:
            route_instruction = (
                "원고를 끝까지 읽고 덱의 흐름과 디자인을 직접 판단해 설계한 뒤, Generate PPTX "
                "경로를 끝까지 수행하여 exports/에 PPTX를 만드세요."
            )
            finish_instruction = (
                "모든 SVG 검증과 후처리, PPTX export까지 완료한 뒤 결과 경로를 최종 답변에 적으세요."
            )

        # PowerPoint 변환에서 실제로 깨졌던 지점들 — 슬라이드를 만드는 단계에서만 필요하다
        build_qa = BUILD_QA if phase != "plan" else ""

        style_instruction = presentation_style_prompt(
            str(options.get("style_preset") or "")
        )
        selected_image_style = image_style_prompt(
            str(options.get("image_style") or "")
        )
        return f"""
아래 PPT Master 스킬을 사용해 강의안으로 편집 가능한 PowerPoint를 완성하세요.
스킬 진입점: {ppt_root / 'skills' / 'ppt-master' / 'SKILL.md'}
프로젝트: {project}
입력 본문: {project / 'sources' / 'lecture.md'}
추출 자산 목록: {project / 'sources' / 'assets.json'}

사용자가 카이로스 화면에서 아래 제작 사양을 직접 확정했고, 나머지 세부 디자인 판단을
에이전트에게 명시적으로 위임했습니다. 별도 확인 UI를 열거나 질문하지 마세요.
{route_instruction}
모든 Python 스크립트는 `{sys.executable}` 인터프리터로 실행하세요.
현재 운영체제는 Windows PowerShell입니다. Bash heredoc(`<<`, `<<'PY'`)과 셸 입력
리다이렉션으로 Python 코드를 실행하지 마세요. 여러 줄 Python이 필요하면 프로젝트 안에
`.py` 파일을 작성한 뒤 `{sys.executable} script.py` 형태로 실행하세요.
비대화형 작업이므로 live preview/Flask 서버나 브라우저를 시작하지 마세요.
- 제목: {options.get('title', '강의안')}
- 대상: {options.get('audience', '일반 학습자')}
- 슬라이드 수: 약 {options.get('slide_count', 10)}장
- 화면 비율: {options.get('aspect', '16:9')}
- 분위기: {options.get('tone', '명료하고 현대적인 교육 자료')}
- 디자인 시스템:
{style_instruction}
- AI 이미지 Visual DNA:
{selected_image_style}
- 외부 사실 조사: 하지 않음. 제공된 강의안만 사용
- 발표자 노트: {bool(options.get('speaker_notes', True))}
{build_qa}
{image_instruction}
{finish_instruction}
""".strip()

    @staticmethod
    def _revision_prompt(project: Path, ppt_root: Path, helper: Path,
                         runner: Path | None, prompt_kit: Path | None,
                         options: dict, phase: str) -> str:
        """완성된 덱의 수정본 지시문 — plan(수정 계획, 아트 디렉터) / execute(반영, 제작자)."""
        request = str(options.get("revision_request") or "").strip()
        common = f"""
카이로스 PPT 수정 작업입니다. 아래 프로젝트는 이미 완성된 PPT Master 덱입니다.
스킬 진입점: {ppt_root / 'skills' / 'ppt-master' / 'SKILL.md'}
프로젝트: {project}
사용자가 화면에서 아래 수정을 요청했습니다. 별도 확인 UI를 열거나 질문하지 마세요.

<수정 요청>
{request}
</수정 요청>

요청한 부분만 바꾸고 나머지 슬라이드·문구·이미지·디자인은 그대로 둡니다.
모든 Python 스크립트는 `{sys.executable}` 인터프리터로 실행하세요. Windows PowerShell
환경이므로 Bash heredoc을 쓰지 말고, 여러 줄 Python은 `.py` 파일로 만들어 실행하세요.
live preview/Flask 서버나 브라우저를 시작하지 마세요.
""".strip()
        if phase == "plan":
            image_rule = ""
            if options.get("use_ai_images", True) and runner and prompt_kit:
                image_rule = (
                    "\n이미지를 바꿔야 하는 요청이면 `images/image_prompts.json`에서 해당 항목만 "
                    "프롬프트를 고치고, **filename을 새 이름(예: `cover_v2.png`)으로 바꾸고 status를 "
                    "`Pending`**으로 두세요. 원래 PNG는 지우지 마세요. 다른 항목은 `Generated` 그대로 "
                    "둡니다. 새 프롬프트에도 기존 Visual DNA 문장을 그대로 넣고 `AR 16:9`로 끝내세요.\n"
                    + IMAGE_CRAFT
                )
            return f"""{common}

당신은 이 덱의 아트 디렉터입니다. 먼저 `design_spec.md`, `spec_lock.md`, `svg_output/`
(또는 `svg_final/`), 발표자 노트를 읽고 요청이 어느 슬라이드·요소에 해당하는지 파악하세요.
요청을 반영하도록 `design_spec.md`와 `spec_lock.md`를 갱신하고, 제작자가 그대로 따라 할 수
있게 **`revision_plan.md`**에 슬라이드별로 무엇을 어떻게 바꿀지(문구·위치·크기·색·이미지
파일명) 구체적으로 적으세요.{image_rule}
이 단계에서는 이미지 생성(Fleet, imagegen, image_gen.py), SVG 수정, PPTX export를 하지 마세요.
계획이 끝나면 최종 답변을 정확히 `KAIROS_REVISION_PLAN_READY`로 마치세요.
""".strip()
        return f"""{common}

당신은 제작자입니다. 아트 디렉터가 쓴 `revision_plan.md`와 갱신된 `design_spec.md`·
`spec_lock.md`대로 해당 슬라이드의 SVG만 수정하세요. 새 이미지가 있으면(manifest에서
새 filename, status `Generated`) 계획에 적힌 슬라이드에서 그 파일로 바꾸세요. 디자인 판단을
새로 하지 말고 계획을 정확히 옮기세요. 바뀐 슬라이드의 발표자 노트도 맞추고, SVG 검증과
svg_final 재생성까지 하세요. svg_to_pptx.py를 실행하거나 PPTX를 만들지 마세요 —
PPTX 내보내기는 독립 카이로스 워커가 담당합니다.
{BUILD_QA}
끝나면 최종 답변을 정확히 `KAIROS_PPT_SOURCES_READY`로 마치세요.
""".strip()
