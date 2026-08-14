from __future__ import annotations

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import ingest as ingest_module
from .adapters.anthropic_llm import ClaudeAnswerModel
from .adapters.openai_embedder import OpenAIEmbedder
from .adapters.pgvector_store import PgVectorStore
from .config import settings
from .observability import configure_logging, request_context_middleware
from .rag import RagService

configure_logging()

app = FastAPI(title="docchat")
app.middleware("http")(request_context_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wiring happens here and only here; everything below main.py sees ports.
_embedder = OpenAIEmbedder(settings.openai_api_key)
_store = PgVectorStore(settings.database_url)
_service = RagService(
    _embedder,
    _store,
    ClaudeAnswerModel(settings.anthropic_api_key),
    k=settings.retrieval_k,
    min_score=settings.grounding_min_score,
)


class AskRequest(BaseModel):
    question: str


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/documents")
async def upload_document(file: UploadFile) -> dict:
    data = await file.read()
    document_id, chunk_count = ingest_module.ingest(
        file.filename or "upload", data, _embedder, _store,
        target_chars=settings.chunk_target_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    return {"document_id": document_id, "chunks": chunk_count}


@app.post("/api/ask")
def ask(body: AskRequest) -> dict:
    answer = _service.ask(body.question)
    return {"answer": answer.text, "citations": answer.citations, "grounded": answer.grounded}
