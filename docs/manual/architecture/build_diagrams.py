"""랩(P3 + PGX) 시스템 아키텍처 다이어그램 생성기.

산출물 (이 파일과 같은 디렉터리 + 상위 docs/manual):
- architecture/NN-*.svg   다이어그램 원본 (편집은 이 스크립트에서)
- architecture/NN-*.png   2배 해상도 이미지 (슬라이드·문서 첨부용)
- ../system-architecture.html   SVG 를 인라인한 단일 HTML (외부 리소스 없음)

실행 (PNG 는 cairosvg 필요 — 개발 PC 에서만):
    uv run --with cairosvg python docs/manual/architecture/build_diagrams.py

수치(리소스·포트·모델)는 2026-10-11 랩 클러스터(kubectl) 실측 기준이다.
랩 구성이 바뀌면 이 파일의 값을 고치고 다시 실행한다.
"""

from __future__ import annotations

import html
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML_OUT = HERE.parent / "system-architecture.html"

FONT = "'Noto Sans CJK KR','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif"
MONO = "'Noto Sans Mono CJK KR','D2Coding',Consolas,'DejaVu Sans Mono',monospace"

STYLE = f"""
text{{font-family:{FONT};fill:#1d2330}}
.h{{font-size:19px;font-weight:700}}
.t{{font-size:15px;font-weight:700}}
.tl{{font-size:16.5px;font-weight:700}}
.s{{font-size:12.5px;fill:#3f4757}}
.sm{{font-size:11.5px;fill:#4a5263}}
.m{{font-size:11.5px;fill:#55607a;font-family:{MONO}}}
.lbl{{font-size:13px;font-weight:700;fill:#334155}}
.al{{font-size:12px;fill:#334155}}
.alb{{font-size:12px;font-weight:700;fill:#334155}}
rect{{stroke-width:1.5}}
.lane{{fill:#f7f8fb;stroke:#d5dae3}}
.user{{fill:#eef0f3;stroke:#8a93a3}}
.web{{fill:#e7f0ff;stroke:#3b78e7}}
.api{{fill:#e2f5f1;stroke:#14967f}}
.work{{fill:#f1eaff;stroke:#7c4ddb}}
.ai{{fill:#fff2e5;stroke:#e07a1f}}
.gpu{{fill:#ffeaea;stroke:#d64545}}
.data{{fill:#e9f6e6;stroke:#3d9a3a}}
.infra{{fill:#f3f5f9;stroke:#64748b}}
.node{{fill:#fbfcfe;stroke:#334155;stroke-width:2.2}}
.note{{fill:#fffbe6;stroke:#c9a227}}
.ns{{fill:none;stroke:#94a3b8;stroke-dasharray:6 4}}
.dash{{stroke-dasharray:6 4}}
.off{{fill:#f5f5f5;stroke:#b0b0b0;stroke-dasharray:5 4}}
.lbg{{fill:#ffffff;fill-opacity:0.94;stroke:none}}
.ar{{fill:none;stroke:#475569;stroke-width:1.6}}
.ar-b{{fill:none;stroke:#3b78e7;stroke-width:1.8}}
.ar-o{{fill:none;stroke:#e07a1f;stroke-width:1.8}}
.ar-g{{fill:none;stroke:#3d9a3a;stroke-width:1.8}}
.ar-v{{fill:none;stroke:#7c4ddb;stroke-width:1.8}}
.ar-r{{fill:none;stroke:#d64545;stroke-width:1.8}}
.ar-t{{fill:none;stroke:#14967f;stroke-width:1.8}}
.life{{stroke:#94a3b8;stroke-width:1.2;stroke-dasharray:4 4}}
.bus{{stroke:#334155;stroke-width:5}}
"""

MARKERS = {"": "#475569", "-b": "#3b78e7", "-o": "#e07a1f", "-g": "#3d9a3a", "-v": "#7c4ddb",
           "-r": "#d64545", "-t": "#14967f"}  # fmt: skip

LINE_H = {"h": 25, "t": 21, "tl": 23, "s": 17.5, "sm": 16, "m": 16, "lbl": 18, "al": 16, "alb": 16}
FONT_PX = {"h": 19, "t": 15, "tl": 16.5, "s": 12.5, "sm": 11.5, "m": 11.5, "lbl": 13, "al": 12,
           "alb": 12}  # fmt: skip


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def text_width(s: str, cls: str) -> float:
    px = FONT_PX.get(cls, 12)
    w = 0.0
    for ch in s:
        if ord(ch) >= 0x1100:
            w += px * 1.0
        elif ch == " ":
            w += px * 0.33
        else:
            w += px * 0.58
    return w


@dataclass
class Svg:
    key: str
    width: int
    height: int
    title: str

    def __post_init__(self) -> None:
        self.parts: list[str] = []

    # ---- primitives --------------------------------------------------------------
    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, cls, rx=10, extra="") -> None:
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="{cls}" {extra}/>'
        )

    def text(self, x, y, s, cls="s", anchor="start", extra="") -> None:
        self.add(
            f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}" {extra}>{esc(s)}</text>'
        )

    def label(self, x, y, s, cls="al", anchor="middle") -> None:
        """배경이 있는 화살표 라벨 (y = baseline)."""
        w = text_width(s, cls) + 10
        px = FONT_PX.get(cls, 12)
        left = {"middle": x - w / 2, "start": x - 5, "end": x - w + 5}[anchor]
        self.add(
            f'<rect x="{left:.1f}" y="{y - px - 1:.1f}" width="{w:.1f}" height="{px + 7:.1f}" rx="4" class="lbg"/>'
        )
        self.text(x, y, s, cls, anchor)

    def box(self, x, y, w, h, cls, lines, *, align="middle", rx=10, pad=12, extra="") -> None:
        """lines = [(cls, text), ...] 를 상자 안에 세로 가운데 정렬."""
        self.rect(x, y, w, h, cls, rx, extra)
        total = sum(LINE_H[c] for c, _ in lines)
        cy = y + (h - total) / 2
        tx = x + w / 2 if align == "middle" else x + pad
        for c, s in lines:
            lh = LINE_H[c]
            self.text(tx, round(cy + lh * 0.76, 1), s, c, align)
            cy += lh

    def arrow(self, d, cls="ar", marker="", start_marker=False) -> None:
        sm = f' marker-start="url(#{self.key}-s{marker})"' if start_marker else ""
        self.add(f'<path d="{d}" class="{cls}" marker-end="url(#{self.key}-a{marker})"{sm}/>')

    def line(self, x1, y1, x2, y2, cls) -> None:
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}"/>')

    # ---- output ------------------------------------------------------------------
    def render(self) -> str:
        defs = []
        for suf, color in MARKERS.items():
            defs.append(
                f'<marker id="{self.key}-a{suf}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
            )
            defs.append(
                f'<marker id="{self.key}-s{suf}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="{color}"/></marker>'
            )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img" aria-label="{esc(self.title)}">'
            f"<title>{esc(self.title)}</title><style>{STYLE}</style><defs>{''.join(defs)}</defs>"
            f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#ffffff" stroke="none"/>'
            + "".join(self.parts)
            + "</svg>"
        )


