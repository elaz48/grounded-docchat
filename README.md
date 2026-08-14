# docchat — Chat With Your Docs

Upload documents, ask questions, get grounded answers with citations.
Built for the Newpage AI-Native Builder assignment (Option 1).


## Quick setup

```bash
cp .env.example .env        # add ANTHROPIC_API_KEY and OPENAI_API_KEY
docker compose up --build   # Postgres (pgvector) + API on :8000
cd frontend && npm install && npm run dev   # UI on :5173
```

Run the tests (no API keys, no DB, no network needed):

```bash
pip install -r requirements-dev.txt
pytest
```

## Architecture overview

```
frontend (React/Vite)
   │  POST /api/documents, POST /api/ask
   ▼
FastAPI ── RagService ──┬── Embedder port ──► OpenAI text-embedding-3-small
   │                    ├── VectorStore port ► Postgres + pgvector (hybrid RRF)
   │                    └── AnswerModel port ► Claude (grounded, cited)
   ▼
tests: the same three ports, implemented by placeborag fakes (offline CI)
```

The RagService does not know that OpenAI, pgvector or Claude exist. The ports make it possible to test with deterministic fakes plugged into the same interfaces. Provider changes are a given in AI systems, so the ports turn them into an explicit, testable code path. The scoring convention is app-wide: a higher score is a better match, and the adapter converts whenever a backend reports the opposite (distance-based stores like Chroma vs similarity-based ones like Qdrant). This is an extra abstraction layer in a small app, which I would normally avoid. Here the interfaces sit exactly at the external boundaries, so the cost buys isolation of the three most volatile dependencies: the embedding API, the vector store, and the LLM.


## Productionization (AWS / GCP / Azure / Cloudflare)

[YOUR VOICE — outline, expand each into 2-3 sentences:]
- Managed Postgres with pgvector (RDS / Cloud SQL / Neon) instead of the compose DB
- API container on a managed runtime; docchat is stateless so it scales horizontally
- Object storage for original uploads; queue-based ingestion for large collections
- Secrets in a manager, not env files; per-request auth in front of the API
- Observability: ship the structured logs somewhere queryable; add token/latency metrics
- Cloudflare path specifically: what stays (Postgres), what changes (Workers vs container)

## RAG / LLM approach & decisions

The full decision log with alternatives considered lives in
[docs/PLAN.md](docs/PLAN.md). Summary:

| Decision | Choice | Why (short) |
|---|---|---|
| LLM | Claude Sonnet | [YOUR VOICE] |
| Embeddings | OpenAI text-embedding-3-small | [YOUR VOICE] |
| Vector store | Postgres + pgvector | [YOUR VOICE] |
| Retrieval | Hybrid: HNSW cosine + tsvector keyword, RRF fusion | [YOUR VOICE] |
| Chunking | Paragraph packing, ~1200 chars, 150 overlap | [YOUR VOICE] |
| Orchestration | None (plain Python service) | Three linear steps, no branching or state; my port layer is a few dozen lines I control, a framework would add surface, not value. |
| Guardrails | Context-only system prompt + NOT_IN_CONTEXT refusal + score floor | [YOUR VOICE] |
| Quality | Offline retrieval contract tests + golden-set evals (evals/) | [YOUR VOICE] |
| Observability | Structured JSON logs, request IDs, latency per request | [YOUR VOICE] |

## Key technical decisions

[YOUR VOICE. The three I'd lead with:
1. Testing retrieval with deterministic test doubles (placeborag — my own OSS
   library) instead of mocking API responses: rank order is a real assertion.
2. Hybrid retrieval inside Postgres: tsvector gives keyword search for free,
   RRF fuses it with vector ranking, zero extra services.
3. Degrade, don't collapse: a failing retrieval path returns an honest
   "try again" answer, and there's a test proving it.]

## Engineering standards followed (and skipped)

[YOUR VOICE. Followed: ports/adapters, offline-first tests, CI on every push,
structured logging, containerised dev env, typed dataclasses at boundaries.
Skipped, deliberately, with reasons: auth, migrations tooling, streaming
responses, multi-tenant isolation — name each and say why it's out of scope
for an assignment and what you'd use in production.]

## How I used AI tools

[YOUR VOICE — this section they will read closely. Describe your actual Claude
Code workflow: CLAUDE.md conventions committed to the repo, plan-first
prompting, test-first loops, where you accept AI output as-is vs. where you
rewrite (e.g. SQL and prompts always reviewed by hand), your do's and don'ts.]

## What I'd do differently with more time

[YOUR VOICE: e.g. reranker stage, page-level PDF metadata for deeper citations,
eval set grown from real usage, streaming answers, LangGraph if the flow grew
beyond linear.]

## Screenshots

[Add 2-3 screenshots + optional short video link.]
