"""이미지 러너가 한글 프롬프트 jsonl을 기본 인코딩(Windows cp949)과 무관하게 읽는다."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_load_items_reads_korean_prompts_without_utf8_mode(tmp_path):
    prompts = tmp_path / "prompts.jsonl"
    rows = [{"prompt": "부모와 자녀가 함께 식탁에 앉은 장면, 따뜻한 저녁 빛", "output_path": "a.png"}]
    prompts.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                       encoding="utf-8")
    # UTF-8 모드를 끈 별도 프로세스 — Windows에서는 기본 인코딩이 cp949가 된다
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONPATH": str(REPO)}
    env.pop("PYTHONIOENCODING", None)
    code = ("import json, sys; from core.codex_imagegen_runner import load_items; "
            "items = load_items(sys.argv[1]); "
            "sys.stdout.buffer.write(json.dumps(items, ensure_ascii=False).encode('utf-8'))")
    out = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code, str(prompts)],
                         capture_output=True, env=env, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    assert json.loads(out.stdout.decode("utf-8")) == rows
