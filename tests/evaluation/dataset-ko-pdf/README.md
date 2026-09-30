# dataset-ko-pdf — 한글 공공 PDF(docs/pdf/*) 임베딩 A/B 용 평가셋

rke2 가이드 §5.1.2 의 bge-m3 ↔ KURE-v1 비교에 쓴다. 기본 데이터셋(`../dataset`, samples/*.md 기준)과 분리 —
docs/pdf 5종을 채널 `c0000000-…-001`(rag-cloud-ops)에 **파일명 stem 을 title 로** 업로드한 경우에만 유효하다.

    RAG_API_URL=http://localhost:8002 uv run python -m evaluation.runner \
      --dataset tests/evaluation/dataset-ko-pdf --out reports/eval_ko_pdf_<model>.md

ground truth 는 파서 출력 텍스트로 쪽 번호를 확인해 작성했다 (1-based PDF 쪽 번호).
kp005·kp006 은 MS Print-To-PDF 문서(4번) — pdfplumber 대체 경로(PDF_TEXT_ENGINE=auto) 회귀 확인용.
