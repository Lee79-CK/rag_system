"""피드백 버튼 context 서명(sig) 산출 — bridge `/actions` 수동 테스트용 (docs/TDD.md §7.1.4).

    uv run python scripts/sign_feedback.py --message-id <uuid> --value UP [--key-file secrets/rag/feedback-signing-key]

서명 규약의 SSOT 는 `mattermost_adapter.feedback_signature` (HMAC-SHA256(key, f"{message_id}:{value}")).
키 파일 기본값은 env FEEDBACK_SIGNING_KEY_FILE → ./secrets/rag/feedback-signing-key.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mattermost_adapter import feedback_signature


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="feedback context sig 산출")
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--value", required=True, choices=["UP", "DOWN"])
    parser.add_argument(
        "--key-file",
        default=os.environ.get("FEEDBACK_SIGNING_KEY_FILE", "./secrets/rag/feedback-signing-key"),
    )
    args = parser.parse_args(argv)

    key_path = Path(args.key_file)
    if not key_path.is_file():
        print(f"signing key file not found: {key_path}", file=sys.stderr)
        return 2
    key = key_path.read_text(encoding="utf-8").strip().encode("utf-8")
    if not key:
        print("signing key file is empty", file=sys.stderr)
        return 2
    print(feedback_signature(key, args.message_id, args.value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
