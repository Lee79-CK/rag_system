"""각 FastAPI 앱의 OpenAPI 스키마를 docs/openapi/*.json 으로 export (§9 MUST, NFR-MAINT-002).

Contract test는 이 파일과 대조한다. 앱 import 실패 시 건너뛰고 경고만 출력한다.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

# (service 이름, "module:factory_or_app") — factory가 있으면 호출, 아니면 app 속성 사용
SERVICES = [
    ("chat-gateway", "gateway.main"),
    ("rag-api", "rag.main"),
    ("admin-api", "admin.main"),
    ("embedding-api", "embedding.main"),
    ("reranker-api", "reranker.main"),
]

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "openapi"


def _load_app(module_path: str):
    mod = importlib.import_module(module_path)
    if hasattr(mod, "create_app"):
        return mod.create_app()
    return mod.app


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, module_path in SERVICES:
        try:
            app = _load_app(module_path)
            schema = app.openapi()
        except Exception as exc:  # noqa: BLE001 — 미구현/미설치 앱은 건너뛴다
            print(f"[skip] {name}: {exc}")
            continue
        target = OUT_DIR / f"{name}.json"
        target.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok]   {name} → {target.relative_to(OUT_DIR.parent.parent)}")


if __name__ == "__main__":
    main()