# =====================================================================================
# 01. 한눈에 보기 (초보자용)
# =====================================================================================
def fig_overview() -> Svg:
    g = Svg("f1", 1060, 470, "한눈에 보기 — 질문하고 답 받기 / 문서 넣기")

    g.rect(10, 10, 1040, 215, "lane", 14)
    g.text(28, 38, "① 질문하고 답 받기 — 사용자가 매번 하는 일", "lbl")
    g.rect(10, 245, 1040, 215, "lane", 14)
    g.text(28, 273, "② 문서 넣기 — 관리자가 미리 해 두는 일", "lbl")

    xs = [200, 415, 630, 845]
    bw, by1, by2, bh = 185, 95, 330, 105
    g.box(
        30,
        by1,
        135,
        bh,
        "user",
        [("tl", "사용자"), ("s", "웹 브라우저"), ("m", "chat.rag.lab.local")],
    )
    g.box(
        xs[0],
        by1,
        bw,
        bh,
        "api",
        [
            ("t", "질문 접수"),
            ("s", "질문을 저장하고"),
            ("s", "작업 대기열에 넣음"),
            ("m", "chat-gateway"),
        ],
    )
    g.box(
        xs[1],
        by1,
        bw,
        bh,
        "ai",
        [
            ("t", "근거 문서 찾기"),
            ("s", "질문과 뜻이 비슷한"),
            ("s", "문서 조각을 골라냄"),
            ("m", "embedding·Qdrant·reranker"),
        ],
    )
    g.box(
        xs[2],
        by1,
        bw,
        bh,
        "gpu",
        [
            ("t", "답변 작성 (AI)"),
            ("s", "찾은 근거만 보고"),
            ("s", "한국어로 답을 씀"),
            ("m", "vLLM · PGX GPU"),
        ],
    )
    g.box(
        xs[3],
        by1,
        bw,
        bh,
        "web",
        [
            ("t", "실시간 표시"),
            ("s", "글자가 만들어지는 대로"),
            ("s", "화면에 흘려 보냄"),
            ("m", "socket.io"),
        ],
    )
    my = by1 + bh / 2
    g.arrow(f"M165,{my} L{xs[0] - 3},{my}")
    for a, b in zip(xs, xs[1:], strict=False):
        g.arrow(f"M{a + bw},{my} L{b - 3},{my}")
    g.arrow(f"M{xs[3] + bw / 2},{by1} C{xs[3] + bw / 2},52 97,52 97,{by1 - 3}", "ar-b", "-b")
    g.label(530, 66, "답변과 근거 문서 표가 채팅 화면에 나타남", "alb")

    g.box(
        30, by2, 135, bh, "user", [("tl", "관리자"), ("s", "웹 브라우저"), ("m", "rag.lab.local")]
    )
    g.box(
        xs[0],
        by2,
        bw,
        bh,
        "web",
        [
            ("t", "문서 올리기"),
            ("s", "PDF·Word·HWP 등"),
            ("s", "한 번에 최대 10개"),
            ("m", "admin-web → admin-api"),
        ],
    )
    g.box(
        xs[1],
        by2,
        bw,
        bh,
        "work",
        [
            ("t", "글자 꺼내 조각내기"),
            ("s", "본문·표를 추출해"),
            ("s", "약 800토큰씩 자름"),
            ("m", "parser-indexer"),
        ],
    )
    g.box(
        xs[2],
        by2,
        bw,
        bh,
        "ai",
        [
            ("t", "뜻을 숫자로 바꾸기"),
            ("s", "조각마다 숫자 1,024개"),
            ("s", "(벡터)로 변환"),
            ("m", "embedding-api"),
        ],
    )
    g.box(
        xs[3],
        by2,
        bw,
        bh,
        "data",
        [
            ("t", "검색 서고에 보관"),
            ("s", "벡터 + 볼 수 있는"),
            ("s", "채널 목록을 함께 저장"),
            ("m", "Qdrant"),
        ],
    )
    my2 = by2 + bh / 2
    g.arrow(f"M165,{my2} L{xs[0] - 3},{my2}")
    for a, b in zip(xs, xs[1:], strict=False):
        g.arrow(f"M{a + bw},{my2} L{b - 3},{my2}")
    cx2, cx1 = xs[3] + bw / 2, xs[1] + bw / 2
    g.arrow(f"M{cx2},{by2} C{cx2},275 {cx1},260 {cx1},{by1 + bh + 3}", "ar-o dash", "-o")
    g.label(735, 247, "질문이 오면 여기서 근거를 찾음", "alb")
    return g


