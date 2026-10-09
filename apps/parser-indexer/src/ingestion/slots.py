"""동시 색인 슬롯 — 색인 Job 을 시스템이 직렬화한다 (가이드 §5.1.1 "여러 문서는 순차 색인").

색인 Job 은 문서마다 K8s Job 으로 즉시 생성되지만, 임베딩은 embedding-api 한 곳(랩: replica 1 · CPU 6)에서
처리되므로 동시에 돌리면 처리량은 늘지 않고 배치가 timeout(120s)을 넘겨 FAILED → 재시도로 부하가 쌓이며,
같은 embedding-api 를 쓰는 채팅 질의 임베딩까지 느려진다. → Job 은 시작 직후 PostgreSQL advisory lock 슬롯
(`INDEX_MAX_PARALLEL` 개)을 잡을 때까지 PENDING(stage=WAITING) 으로 대기한다.

session-level advisory lock 이라 Pod 가 죽어 DB 연결이 끊기면 PostgreSQL 이 슬롯을 자동 해제한다.
순서는 폴링 경쟁이라 엄격한 FIFO 는 아니다(대체로 먼저 기다린 Job 이 먼저 잡는다).
"""

from __future__ import annotations

import time
from collections.abc import Callable

# 다른 advisory lock 과 겹치지 않는 고정 키 대역 (슬롯 i → SLOT_KEY_BASE + i).
SLOT_KEY_BASE = 7_420_110_000


class SlotWaitTimeout(RuntimeError):
    """대기 상한 초과 — 앞선 Job 이 비정상적으로 오래 슬롯을 잡고 있는 경우."""


def acquire_slot(
    try_lock: Callable[[int], bool],
    *,
    max_parallel: int,
    poll_seconds: float,
    timeout_seconds: float,
    on_wait: Callable[[float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """비어 있는 슬롯 번호를 반환할 때까지 대기. on_wait(경과초)는 대기 루프마다 호출된다."""
    start = clock()
    while True:
        for i in range(max(1, max_parallel)):
            if try_lock(SLOT_KEY_BASE + i):
                return i
        elapsed = clock() - start
        if elapsed >= timeout_seconds:
            raise SlotWaitTimeout(
                f"색인 슬롯 대기 {int(elapsed)}초 초과 (INDEX_MAX_PARALLEL={max_parallel})"
            )
        if on_wait is not None:
            on_wait(elapsed)
        sleep(poll_seconds)
