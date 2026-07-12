"""문서 스토리지 어댑터 — docs/TDD.md §7.5 (DEC-004 NFS PVC).

저장 경로: {DOCUMENT_STORAGE_PATH}/{document_id}/{version}/{filename}
MinIO 등은 `StorageAdapter` Protocol 구현체 교체로 대응한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, override


class StorageAdapter(Protocol):
    def save(self, document_id: str, version: int, filename: str, data: bytes) -> str:
        """원본 파일을 저장하고 저장 경로(문자열)를 반환한다."""
        ...

    def read(self, path: str) -> bytes: ...

    def delete(self, path: str) -> None: ...


class NFSStorage:
    """NFS PVC 마운트 경로 하위에 저장하는 어댑터 (DEC-004)."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    @override
    def save(self, document_id: str, version: int, filename: str, data: bytes) -> str:
        safe_name = Path(filename).name  # 경로 탈출 방지.
        target_dir = self._root / document_id / str(version)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        target.write_bytes(data)
        return str(target)

    @override
    def read(self, path: str) -> bytes:
        return Path(path).read_bytes()

    @override
    def delete(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            p.unlink()
