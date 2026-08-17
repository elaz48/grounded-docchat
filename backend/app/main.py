from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import ingest as ingest_module
from .adapters.anthropic_llm import ClaudeAnswerModel
from .adapters.openai_embedder import OpenAIEmbedder
from .adapters.pgvector_store import RRF_K, PgVectorStore, single_arm_floor
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

# RETRIEVAL_K and GROUNDING_MIN_SCORE are coupled, and the coupling used to
# be invisible (PLAN.md decision 18). RRF scores a single-arm hit at
# 1/(RRF_K + rank), so at k=6 the last hit the pool can return scores
# 1/66 = 0.015151 - and the shipped floor was 0.015, clearing it by 0.00015.
# Raise k to 7 and rank 7 scores 1/67 = 0.014925: every such hit disappears
# below the same unchanged constant, silently. So derive the floor from the
# constants it depends on, and refuse to start on a value that would delete
# hits the retriever was asked for.
_pool_floor = single_arm_floor(settings.retrieval_k)
_min_score = (
    settings.grounding_min_score
    if "grounding_min_score" in settings.model_fields_set
    else _pool_floor
)
if _min_score > _pool_floor:
    raise RuntimeError(
        f"GROUNDING_MIN_SCORE={_min_score} exceeds the RRF single-arm floor "
        f"{_pool_floor:.6f} implied by RETRIEVAL_K={settings.retrieval_k}. "
        f"Hits ranked below {int(1 / _min_score) - RRF_K} in a single arm would be "
        "dropped after retrieval asked for them; lower the floor or lower RETRIEVAL_K."
    )

_service = RagService(
    _embedder,
    _store,
    ClaudeAnswerModel.from_api_key(settings.anthropic_api_key),
    k=settings.retrieval_k,
    min_score=_min_score,
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
def upload_document(file: UploadFile) -> dict:
    # Deliberately sync: ingest() extracts, chunks and embeds synchronously,
    # and on an async endpoint all of that runs on the event loop, so one
    # upload of a large PDF stalls every other request. A sync def hands the
    # whole handler to the threadpool instead; file.file is the already-parsed
    # spooled body, so the read needs no await.
    data = file.file.read()
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
