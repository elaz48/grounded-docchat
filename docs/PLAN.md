# docchat — build plan

Assignment: Newpage "AI-Native Builder", Option 1 (Chat With Your Docs).
Deadline: ASAP — target ~2 focused days. Solid basic > over-engineered
(their words, taken seriously).

## Milestones

- [x] M0 Skeleton: repo layout, ports, compose, CI, offline test suite green
- [ ] M1 Ingest: PDF/text extraction, chunking wired end to end, documents row
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

Add a row every time you make a non-obvious call. This table feeds the README.

## Non-goals (say so in the README, don't build them)

Auth, multi-user tenancy, document deletion UI, streaming tokens, migrations
tooling (init.sql is fine at this scale), conversation memory across questions.

## Backlog (if time remains, in order)

1. Page-level PDF metadata -> citations point at pages, not just files
2. `where` filter UI (ask within one document)
3. LLM-graded answer quality in evals (behind an --llm flag)
4. Reranker stage between retrieval and generation