# =====================================================================================
# 02. 하드웨어 아키텍처
# =====================================================================================
def fig_hardware() -> Svg:
    g = Svg("f2", 1100, 730, "하드웨어 아키텍처 — P3 + PGX 2노드")

    g.box(
        375,
        14,
        350,
        66,
        "user",
        [("t", "사용자 · 관리자 PC (웹 브라우저)"), ("m", "hosts: *.rag.lab.local → 노드 IP")],
    )
    g.line(40, 118, 1060, 118, "bus")
    g.text(44, 108, "사내 LAN 192.168.168.0/24 — 폐쇄망 (인터넷 연결 없음)", "lbl")
    g.arrow("M550,80 L550,113", "ar-b", "-b")
    g.label(560, 101, "HTTPS 443", "al", "start")
    g.line(275, 118, 275, 168, "ar")
    g.line(835, 118, 835, 168, "ar")
    g.arrow("M805,146 L310,146", "ar dash")
    g.label(
        557, 151, "PGX → P3: 이미지 pull(:5000) · K8s API(:6443) · Pod 네트워크(Canal VXLAN)", "al"
    )

    def node(x, w, title, sub, chips, role, roles2):
        g.rect(x, 170, w, 545, "node", 16)
        g.text(x + 20, 202, title, "h")
        g.text(x + 20, 224, sub, "m")
        cw = (w - 40 - 20) / 3
        for i, (cls, lines) in enumerate(chips):
            g.box(x + 20 + i * (cw + 10), 240, cw, 70, cls, lines)
        g.box(x + 20, 322, w - 40, 84, "infra", [("t", role), *[("s", r) for r in roles2]])

    node(
        20,
        510,
        "P3 · rke2-master-01",
        "192.168.168.109 · amd64 · Ubuntu 26.04 · RKE2 v1.34 server",
        [
            ("infra", [("sm", "CPU"), ("t", "Intel x86-64"), ("s", "20코어")]),
            ("infra", [("sm", "메모리"), ("t", "128 GB"), ("s", "시스템 메모리")]),
            ("off", [("sm", "GPU"), ("t", "RTX A400 4GB"), ("s", "플랫폼 미사용")]),
        ],
        "K8s 역할: control-plane · etcd + 앱 워커",
        [
            "웹·API 6종, AI(CPU) 2종, DB 3종, 색인 Job",
            "ingress-nginx (80/443) · Docker 레지스트리 (:5000)",
        ],
    )
    node(
        570,
        510,
        "PGX · pgx",
        "192.168.168.108 · arm64 · Ubuntu 24.04 (NVIDIA 커널) · RKE2 agent",
        [
            ("infra", [("sm", "CPU"), ("t", "Arm 20코어"), ("s", "Grace")]),
            ("infra", [("sm", "통합 메모리"), ("t", "128 GB"), ("s", "CPU·GPU 공유")]),
            ("gpu", [("sm", "GPU"), ("t", "NVIDIA GB10"), ("s", "Blackwell")]),
        ],
        "K8s 역할: LLM 전용 워커",
        ["taint dedicated=llm:NoSchedule → vLLM 만 배치", "ingress-nginx (80/443) · GPU Operator"],
    )

    # P3 디스크 3개 — OS NVMe 1TB / DB 전용 NVMe 512GB(별도 추가) / HDD 4TB
    def disk(x, w, title, sub, items, cls="data"):
        g.rect(x, 420, w, 280, cls, 12)
        g.text(x + w / 2, 444, title, "t", "middle")
        g.text(x + w / 2, 462, sub, "sm", "middle")
        for i, lines in enumerate(items):
            g.box(x + 10, 474 + i * 56, w - 20, 48, "lane", lines, rx=8)

    disk(40, 140, "NVMe 1TB", "OS 전용",
         [[("m", "/  (루트 FS)"), ("sm", "OS · 로그")], [("m", "/var/lib/rancher"), ("sm", "etcd · containerd")],
          [("sm", "DiskPressure"), ("sm", "판단 기준")]], "infra")  # fmt: skip
    disk(190, 140, "NVMe 512GB", "DB 전용 (별도 추가)",
         [[("m", "/data/fast"), ("sm", "local-fast PVC")], [("sm", "PostgreSQL 20Gi")], [("sm", "Qdrant 50Gi")],
          [("sm", "Redis 10Gi")]])  # fmt: skip
    disk(340, 170, "HDD 4TB", "대용량 (/data/bulk)",
         [[("m", "documents"), ("sm", "업로드 문서 원본")], [("m", "models"), ("sm", "임베딩·리랭커 모델")],
          [("m", "registry"), ("sm", "이미지 레지스트리")], [("m", "pvc"), ("sm", "local-bulk PVC")]])  # fmt: skip

    # PGX 디스크
    g.rect(590, 420, 470, 280, "data", 12)
    g.text(825, 446, "NVMe SSD 4TB", "t", "middle")
    g.box(
        608,
        462,
        434,
        92,
        "gpu",
        [
            ("m", "/home/<user>/models/Qwen3.8-27B-FP8"),
            ("s", "LLM 가중치 ≈29GB — vLLM 이 /models 로 읽기 전용 마운트"),
            ("sm", "GPU 메모리 사용 상한 90% (gpu-memory-utilization 0.90)"),
        ],
        rx=8,
    )
    g.box(
        608,
        566,
        434,
        56,
        "lane",
        [("s", "OS · /var/lib/rancher"), ("sm", "containerd 이미지 (vLLM arm64 ≈ 수십 GB)")],
        rx=8,
    )
    g.box(
        608,
        634,
        434,
        52,
        "lane",
        [("sm", "DB·문서 저장 없음 — 상태(stateful) 데이터는 모두 P3")],
        rx=8,
    )
    return g


# =====================================================================================
# 03. K8s Pod 배치
# =====================================================================================
POD_H = 96


def pod(g: Svg, x, y, w, cls, name, port, cpu, mem, note=None, h=POD_H) -> None:
    lines = [("t", name), ("m", port), ("sm", cpu), ("sm", mem)]
    if note:
        lines.append(("sm", note))
    g.box(x, y, w, h, cls, lines, align="start", rx=8)


