"""RAG 응답 지연(p50/p95) 측정 (M7 DoD, PRD §8.2).

rag-api 동기 completions 경로를 반복 호출하여 stage별/총 지연을 집계한다.
로컬은 mock LLM 기준, 운영은 실 vLLM 기준. 목표: 최종 답변 p95 ≤ 30s (동시 10건).

실행:
  python scripts/measure_latency.py --n 30 --concurrency 5 \
      --rag-url http://localhost:8002 --channel c0000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time

import httpx

# PRD §8.2 목표 (ms)
TARGET_TOTAL_P95_MS = 30000


async def _one(client: httpx.AsyncClient, url: str, channel: str, q: str) -> float:
    start = time.perf_counter()
    resp = await client.post(
        f"{url.rstrip('/')}/internal/v1/rag/completions",
        json={"channel_id": channel, "message": q},
    )
    resp.raise_for_status()
    return (time.perf_counter() - start) * 1000


async def run(args) -> int:
    sem = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    errors = 0

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=120.0, write=10.0, pool=10.0)
    ) as client:

        async def worker(i: int) -> None:
            nonlocal errors
            async with sem:
                try:
                    latencies.append(await _one(client, args.rag_url, args.channel, args.question))
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"[err] {i}: {exc}")

        await asyncio.gather(*(worker(i) for i in range(args.n)))

    if not latencies:
        print("측정 실패 — 모든 요청 오류")
        return 1

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    print(f"요청: {args.n}  동시성: {args.concurrency}  오류: {errors}")
    print(f"p50: {p50:.0f}ms  p95: {p95:.0f}ms  max: {latencies[-1]:.0f}ms")
    ok = p95 <= TARGET_TOTAL_P95_MS
    print(
        f"{'[OK]' if ok else '[FAIL]'} 최종 답변 p95 {p95:.0f}ms {'≤' if ok else '>'} {TARGET_TOTAL_P95_MS}ms"
    )
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 응답 지연 측정 (p50/p95)")
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--rag-url", default=os.environ.get("RAG_API_URL", "http://localhost:8002"))
    parser.add_argument(
        "--channel", default="c0000000-0000-0000-0000-000000000001", help="chat_channels.id"
    )
    parser.add_argument("--question", default="장애 등급별 대응 절차를 알려주세요.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
