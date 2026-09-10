"""보안 원시 함수 (docs/TDD.md §11 #1, NFR-SEC-008)."""

from __future__ import annotations

import hmac
import ipaddress


def constant_time_token_check(provided: str, expected: str) -> bool:
    """Outgoing Token 상수시간 비교 (§22.2, §11 #1).

    타이밍 공격을 피하려고 `hmac.compare_digest`를 사용한다. None-안전.
    기대 토큰이 비어 있으면(Secret 파일 미마운트 등) **무조건 거부**한다 — fail-closed (§11 #1).
    """
    if not expected:
        return False
    return hmac.compare_digest(provided or "", expected)


def source_ip_allowed(ip: str, cidrs: list[str]) -> bool:
    """Source IP가 allowlist CIDR에 속하는지 검사한다 (NFR-SEC-008).

    allowlist가 비어 있으면(미설정) 개방 정책으로 True를 반환한다.
    파싱 불가한 IP/CIDR은 매칭 실패로 간주한다.
    """
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
