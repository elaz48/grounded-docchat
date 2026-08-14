# docchat — build plan

Assignment: Newpage "AI-Native Builder", Option 1 (Chat With Your Docs).
Deadline: ASAP — target ~2 focused days. Solid basic > over-engineered
(their words, taken seriously).

## Milestones

- [x] M0 Skeleton: repo layout, ports, compose, CI, offline test suite green
- [x] M1 Ingest: PDF/text extraction, chunking wired end to end, documents row
      persisted, upload visible in UI
- [ ] M2 Retrieval: pgvector hybrid query finished (metadata `where` -> SQL),
      manual smoke test with 2-3 real PDFs
- [ ] M3 Generation: Claude answers with [n] citations rendered in UI,
      refusal + degrade paths verified by hand
- [ ] M4 UI polish: upload states, streaming-feel loading, citation chips,
      empty states with direction (see frontend/src/styles.css tokens)
- [ ] M5 Evals: 10-15 golden questions against my own real documents,
      `python evals/run_evals.py` prints hit rate + refusal correctness
- [ ] M6 Ship: README rewritten in my voice, screenshots, short video,
      squash noisy commits, push, send link

## Decision log

Status: proposed = my recommendation from planning; confirm or overturn as you build.

| # | Decision | Options considered | Choice | Why | Status |
|---|---|---|---|---|---|
| 1 | Vector store | pgvector / Chroma / Pinecone | pgvector | I know Postgres deeply; one DB for data + vectors + keyword search; JD names it | proposed |
| 2 | Retrieval | vector-only / hybrid RRF / rerank stage | hybrid RRF | keyword search is free in Postgres; rerank is backlog | proposed |
| 3 | Embeddings | OpenAI 3-small / Voyage / local | OpenAI 3-small | cheap, ubiquitous, 1536 dims; swap path is tested | proposed |
| 4 | LLM | Claude Sonnet / GPT / both | Claude Sonnet | strongest grounded-answer behaviour; my daily driver | proposed |
| 5 | Orchestration | LangGraph / LlamaIndex / none | none | linear 3-step pipeline; a framework adds surface, not value | proposed |
| 6 | Chunking | paragraph packing / semantic / per-page | paragraph packing + overlap | explainable, testable, good enough; semantic is backlog | proposed |
| 7 | Retrieval testing | mock API responses / live calls / placeborag | placeborag | deterministic rank-order assertions offline; my own OSS lib | decided |
| 8 | Guardrail | prompt-only / score floor / both | both | prompt handles content, score floor handles "nothing relevant" | proposed |
| 9 | Document registry | method on VectorStore / separate DocumentStore port / no port (SQL in ingest) | separate `DocumentStore` port | chunks.document_id is a FK, so the row must exist first; a separate port puts that ordering in `ingest()`'s signature instead of hiding it in an adapter. One Postgres class implements both ports; only main.py knows that | decided (M1) |
| 10 | Document chunk count | denormalized column on documents / COUNT over chunks | COUNT over chunks | the UI wants the number, but a stored counter is a second source of truth to keep in sync — and adding the column would change db/init.sql, which is a contract | decided (M1) |
| 11 | psycopg type adaptation | cast in SQL / wrap at the call site / register on the pool | `Json()` + `Vector()` at the call site, `register_vector` on the pool | psycopg binds neither a bare dict to JSONB nor a bare list to `vector`; both fail only against a live DB, so the wrappers are asserted in backend/tests/test_pgvector_adapter.py against a fake cursor | decided (M1) |
| 12 | Empty/scanned upload | index an empty doc / silent 200 / 400 with a reason | `EmptyDocumentError` -> HTTP 400 | a scanned PDF is the most likely real upload failure; failing at upload with "this needs OCR" beats a document that exists but can never answer anything | decided (M1) |

Add a row every time you make a non-obvious call. This table feeds the README.

## Non-goals (say so in the README, don't build them)

Auth, multi-user tenancy, document deletion UI, streaming tokens, migrations
tooling (init.sql is fine at this scale), conversation memory across questions.

## Backlog (if time remains, in order)

1. Page-level PDF metadata -> citations point at pages, not just files
2. `where` filter UI (ask within one document)
3. LLM-graded answer quality in evals (behind an --llm flag)
4. Reranker stage between retrieval and generation