def fig_pods() -> Svg:
    g = Svg("f3", 1220, 1040, "Kubernetes Pod 배치 — 네임스페이스·리소스·포트")

    g.rect(10, 40, 810, 990, "node", 16)
    g.text(26, 28, "P3 · rke2-master-01 (amd64) — 앱·AI(CPU)·데이터", "h")
    g.rect(840, 40, 370, 990, "node", 16)
    g.text(856, 28, "PGX · pgx (arm64, GPU)", "h")

    def ns(x, y, w, h, name):
        g.rect(x, y, w, h, "ns", 10)
        g.label(x + 12, y + 6, name, "alb", "start")

    def chip(x, y, w, cls, s, h=34):
        g.box(x, y, w, h, cls, [("sm", s)], rx=6)

    # kube-system (P3)
    ns(25, 60, 780, 76, "kube-system  (RKE2 내장)")
    cx = 38
    for s, w in [("ingress-nginx :80/:443", 152), ("kube-apiserver :6443", 150), ("etcd", 76), ("coredns", 96),
                 ("canal (CNI)", 108), ("metrics-server", 128)]:  # fmt: skip
        chip(cx, 84, w, "infra", s)
        cx += w + 8

    # rag-app
    ns(25, 152, 780, 262, "rag-app  — 화면·API·워커")
    w4 = 182
    pod(
        g,
        38,
        174,
        w4,
        "web",
        "chat-web",
        ":3000 · Next.js",
        "CPU 100m / 500m",
        "MEM 256Mi / 512Mi",
        "사용자 채팅 화면",
    )
    pod(
        g,
        230,
        174,
        w4,
        "api",
        "chat-gateway",
        ":8001 · REST + /ws",
        "CPU 250m / 1",
        "MEM 512Mi / 1Gi",
        "로그인·질문·실시간",
    )
    pod(
        g,
        422,
        174,
        w4,
        "web",
        "admin-web",
        ":8080 · nginx",
        "CPU 50m / 500m",
        "MEM 64Mi / 256Mi",
        "관리자 화면",
    )
    pod(
        g,
        614,
        174,
        w4 - 6,
        "api",
        "admin-api",
        ":8003 · REST",
        "CPU 500m / 2",
        "MEM 1Gi / 2Gi",
        "문서·채널·색인 Job",
    )
    pod(
        g,
        38,
        290,
        w4,
        "api",
        "rag-api",
        ":8002 · REST",
        "CPU 500m / 2",
        "MEM 1Gi / 3Gi",
        "동기 RAG (평가용)",
    )
    g.rect(236, 296, w4, POD_H, "work", 8)
    pod(
        g,
        230,
        290,
        w4,
        "work",
        "rag-worker ×2",
        "rq worker rag-chat",
        "CPU 500m / 2 (각)",
        "MEM 1Gi / 3Gi (각)",
        "RAG 파이프라인",
    )
    g.box(
        422,
        290,
        368,
        POD_H,
        "note",
        [
            ("alb", "NetworkPolicy (rag-* 네임스페이스 공통)"),
            ("sm", "기본 전부 차단(default-deny) → 플랫폼 NS 끼리만 허용"),
            ("sm", "Ingress → chat-web·chat-gateway·admin-web·admin-api 만"),
            ("sm", "admin-api → kube-apiserver:6443 (색인 Job 생성)"),
        ],
        align="start",
        rx=8,
    )

    # rag-ai (P3)
    ns(25, 430, 780, 140, "rag-ai  — CPU 모델 서빙 (amd64)")
    pod(
        g,
        38,
        452,
        250,
        "ai",
        "embedding-api",
        ":8004 · KURE-v1 (1024차원)",
        "CPU 2 / 6",
        "MEM 4Gi / 8Gi",
        "max_length 2048",
    )
    pod(
        g,
        300,
        452,
        250,
        "ai",
        "reranker-api",
        ":8005 · bge-reranker-v2-m3",
        "CPU 4 / 8",
        "MEM 6Gi / 12Gi",
        "max_length 512",
    )
    g.box(
        562,
        452,
        228,
        POD_H,
        "lane",
        [
            ("alb", "모델 파일"),
            ("m", "hostPath"),
            ("m", "/data/bulk/models"),
            ("sm", "(HDD, 읽기 전용)"),
        ],
        align="start",
        rx=8,
    )

    # rag-data
    ns(25, 586, 780, 190, "rag-data  — 상태 저장 (StatefulSet)")
    for i, (name, port, cpu, mem, pvc) in enumerate(
        [
            ("postgresql-0", ":5432 · PostgreSQL 16", "CPU 1 (요청)", "MEM 2Gi (요청)", "PVC 20Gi"),
            ("qdrant-0", ":6333 · Qdrant 1.12", "CPU 2 (요청)", "MEM 8Gi (요청)", "PVC 50Gi"),
            ("redis-0", ":6379 · Redis 7", "CPU 500m (요청)", "MEM 1Gi (요청)", "PVC 10Gi"),
        ]
    ):
        x = 38 + i * 255
        pod(g, x, 608, 245, "data", name, port, cpu, mem)
        g.box(
            x,
            714,
            245,
            46,
            "lane",
            [("sm", f"{pvc} · local-fast"), ("m", "→ NVMe 512GB /data/fast")],
            rx=6,
        )
        g.arrow(f"M{x + 122},{608 + POD_H} L{x + 122},{711}", "ar-g", "-g")

    # rag-ingestion
    ns(25, 792, 780, 118, "rag-ingestion  — 문서 색인 (필요할 때만 생성)")
    g.box(
        38,
        814,
        300,
        82,
        "work",
        [
            ("t", "index-job-xxxxx"),
            ("m", "parser-indexer · K8s Job"),
            ("sm", "CPU 250m / 2 · MEM 512Mi / 8Gi"),
        ],
        align="start",
        rx=8,
        extra='stroke-dasharray="6 4"',
    )
    g.box(
        350,
        814,
        440,
        82,
        "note",
        [
            ("sm", "업로드하면 admin-api 가 K8s API 로 Job 을 만든다"),
            ("sm", "동시에 1개만 색인 (INDEX_MAX_PARALLEL=1), 나머지는 대기"),
            ("sm", "문서 원본 hostPath /data/bulk/documents · 완료 1시간 뒤 자동 삭제"),
        ],
        align="start",
        rx=8,
    )

    # 기타 인프라
    ns(25, 926, 780, 90, "기타 — 스토리지·GPU·레지스트리")
    chip(38, 954, 240, "infra", "local-path-provisioner (fast·bulk)", 40)
    chip(288, 954, 240, "infra", "gpu-operator (NFD·device-plugin·DCGM)", 40)
    chip(538, 954, 252, "off", "registry:2 :5000 (Docker, K8s 밖)", 40)

    # PGX
    ns(855, 60, 340, 76, "kube-system")
    chip(868, 84, 150, "infra", "ingress-nginx :80/:443")
    chip(1028, 84, 150, "infra", "canal (CNI)")

    ns(855, 152, 340, 418, "rag-ai  — LLM (GPU)")
    g.box(
        870,
        176,
        310,
        280,
        "gpu",
        [
            ("tl", "vllm-llm-0"),
            ("m", ":8000 · Service vllm-service"),
            ("s", "OpenAI 호환 API (vLLM)"),
            ("s", "모델 Qwen3.8-27B-FP8"),
            ("m", "served: internal-rag-llm"),
            ("s", "GPU 1장 (GB10) · 사용률 상한 0.90"),
            ("s", "CPU 8 · MEM 32Gi (요청)"),
            ("s", "컨텍스트 16,384 토큰 · 동시 8건"),
            ("s", "/dev/shm 8Gi (메모리)"),
            ("m", "hostPath /home/<user>/models"),
        ],
        align="start",
        rx=8,
    )
    g.box(
        870,
        470,
        310,
        86,
        "note",
        [
            ("alb", "배치 규칙"),
            ("sm", "nodeSelector ragplatform.io/tier=llm"),
            ("sm", "toleration dedicated=llm"),
            ("sm", "→ PGX 에만 뜨고, 다른 Pod 은 PGX 에 못 뜬다"),
        ],
        align="start",
        rx=8,
    )

    ns(855, 586, 340, 190, "gpu-operator")
    for i, s in enumerate(["nvidia-device-plugin", "container-toolkit", "dcgm-exporter", "gpu-feature-discovery",
                           "node-feature-discovery", "operator-validator"]):  # fmt: skip
        chip(868 + (i % 2) * 160, 612 + (i // 2) * 48, 150, "infra", s)

    # 범례
    g.rect(855, 792, 340, 224, "lane", 10)
    g.text(870, 818, "범례", "lbl")
    for i, (cls, s) in enumerate([("web", "화면 (프런트엔드)"), ("api", "API 서버"), ("work", "백그라운드 작업"),
                                   ("ai", "AI 모델 (CPU)"), ("gpu", "AI 모델 (GPU)"), ("data", "데이터 저장"),
                                   ("note", "규칙·설명")]):  # fmt: skip
        g.rect(872 + (i % 2) * 160, 834 + (i // 2) * 34, 26, 20, cls, 4)
        g.text(906 + (i % 2) * 160, 849 + (i // 2) * 34, s, "sm")
    g.text(870, 990, "CPU/MEM 표기: 요청(request) / 상한(limit)", "sm")
    g.text(870, 1006, "점선 상자: 필요할 때만 생기는 Pod", "sm")
    return g


# =====================================================================================
# 04. 소프트웨어 아키텍처 (논리 구성)
# =====================================================================================
def fig_software() -> Svg:
    g = Svg("f4", 1220, 960, "소프트웨어 아키텍처 — 계층별 구성요소와 호출 관계")

    rows = [("클라이언트", 18, 62), ("진입", 104, 70), ("화면", 200, 84), ("API", 318, 100),
            ("비동기 처리", 452, 100), ("AI 모델", 586, 100), ("데이터", 720, 100), ("공유 라이브러리", 856, 84)]  # fmt: skip
    for name, y, h in rows:
        g.box(10, y, 112, h, "lane", [("lbl", name)], rx=8)

    # 클라이언트
    g.box(205, 18, 300, 62, "user", [("t", "사용자 브라우저"), ("m", "https://chat.rag.lab.local")])
    g.box(800, 18, 300, 62, "user", [("t", "관리자 브라우저"), ("m", "https://rag.lab.local")])
    # 진입
    g.box(
        140,
        102,
        1070,
        74,
        "infra",
        [
            ("t", "ingress-nginx (RKE2 내장, TLS 종료)"),
            ("m", "chat.rag.lab.local : / → chat-web · /api/v1, /ws → chat-gateway (업로드 1MB)"),
            ("m", "rag.lab.local : / → admin-web · /api → admin-api (업로드 110MB)"),
        ],
    )
    g.arrow("M355,80 L355,101")
    g.arrow("M950,80 L950,101")
    # 화면
    g.box(
        260,
        200,
        300,
        84,
        "web",
        [
            ("t", "chat-web"),
            ("s", "Next.js 15 · React 19 · zustand"),
            ("sm", "socket.io-client · 비밀번호 prehash(PBKDF2)"),
        ],
    )
    g.box(
        800,
        200,
        300,
        84,
        "web",
        [
            ("t", "admin-web"),
            ("s", "React 18 · Vite · antd"),
            ("sm", "React Query · nginx 정적 서빙"),
        ],
    )
    g.arrow("M355,174 L355,197")
    g.arrow("M950,174 L950,197")
    # API
    g.box(
        140,
        318,
        360,
        100,
        "api",
        [
            ("t", "chat-gateway"),
            ("s", "FastAPI REST + python-socketio (/ws)"),
            ("sm", "로그인(JWT·scrypt+pepper) · 채널 · 질문 · 피드백"),
            ("sm", "채널 멤버만 접근 (비멤버 = 404)"),
        ],
    )
    g.box(
        520,
        318,
        220,
        100,
        "api",
        [
            ("t", "rag-api"),
            ("s", "FastAPI · 동기 RAG"),
            ("sm", "평가 도구·내부 점검용"),
            ("sm", "(채팅 경로는 worker)"),
        ],
    )
    g.box(
        760,
        318,
        450,
        100,
        "api",
        [
            ("t", "admin-api"),
            ("s", "FastAPI · 문서·ACL·채널·사용자·설정·감사 로그"),
            ("sm", "색인 Job 생성(K8s API) · 원본 미리보기 · Alembic 마이그레이션"),
            ("sm", "역할: SYS_ADMIN · DOC_ADMIN · QUALITY_EVALUATOR · AUDITOR"),
        ],
    )
    g.arrow("M150,174 L150,315", "ar-b", "-b")
    g.label(156, 250, "/api/v1 · /ws", "al", "start")
    g.arrow("M1180,174 L1180,315", "ar-b", "-b")
    g.label(1174, 250, "/api", "al", "end")
    # 비동기
    g.box(
        140,
        452,
        440,
        100,
        "work",
        [
            ("t", "rag-worker ×2  (RQ worker)"),
            ("s", "임베딩 → 검색(채널 필터) → 재정렬 → LLM 스트리밍"),
            ("sm", "claim_job 으로 중복 실행 방지 · 동시 8건"),
            ("sm", "토큰을 socket.io 로 직접 발행 (Redis 경유)"),
        ],
    )
    g.box(
        760,
        452,
        450,
        100,
        "work",
        [
            ("t", "parser-indexer  (K8s Job)"),
            ("s", "파싱(PyMuPDF·pdfplumber) → 청크 → 임베딩"),
            ("sm", "→ Qdrant 저장 → 검증 → 새 버전 활성화"),
            ("sm", "동시 1개 · 진행률을 index_jobs 에 기록"),
        ],
    )
    # AI
    g.box(
        140,
        586,
        300,
        100,
        "ai",
        [
            ("t", "embedding-api"),
            ("s", "KURE-v1 (bge-m3 한국어 미세조정)"),
            ("sm", "1024차원 · CPU · 최대 2048 토큰"),
            ("m", "사용: worker · indexer"),
        ],
    )
    g.box(
        460,
        586,
        280,
        100,
        "ai",
        [
            ("t", "reranker-api"),
            ("s", "bge-reranker-v2-m3"),
            ("sm", "후보 12개 재정렬 · CPU · 512 토큰"),
            ("m", "사용: worker"),
        ],
    )
    g.box(
        760,
        586,
        450,
        100,
        "gpu",
        [
            ("t", "vLLM  (PGX · GB10 GPU)"),
            ("s", "OpenAI 호환 /v1/chat/completions · stream"),
            ("sm", "Qwen3.8-27B-FP8 · served name internal-rag-llm"),
            ("sm", "컨텍스트 16K · 동시 8건 · reasoning-parser qwen3"),
            ("m", "사용: worker · rag-api"),
        ],
    )
    # 데이터
    g.box(
        140,
        720,
        250,
        100,
        "data",
        [
            ("t", "PostgreSQL 16"),
            ("sm", "사용자·채널·멤버·대화(Post)"),
            ("sm", "문서 메타·버전·ACL·색인 Job"),
            ("m", "사용: gateway·worker·admin"),
        ],
    )
    g.box(
        410,
        720,
        230,
        100,
        "data",
        [
            ("t", "Redis 7"),
            ("sm", "RQ 작업 큐 (rag-chat)"),
            ("sm", "socket.io pub/sub · rate limit"),
            ("m", "사용: gateway · worker"),
        ],
    )
    g.box(
        660,
        720,
        270,
        100,
        "data",
        [
            ("t", "Qdrant 1.12"),
            ("sm", "rag_chunks_v1 (1024차원)"),
            ("sm", "payload: 채널 ACL · is_active"),
            ("m", "사용: worker·indexer·admin"),
        ],
    )
    g.box(
        950,
        720,
        260,
        100,
        "data",
        [
            ("t", "문서 원본 파일"),
            ("m", "/data/bulk/documents"),
            ("sm", "hostPath (P3 HDD)"),
            ("m", "사용: admin(쓰기)·indexer"),
        ],
    )
    # 공유 라이브러리
    g.box(
        140,
        856,
        1070,
        84,
        "lane",
        [
            ("t", "libs/* (uv workspace — 서비스 간 공유는 여기로만)"),
            (
                "m",
                "rag_schemas (계약 SSOT)  ·  rag_common (JWT·비밀번호·재시도)  ·  "
                "rag_observability (structlog·Prometheus·마스킹)  ·  chat_adapter (답변 렌더·피드백 토큰·스트림)",
            ),
        ],
    )

    # 인접 계층 호출만 화살표로 — 계층을 건너뛰는 호출은 각 상자의 "사용:" 줄로 표시
    g.arrow("M250,552 L250,583", "ar-v", "-v")  # worker → embedding
    g.arrow("M520,552 L520,583", "ar-v", "-v")  # worker → reranker
    g.arrow("M580,530 C700,530 790,545 790,583", "ar-v", "-v")  # worker → vLLM
    g.label(672, 524, "LLM 호출", "al")
    g.arrow("M985,418 L985,449", "ar-t", "-t")  # admin-api → Job
    g.label(991, 440, "Job 생성", "al", "start")
    return g


# =====================================================================================
# 05. 질문 처리 순서 (시퀀스)
# =====================================================================================
def fig_sequence() -> Svg:
    g = Svg("f5", 1240, 960, "질문 한 건이 처리되는 순서")
    parts = [("user", "브라우저", "chat-web"), ("api", "chat-gateway", ""), ("data", "PostgreSQL", ""),
             ("data", "Redis", "큐·pub/sub"), ("work", "rag-worker", ""), ("ai", "embedding-api", ""),
             ("data", "Qdrant", ""), ("ai", "reranker-api", ""), ("gpu", "vLLM", "PGX GPU")]  # fmt: skip
    step = 135
    xs = [80 + i * step for i in range(len(parts))]
    for x, (cls, name, sub) in zip(xs, parts, strict=True):
        lines = [("t", name)] + ([("m", sub)] if sub else [])
        g.box(x - 62, 16, 124, 56, cls, lines, rx=8)
        g.line(x, 72, x, 850, "life")

    y0, dy = 120, 46
    # worker 활성 구간
    g.rect(xs[4] - 7, y0 + 4 * dy - 14, 14, 10 * dy + 20, "work", 3)

    W = xs[4] + 12  # worker 활성 막대 오른쪽 — 오른쪽으로 나가는 라벨의 시작점
    msgs = [  # (from, to, 라벨, 선 class, marker, 라벨 위치: mid | (anchor, x))
        (0, 1, "① 질문 전송  POST /api/v1/posts (JWT)", "ar-b", "-b", ("start", xs[0] + 8)),
        (1, 2, "② 질문·답변 자리·작업 저장 (1 트랜잭션)", "ar-t", "-t", ("start", xs[1] + 8)),
        (1, 3, "③ 요청 보관 + RQ 큐 등록", "ar-t", "-t", "mid"),
        (1, 0, "④ 201 응답 + post.created (1초 이내)", "ar-t dash", "-t", ("start", xs[0] + 8)),
        (3, 4, "⑤ 작업 꺼냄", "ar-v dash", "-v", "mid"),
        (4, 2, "⑥ claim_job: QUEUED → RUNNING (중복 방지)", "ar-v", "-v", ("end", xs[4] - 14)),
        (4, 5, "⑦ 질문 → 벡터 (query)", "ar-v", "-v", ("start", W)),
        (4, 6, "⑧ 벡터 검색 상위 12개 + 채널 필터", "ar-v", "-v", ("start", W)),
        (4, 7, "⑨ 관련도 재정렬 (45초 넘으면 검색 순서 사용)", "ar-v", "-v", ("start", W)),
        (4, 8, "⑩ 근거를 넣어 답변 요청  stream=True", "ar-v", "-v", ("start", W)),
        (8, 4, "⑪ 토큰이 생성되는 대로 전송", "ar-r dash", "-r", ("start", W)),
        (4, 3, "⑫ llm.stream.delta 발행", "ar-v", "-v", ("end", xs[4] - 14)),
        (3, 1, "⑬ Redis pub/sub → 모든 gateway", "ar-o dash", "-o", "mid"),
        (1, 0, "⑭ 채널 방(room) 멤버 화면에 글자 표시", "ar-o", "-o", ("start", xs[0] + 8)),
        (4, 2, "⑮ 최종 답변 + 근거 표 저장, 작업 DONE", "ar-v", "-v", ("end", xs[4] - 14)),
        (
            4,
            0,
            "⑯ post.updated + llm.stream.end → 화면 확정 (Redis → gateway 경유)",
            "ar-o dash",
            "-o",
            "mid",
        ),
    ]
    for i, (a, b, s, cls, mk, pos) in enumerate(msgs):
        y = y0 + i * dy
        xa, xb = xs[a], xs[b]
        off = 8 if a == 4 else 0
        sx = xa + (off if xb > xa else -off)
        ex = xb - 4 if xb > xa else xb + (12 if b == 4 else 4)
        g.arrow(f"M{sx},{y} L{ex},{y}", cls, mk)
        if pos == "mid":
            g.label((xa + xb) / 2, y - 8, s, "al")
        else:
            g.label(pos[1], y - 8, s, "al", pos[0])
    g.box(
        xs[4] + 20,
        y0 + 15 * dy + 36,
        570,
        82,
        "note",
        [
            ("alb", "체감 시간 (랩 기준)"),
            ("sm", "① ~ ④ 접수: 1초 이내 · ⑦ ~ ⑨ 검색·재정렬: 수 초 (CPU)"),
            ("sm", "⑩ ~ ⑭ 답변 생성: 답변 길이에 따라 수십 초 — 그동안 글자가 계속 나타남"),
            ("sm", "⑫ 토큰은 50ms 또는 64자 단위로 묶어 발행 (화면 부하 감소)"),
        ],
        align="start",
        rx=8,
    )
    return g


# =====================================================================================
# 06. 문서 색인 흐름
# =====================================================================================
def fig_indexing() -> Svg:
    g = Svg("f6", 1220, 640, "문서 한 건이 검색 가능해지기까지 (색인 파이프라인)")

    g.box(
        20,
        30,
        200,
        84,
        "web",
        [("t", "admin-web"), ("s", "문서 업로드"), ("sm", "최대 10개 · 합계 100MB")],
    )
    g.box(
        290,
        30,
        290,
        84,
        "api",
        [
            ("t", "admin-api"),
            ("sm", "확장자·크기·중복(sha256) 검사"),
            ("sm", "POST /documents · /documents/batch"),
        ],
    )
    g.box(
        650,
        30,
        240,
        84,
        "infra",
        [("t", "kube-apiserver"), ("sm", "Job 생성 (ServiceAccount·RBAC)")],
    )
    g.box(
        960,
        30,
        240,
        84,
        "note",
        [
            ("alb", "rag-ingestion 네임스페이스"),
            ("sm", "index-job-xxxxx Pod 기동"),
            ("sm", "parser-indexer 이미지"),
        ],
        align="start",
    )
    g.arrow("M220,72 L287,72", "ar-b", "-b")
    g.arrow("M580,72 L647,72", "ar-t", "-t")
    g.arrow("M890,72 L957,72", "ar")

    g.box(200, 160, 230, 70, "data", [("t", "원본 파일 저장"), ("m", "/data/bulk/documents")])
    g.box(
        450,
        160,
        340,
        70,
        "data",
        [("t", "PostgreSQL"), ("sm", "documents · versions · 채널 ACL · index_jobs(PENDING)")],
    )
    g.arrow("M370,114 L330,157", "ar-t", "-t")
    g.arrow("M500,114 L560,157", "ar-t", "-t")

    g.rect(20, 270, 1180, 270, "node", 14)
    g.text(
        38,
        298,
        "index-job Pod (parser-indexer) — 단계와 진행률 (index_jobs.stage / progress)",
        "lbl",
    )
    g.arrow("M1080,114 L1080,267", "ar")

    stages = [
        ("infra", "① 순서 대기", "WAITING · 0%", ["동시 색인 1개", "앞 작업 끝나면 시작"]),
        ("work", "② 파싱", "PARSING · 5%", ["본문·표 추출", "PyMuPDF + pdfplumber"]),
        ("work", "③ 조각내기", "CHUNKING · 25%", ["≈800 토큰 단위", "문단·표 경계 유지"]),
        ("ai", "④ 임베딩", "EMBEDDING · 45→70%", ["8개씩 묶어 벡터화", "가장 오래 걸림 (CPU)"]),
        ("data", "⑤ 저장", "UPSERTING · 70%", ["벡터 + 채널 ACL", "payload 와 함께"]),
        ("data", "⑥ 검증·활성화", "VALIDATING · 85→100%", ["개수 확인 후", "새 버전 공개"]),
    ]
    sw, gap = 172, 22
    for i, (cls, t, st, desc) in enumerate(stages):
        x = 40 + i * (sw + gap)
        g.box(x, 316, sw, 120, cls, [("t", t), ("m", st), *[("sm", d) for d in desc]], rx=10)
        if i:
            g.arrow(f"M{x - gap},{376} L{x - 3},{376}")
    deps = [
        (1, "data", "원본 파일 읽기"),
        (3, "ai", "embedding-api"),
        (4, "data", "Qdrant"),
        (5, "data", "Qdrant · PostgreSQL"),
    ]
    for i, cls, s in deps:
        x = 40 + i * (sw + gap)
        g.box(x + 10, 476, sw - 20, 40, cls, [("sm", s)], rx=6)
        g.arrow(f"M{x + sw / 2},{473} L{x + sw / 2},{439}", "ar dash")

    g.box(
        20,
        560,
        1180,
        66,
        "note",
        [
            ("alb", "참고 (랩 실측 2026-10-11)"),
            (
                "sm",
                "표가 많은 345쪽 PDF → 1,398 조각, 전체 ≈ 85분 중 임베딩이 ≈ 83분.  진행률은 admin-web '색인 작업' 화면에서 실시간으로 확인 "
                "(임베딩 단계는 10초마다 갱신).  실패하면 단계와 오류가 index_jobs 에 남고 [재시도] 가능.",
            ),
        ],
        align="start",
        rx=8,
    )
    return g


# =====================================================================================
# 07. 채널 격리 (초보자용)
# =====================================================================================
def fig_isolation() -> Svg:
    g = Svg("f7", 1120, 500, "채널 격리 — 내 채널에 허용된 문서만 근거로 쓴다")

    g.box(
        20,
        60,
        230,
        130,
        "web",
        [("t", "채널 rag-hr (인사)"), ("s", "멤버: 김OO"), ("s", '질문: "연차 며칠이에요?"')],
    )
    g.box(
        20,
        270,
        230,
        130,
        "api",
        [
            ("t", "채널 rag-cloud-ops (운영)"),
            ("s", "멤버: 홍OO"),
            ("s", '질문: "1등급 장애 절차?"'),
        ],
    )

    g.box(295, 90, 200, 70, "note", [("alb", "검색 필터"), ("m", "채널 = rag-hr")])
    g.box(295, 300, 200, 70, "note", [("alb", "검색 필터"), ("m", "채널 = rag-cloud-ops")])
    g.arrow("M250,125 L292,125", "ar-b", "-b")
    g.arrow("M250,335 L292,335", "ar-t", "-t")

    g.rect(545, 30, 300, 420, "data", 14)
    g.text(695, 58, "Qdrant — 문서 조각 서고", "t", "middle")
    docs = [
        ("lane", "인사규정집 조각들", "허용: rag-hr", 80),
        ("lane", "장애대응매뉴얼 조각들", "허용: rag-cloud-ops", 170),
        ("lane", "공통 보안수칙 조각들", "허용: rag-hr, rag-cloud-ops", 260),
        ("off", "비활성화한 문서", "is_active = false → 아무도 못 찾음", 350),
    ]
    for cls, a, b, y in docs:
        g.box(565, y, 260, 72, cls, [("s", a), ("m", b)], rx=8)
    g.arrow("M495,118 C525,118 530,116 562,116", "ar-b", "-b")
    g.arrow("M495,130 C530,140 530,290 562,292", "ar-b", "-b")
    g.arrow("M495,330 C530,320 530,210 562,206", "ar-t", "-t")
    g.arrow("M495,342 C530,342 530,300 562,300", "ar-t", "-t")

    g.box(
        885,
        60,
        215,
        130,
        "web",
        [
            ("t", "rag-hr 이 받는 근거"),
            ("s", "○ 인사규정집"),
            ("s", "○ 공통 보안수칙"),
            ("s", "× 장애대응매뉴얼"),
        ],
    )
    g.box(
        885,
        270,
        215,
        130,
        "api",
        [
            ("t", "rag-cloud-ops 이 받는 근거"),
            ("s", "○ 장애대응매뉴얼"),
            ("s", "○ 공통 보안수칙"),
            ("s", "× 인사규정집"),
        ],
    )
    g.arrow("M845,125 L882,125", "ar-b", "-b")
    g.arrow("M845,335 L882,335", "ar-t", "-t")

    g.box(
        20,
        420,
        500,
        66,
        "note",
        [
            ("alb", "두 겹의 벽"),
            ("sm", "1) 채널 멤버가 아니면 채널 자체가 안 보임 (404)"),
            ("sm", "2) 검색할 때 필터를 반드시 먼저 걸어 다른 채널 문서는 후보조차 안 됨"),
        ],
        align="start",
        rx=8,
    )
    return g


# =====================================================================================
# 08. 빌드·배포 흐름
# =====================================================================================
def fig_deploy() -> Svg:
    g = Svg("f8", 1220, 330, "소스 변경이 랩에 반영되는 흐름 (scripts/redeploy_lab.sh)")
    g.rect(10, 14, 1200, 200, "lane", 14)
    g.text(28, 42, "scripts/redeploy_lab.sh — P3 에서 한 번에 실행", "lbl")
    steps = [
        ("user", "① 소스 커밋", ["git commit", "태그 = 커밋 해시"]),
        ("work", "② 이미지 빌드", ["make build-images", "Python 6 + 웹 2 (amd64)"]),
        ("data", "③ 레지스트리 push", ["registry.local:5000", "P3 HDD 에 저장"]),
        ("api", "④ helm upgrade", ["values → poc → lab", "release rag-platform"]),
        ("infra", "⑤ Pod 교체", ["새 이미지 pull", "DB 마이그레이션 Job"]),
    ]
    w, gap = 210, 30
    for i, (cls, t, ls) in enumerate(steps):
        x = 28 + i * (w + gap)
        g.box(
            x,
            66,
            w,
            120,
            cls,
            [("t", t), *[("m" if j == 0 else "sm", s) for j, s in enumerate(ls)]],
        )
        if i:
            g.arrow(f"M{x - gap},126 L{x - 3},126")
    g.box(
        10,
        236,
        1200,
        80,
        "note",
        [
            ("alb", "예외 — vLLM 이미지 (arm64)"),
            (
                "sm",
                "PGX 용 vLLM 이미지(registry.local:5000/ai/vllm-arm64)는 이 스크립트로 빌드하지 않고 별도로 미러링한다.  "
                "모델 교체는 values-lab 의 vllm.modelDir 값 하나로 한다.",
            ),
            (
                "sm",
                "폐쇄망이라 빌드·실행 중 인터넷에서 아무것도 받지 않는다 (모델·패키지 모두 미리 반입).",
            ),
        ],
        align="start",
        rx=8,
    )
    return g


FIGS = [
    ("01-overview", fig_overview),
    ("02-hardware", fig_hardware),
    ("03-k8s-pods", fig_pods),
    ("04-software", fig_software),
    ("05-question-sequence", fig_sequence),
    ("06-indexing-pipeline", fig_indexing),
    ("07-channel-isolation", fig_isolation),
    ("08-deploy-flow", fig_deploy),
]


def main() -> int:
    svgs: dict[str, str] = {}
    for name, fn in FIGS:
        svg = fn().render()
        (HERE / f"{name}.svg").write_text(svg, encoding="utf-8")
        svgs[name] = svg
    try:
        import cairosvg  # type: ignore[import-not-found]
    except ImportError:
        print("cairosvg 없음 — PNG 생략 (uv run --with cairosvg ...)", file=sys.stderr)
    else:
        for name, svg in svgs.items():
            cairosvg.svg2png(bytestring=svg.encode(), write_to=str(HERE / f"{name}.png"), scale=2)
    template = (HERE / "template.html").read_text(encoding="utf-8")
    for name, svg in svgs.items():
        template = template.replace(f"<!--SVG:{name}-->", svg)
    HTML_OUT.write_text(template, encoding="utf-8")
    print(f"wrote {len(svgs)} SVG/PNG + {HTML_OUT.relative_to(HERE.parents[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
