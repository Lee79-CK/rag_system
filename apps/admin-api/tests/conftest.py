"""admin-api 테스트 하네스 — 완전 hermetic (SQLite in-memory, 외부 의존 없음).

- SQLite in-memory + StaticPool로 models 기반 create_all.
- get_db 의존성 및 audit 미들웨어 sessionmaker를 테스트 엔진으로 override.
- 인증은 실제 HeaderAuthBackend를 사용하되, 테스트 DB에 사용자/역할을 seed하여
  X-Auth-User 헤더로 RBAC까지 검증한다.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# 문서 저장 경로를 임시 디렉터리로 고정 (앱/설정 import 전에 설정).
_TMP_STORAGE = tempfile.mkdtemp(prefix="admin-doc-store-")
os.environ["DOCUMENT_STORAGE_PATH"] = _TMP_STORAGE

import admin.core.audit as audit_mod  # noqa: E402
from admin.core.config import get_settings  # noqa: E402
from admin.db.models import AdminUser, Base, Role  # noqa: E402
from admin.db.session import get_db  # noqa: E402
from admin.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def TestSession(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def seed(TestSession):
    """사용자/역할을 seed하는 헬퍼. login_id → roles 매핑을 받는다."""

    def _seed(users: dict[str, list[str]]) -> None:
        with TestSession() as s:
            role_cache: dict[str, Role] = {}
            for login_id, role_names in users.items():
                user = AdminUser(login_id=login_id, display_name=login_id, status="ACTIVE")
                for rn in role_names:
                    role = role_cache.get(rn)
                    if role is None:
                        role = Role(name=rn)
                        role_cache[rn] = role
                        s.add(role)
                    user.roles.append(role)
                s.add(user)
            s.commit()

    return _seed


@pytest.fixture
def client(engine, TestSession, monkeypatch):
    app = create_app()

    def _override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    # 검색 색인(Qdrant)은 기본 no-op fake — 실제 네트워크 호출 금지. 테스트별로 override 해 호출을 검증한다.
    from admin.services.search_index import provide_search_index

    class _NullSearchIndex:
        def deactivate_document(self, document_id):
            pass

    app.dependency_overrides[provide_search_index] = lambda: _NullSearchIndex()
    # 감사 미들웨어도 테스트 엔진을 사용하도록 교체.
    monkeypatch.setattr(audit_mod, "get_sessionmaker", lambda: TestSession)

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth():
    """X-Auth-User 헤더 빌더 fixture."""

    def _make(login_id: str) -> dict[str, str]:
        return {"X-Auth-User": login_id}

    return _make
