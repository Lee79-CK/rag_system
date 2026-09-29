"""Worker/파이프라인 실 어댑터 구성 (§7.2). settings → adapters → WorkerDeps/RagPipeline."""

from __future__ import annotations

from pathlib import Path

from chat_adapter import redis_emitter
from rag_observability import get_logger
from sqlalchemy import create_engine

from rag.adapters.embedding_client import EmbeddingClient
from rag.adapters.llm_client import LLMClient
from rag.adapters.pg_repo import PgBindingReader, PgChatPostStore, PgConversationStore
from rag.adapters.qdrant_repo import QdrantRepo
from rag.adapters.reranker_client import RerankerClient
from rag.adapters.webchat_delivery import DeliveryDeps, WebChatDelivery
from rag.core.config import Settings, get_settings
from rag.domain.context import BudgetConfig
from rag.domain.pipeline import PipelineConfig, RagPipeline
from rag.domain.tokens import make_token_counter
from rag.worker.chat_worker import WorkerDeps


def _read_key(path: str) -> bytes:
    p = Path(path)
    return p.read_bytes().strip() if p.exists() else b""


def build_pipeline(settings: Settings) -> RagPipeline:
    cfg = PipelineConfig(
        vector_top_k=settings.vector_top_k,
        rerank_top_n=settings.rerank_top_n,
        similarity_threshold=settings.similarity_threshold,
        rerank_score_threshold=settings.rerank_score_threshold,
        max_output_tokens=settings.max_output_tokens,
        temperature=settings.llm_temperature,
        budget=BudgetConfig(
            max_context_tokens=settings.max_context_tokens,
            max_output_tokens=settings.max_output_tokens,
            safety_margin_tokens=settings.safety_margin_tokens,
        ),
    )
    return RagPipeline(
        embedding=EmbeddingClient(
            settings.embedding_api_url,
            connect_timeout=settings.http_connect_timeout,
            read_timeout=settings.http_read_timeout,
        ),
        retrieval=QdrantRepo(settings.qdrant_url, settings.qdrant_collection),
        reranker=RerankerClient(
            settings.reranker_api_url,
            connect_timeout=settings.http_connect_timeout,
            read_timeout=settings.http_read_timeout,
        ),
        llm=LLMClient(
            settings.vllm_api_url,
            settings.llm_served_model_name,
            timeout=settings.llm_timeout_seconds,
            enable_thinking=settings.llm_enable_thinking,
        ),
        token_counter=make_token_counter(settings.tokenizer_path),
        config=cfg,
    )


def build_worker_deps() -> WorkerDeps:
    settings = get_settings()
    signing_key = _read_key(settings.feedback_signing_key_file)
    if settings.feedback_enabled and not signing_key:
        # 피드백 버튼 미노출로 degrade (빈 키 HMAC 토큰을 만들지 않는다 — fail-closed)
        get_logger("rag.worker").error(
            "worker.feedback_signing_key_missing", file=settings.feedback_signing_key_file
        )
    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    delivery = WebChatDelivery(
        DeliveryDeps(
            posts=PgChatPostStore(engine),
            emitter=redis_emitter(settings.redis_url),
            signing_key=signing_key,
        )
    )
    return WorkerDeps(
        binding_reader=PgBindingReader(engine),
        store=PgConversationStore(engine),
        pipeline=build_pipeline(settings),
        delivery=delivery,
    )
