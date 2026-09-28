"""RAG Domain Layer — 프레임워크 비종속 (NFR-MAINT-005).

이 패키지는 FastAPI / LangChain / socket.io 타입을 import 하지 않는다.
순수 Python + rag_schemas (+ qdrant filter 모델) 만 의존한다.
"""
