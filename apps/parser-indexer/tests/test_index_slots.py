"""동시 색인 슬롯 — 색인 Job 직렬화 (ingestion.slots, 가이드 §5.1.1 "여러 문서는 순차 색인")."""

from __future__ import annotations

import threading

import pytest
from ingestion.slots import SLOT_KEY_BASE, SlotWaitTimeout, acquire_slot


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_fr_idx_slot_acquires_free_slot_immediately():
    tried: list[int] = []
    slot = acquire_slot(
        lambda k: tried.append(k) or True,
        max_parallel=1,
        poll_seconds=10,
        timeout_seconds=60,
    )
    assert slot == 0 and tried == [SLOT_KEY_BASE]


def test_fr_idx_slot_waits_until_released_and_reports_wait():
    """슬롯이 차 있으면 poll 간격으로 대기 → 풀리면 획득. 대기 콜백으로 stage=WAITING 표시."""
    clock = _FakeClock()
    free_at = 25.0
    waits: list[float] = []
    slot = acquire_slot(
        lambda k: clock.t >= free_at,
        max_parallel=1,
        poll_seconds=10,
        timeout_seconds=600,
        on_wait=waits.append,
        sleep=clock.sleep,
        clock=clock,
    )
    assert slot == 0
    assert waits == [0.0, 10.0, 20.0]


def test_fr_idx_slot_uses_second_slot_when_parallel_2():
    taken = {SLOT_KEY_BASE}
    slot = acquire_slot(lambda k: k not in taken, max_parallel=2, poll_seconds=1, timeout_seconds=1)
    assert slot == 1


def test_fr_idx_slot_wait_timeout():
    clock = _FakeClock()
    with pytest.raises(SlotWaitTimeout):
        acquire_slot(
            lambda k: False,
            max_parallel=1,
            poll_seconds=10,
            timeout_seconds=30,
            sleep=clock.sleep,
            clock=clock,
        )


# ----- 실제 PostgreSQL advisory lock (Docker 필요) -----


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def pg_url():
    if not _docker_available():
        pytest.skip("Docker 미기동 — testcontainers 실행 불가")
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    c = (
        DockerContainer("postgres:16")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_USER", "rag")
        .with_env("POSTGRES_DB", "rag")
        .with_exposed_ports(5432)
    )
    c.start()
    wait_for_logs(c, "database system is ready to accept connections", timeout=60)
    # initdb 후 재기동하므로 두 번째 ready 로그까지 기다린 뒤 접속 재시도
    import time

    from sqlalchemy import create_engine, text

    url = (
        f"postgresql+psycopg://rag:test@{c.get_container_host_ip()}:{c.get_exposed_port(5432)}/rag"
    )
    for _ in range(60):
        try:
            with create_engine(url).connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(1)
    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE index_jobs (id text PRIMARY KEY, status text, stage text)"))
        conn.execute(
            text("INSERT INTO index_jobs VALUES ('j1','PENDING',NULL),('j2','PENDING',NULL)")
        )
    yield url
    c.stop()


def test_fr_idx_slot_serializes_jobs_with_pg_advisory_lock(pg_url):
    """Job 2 는 Job 1 이 슬롯을 놓을 때까지 대기(stage=WAITING) — 해제 후 획득. 연결 풀에 lock 이 남지 않는다."""
    from ingestion.core.config import Settings
    from ingestion.db import JobRepository
    from sqlalchemy import text

    settings = Settings(
        index_max_parallel=1, index_slot_poll_seconds=0.2, index_slot_wait_timeout_seconds=30
    )
    repo = JobRepository.from_url(pg_url)
    order: list[str] = []
    job1_in = threading.Event()
    release1 = threading.Event()

    def job1():
        with repo.index_slot("j1", settings):
            order.append("j1-start")
            job1_in.set()
            release1.wait(10)
            order.append("j1-end")

    def job2():
        job1_in.wait(10)
        with repo.index_slot("j2", settings):
            order.append("j2-start")

    t1, t2 = threading.Thread(target=job1), threading.Thread(target=job2)
    t1.start()
    t2.start()
    job1_in.wait(10)
    # Job 2 가 대기 표시를 남길 때까지
    for _ in range(50):
        with repo._engine.connect() as conn:
            if (
                conn.execute(text("SELECT stage FROM index_jobs WHERE id='j2'")).scalar()
                == "WAITING"
            ):
                break
        threading.Event().wait(0.1)
    assert order == ["j1-start"]
    release1.set()
    t1.join(10)
    t2.join(10)
    assert order == ["j1-start", "j1-end", "j2-start"]

    with repo._engine.connect() as conn:
        held = conn.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted")
        ).scalar()
    assert held == 0
