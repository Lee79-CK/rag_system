"""admin-api 설정 (docs/TDD.md §10, §7.5).

환경변수 키는 TDD §10 + PRD 부록 B가 SSOT. 임의 변경 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- PostgreSQL (부록 B) ---
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="rag", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(
        default=SecretStr("rag-dev-only"), alias="POSTGRES_PASSWORD"
    )  # repr/log 노출 금지 (CLAUDE.md 규칙 3)
    postgres_db: str = Field(default="rag", alias="POSTGRES_DB")
    # 명시적 override (예: 테스트/특수 배포). 설정 시 위 5개 키보다 우선.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # --- 문서 저장 (DEC-004 NFS PVC) ---
    document_storage_path: str = Field(default="/data/documents", alias="DOCUMENT_STORAGE_PATH")
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    # 일괄 업로드 한 번의 파일 수 상한 — 합계 크기는 max_upload_bytes 를 그대로 적용
    max_upload_files: int = Field(default=10, alias="MAX_UPLOAD_FILES")

    # --- Web Chat 사용자 관리 (chat-gateway 와 동일 값이어야 로그인 가능) ---
    chat_workspace_slug: str = Field(default="rag", alias="CHAT_WORKSPACE_SLUG")
    password_pepper_file: str = Field(default="", alias="PASSWORD_PEPPER_FILE")

    def password_pepper(self) -> bytes:
        """chat-gateway 와 공유하는 pepper (Secret file). 값은 로그/응답 노출 금지."""
        import os
        from pathlib import Path

        path = self.password_pepper_file
        if path and os.path.isfile(path):
            return Path(path).read_text(encoding="utf-8").strip().encode("utf-8")
        return b""

    # --- 검색 색인(Qdrant) — 문서 비활성화/삭제를 payload is_active=false 로 즉시 반영 (FR-DOC-008) ---
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="rag_chunks_v1", alias="QDRANT_COLLECTION")
    qdrant_timeout: float = Field(default=10.0, alias="QDRANT_TIMEOUT")

    # RUNNING 으로 이 시간(분) 넘게 남은 index_job 은 비정상 종료(Pod 강제 종료·재시도 소진)로 보고 FAILED 처리.
    # 그대로 두면 문서의 채널 변경·비활성화·재색인이 영구히 409 로 막힌다. 최대 문서(1,000쪽 ≈ 30분)보다 넉넉히.
    index_job_stale_minutes: int = Field(default=120, alias="INDEX_JOB_STALE_MINUTES")

    # --- 오류 로그 화면의 파드 로그 조회 (admin.services.pod_logs) ---
    # none: 비활성(DB 오류 목록만) · k8s: in-cluster SA 로 pods/log 조회 — chart podLogs.enabled 의 Role 필요
    pod_log_access: str = Field(default="none", alias="POD_LOG_ACCESS")
    log_app_namespace: str = Field(default="rag-app", alias="LOG_APP_NAMESPACE")
    log_ai_namespace: str = Field(default="rag-ai", alias="LOG_AI_NAMESPACE")

    # --- 색인 Job 트리거 (ADR-008, §7.5) ---
    # none: index_jobs 행만 생성(로컬/CLI 실행) · k8s: kube-apiserver 로 parser-indexer Job 생성
    index_job_trigger: str = Field(default="none", alias="INDEX_JOB_TRIGGER")
    index_job_namespace: str = Field(default="rag-ingestion", alias="INDEX_JOB_NAMESPACE")
    index_job_template_configmap: str = Field(
        default="parser-indexer-job-template", alias="INDEX_JOB_TEMPLATE_CONFIGMAP"
    )

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        pw = self.postgres_password.get_secret_value()  # DSN 조립 시에만 노출
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
