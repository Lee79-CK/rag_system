"""테스트는 항상 결정론적 mock 엔진으로 구동한다 (로컬엔 FlagEmbedding 미설치)."""

from __future__ import annotations

import os

os.environ.setdefault("RERANKER_MOCK", "1")
