from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile
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
# One Postgres adapter serves both the VectorStore and DocumentStore ports.
_embedder = OpenAIEmbedder(settings.openai_api_key)
_store = PgVectorStore.from_url(settings.database_url)
_service = RagService(
    _embedder,
    _store,
    ClaudeAnswerModel.from_api_key(settings.anthropic_api_key),
    k=settings.retrieval_k,
    min_score=settings.grounding_min_score,
)


class AskRequest(BaseModel):
    question: str


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/documents")
def list_documents() -> dict:
    return {
        "documents": [
            {"document_id": d.id, "filename": d.filename, "chunks": d.chunk_count}
            for d in _store.list_documents()
        ]
    }


@app.post("/api/documents")
async def upload_document(file: UploadFile) -> dict:
    data = await file.read()
    try:
        document_id, chunk_count = ingest_module.ingest(
            file.filename or "upload", data, _embedder,
            store=_store, documents=_store,  # one adapter, two ports
            target_chars=settings.chunk_target_chars,
            overlap_chars=settings.chunk_overlap_chars,
        )
    except ingest_module.EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document_id": document_id, "chunks": chunk_count}


@app.post("/api/ask")
def ask(body: AskRequest) -> dict:
    answer = _service.ask(body.question)
    return {"answer": answer.text, "citations": answer.citations, "grounded": answer.grounded}
