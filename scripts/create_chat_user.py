"""Web Chat 사용자 생성/갱신 + 채널 멤버십 부여 (로컬/초기 구축용). `make seed-users`.

비밀번호 해시는 SQL 로 만들 수 없으므로(PBKDF2 prehash → scrypt+pepper) 이 스크립트를 쓴다.
chat-gateway 와 **같은** CHAT_WORKSPACE_SLUG / PASSWORD_PEPPER_FILE 을 사용해야 로그인된다.

    uv run python scripts/create_chat_user.py --email hong@example.com --name 홍길동 \\
        --password 'Rag!Assistant2026' --channels rag-cloud-ops,rag-hr [--role admin]

운영에서는 admin-web(채팅 사용자 메뉴) 의 임시 비밀번호 발급을 사용한다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rag_common.passwords import compute_prehash, hash_prehash, normalize_email
from sqlalchemy import create_engine, text


def _dsn() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return (
        f"postgresql+psycopg://{os.environ.get('POSTGRES_USER', 'rag')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'rag-dev-only')}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'rag')}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--password", required=True, help="12자 이상, 3종 이상 문자")
    ap.add_argument("--role", default="user", choices=["user", "admin"])
    ap.add_argument("--channels", default="", help="쉼표 구분 채널 name 목록")
    ap.add_argument("--must-change", action="store_true", help="첫 로그인 시 변경 강제")
    args = ap.parse_args()

    pepper_file = os.environ.get("PASSWORD_PEPPER_FILE", "")
    if not pepper_file or not Path(pepper_file).is_file():
        print("PASSWORD_PEPPER_FILE 이 필요합니다 (chat-gateway 와 동일 파일).", file=sys.stderr)
        return 2
    pepper = Path(pepper_file).read_text(encoding="utf-8").strip().encode()
    slug = os.environ.get("CHAT_WORKSPACE_SLUG", "rag")

    email = normalize_email(args.email)
    pw_hash = hash_prehash(compute_prehash(slug, email, args.password), pepper)

    engine = create_engine(_dsn())
    with engine.begin() as conn:
        uid = conn.execute(
            text(
                """
                INSERT INTO chat_users (email, display_name, role, password_hash,
                                        must_change_password)
                VALUES (:email, :name, :role, :h, :mc)
                ON CONFLICT ((lower(email))) DO UPDATE
                  SET display_name = EXCLUDED.display_name, role = EXCLUDED.role,
                      password_hash = EXCLUDED.password_hash,
                      must_change_password = EXCLUDED.must_change_password,
                      is_active = true, updated_at = now()
                RETURNING id
                """
            ),
            {
                "email": email,
                "name": args.name,
                "role": args.role,
                "h": pw_hash,
                "mc": args.must_change,
            },
        ).scalar_one()
        for name in [c.strip() for c in args.channels.split(",") if c.strip()]:
            cid = conn.execute(
                text("SELECT id FROM chat_channels WHERE name = :n"), {"n": name}
            ).scalar()
            if cid is None:
                print(f"  ! 채널 없음: {name} (seed_dev.sql 먼저 실행)", file=sys.stderr)
                continue
            conn.execute(
                text(
                    "INSERT INTO chat_channel_members (channel_id, user_id) VALUES (:c, :u)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"c": cid, "u": uid},
            )
    print(f"ok: {email} ({uid}) channels=[{args.channels}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
