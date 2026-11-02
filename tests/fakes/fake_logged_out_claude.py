"""로그인이 풀린 claude CLI의 stream-json 출력 재현 (2.1.x 실측 형태)."""
import json
import sys

for msg in (
    {"type": "system", "subtype": "init", "session_id": "sess-out"},
    {"type": "assistant", "error": "authentication_failed",
     "message": {"content": [{"type": "text", "text": "Not logged in · Please run /login"}]}},
    {"type": "result", "subtype": "success", "is_error": True,
     "result": "Not logged in · Please run /login", "session_id": "sess-out"},
):
    print(json.dumps(msg, ensure_ascii=False), flush=True)
sys.exit(1)
