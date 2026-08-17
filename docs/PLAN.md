# docchat — build plan

Assignment: Newpage "AI-Native Builder", Option 1 (Chat With Your Docs).
Deadline: ASAP — target ~2 focused days. Solid basic > over-engineered
(their words, taken seriously).

## Milestones

- [x] M0 Skeleton: repo layout, ports, compose, CI, offline test suite green
- [x] M1 Ingest: PDF/text extraction, chunking wired end to end, documents row
      persisted, upload visible in UI
- [x] M2 Retrieval: pgvector hybrid query finished (metadata `where` -> SQL),
      manual smoke test with 2-3 real PDFs
- [ ] M3 Generation: Claude answers with [n] citations rendered in UI,
      refusal + degrade paths verified by hand
- [x] M4 UI polish: upload states, streaming-feel loading, citation chips,
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
| 13 | `where` -> SQL | filter in Python after search / predicates in the outer SELECT / predicates inside both CTEs | predicates inside the vec and kw CTEs, above their `LIMIT` | both post-filter variants under-return: the CTEs have already spent their pool on non-matching rows, so "ask within this document" can come back empty while matching chunks sit one rank below the cut. `document_id` hits the indexed column, other keys use JSONB containment (`metadata @> ...`), so no caller-supplied key or value is ever interpolated into SQL | decided (M2) |
| 14 | Citation numbering | renumber in the UI / return `{n, source}` objects / rewrite the markers in the answer text | rewrite the markers, `citations` stays `list[str]` | the UI cannot renumber, because it never sees the block numbers Claude cites; structured citations would change the API, the evals and the `Answer` port to carry information the rewrite makes unnecessary. Rewriting makes `citations[j]` the source of every `[j+1]`, so chips and inline numbers cannot drift apart, and repeated sources collapse into one chip. It lives in `app/citations.py` rather than the Claude adapter: it is a property of our contract, not of the vendor, and being pure text it is asserted offline like the rest | decided (M4) |
| 15 | `$` in answers | render as-is / turn single-dollar math off / escape currency before parsing | escape `$` when a digit follows | markdown reads `$` as math, so "over $1,200 and $3,400" parses as one formula and both amounts disappear from the answer - in a document-chat app that is a wrong answer, not a cosmetic bug. Turning single-dollar math off would instead drop the inline formulas these papers are full of. Currency is a `$` followed by a digit and a formula almost never opens on one, so escaping exactly that keeps both; code spans and fences are skipped | decided (M4) |
| 16 | Upload progress | spinner / one bar / measured bytes then indeterminate | two phases | fetch cannot report request-body progress, so the bar needs XHR. The two waits are different in kind: sending bytes is measurable, chunking and embedding is not and is usually the longer one. A single bar would sit at 100% through the slow half, which is exactly the lie a progress bar exists to prevent | decided (M4) |
| 17 | Keyword arm query semantics | keep `plainto_tsquery` (AND) / `websearch_to_tsquery` / OR-join the parsed query's lexemes | OR-join the lexemes, keep `ts_rank_cd` for order | `plainto_tsquery` ANDs every lexeme, so a chunk must contain the whole question to match. Measured on the golden set: 11 of 12 answerable questions matched **zero** chunks, so RRF fused the vector arm with the empty set and the "hybrid" was vector-only for anything longer than a phrase. The tell is in the scores - every hit came back at exactly `1/(60+rank)`, meaning no chunk was ever in both arms. `websearch_to_tsquery` does not fix it: it adds quoting and `OR`/`-` syntax but still ANDs bare terms. The rewrite happens on the *parsed* query (`replace(plainto_tsquery(...)::text, ' & ', ' \| ')::tsquery`), so Postgres keeps doing the tokenising, stemming and stop-word removal and only the operator changes; `plainto_tsquery` never emits phrase operators, so `' & '` is the only separator to swap. OR decides membership, `ts_rank_cd` still decides rank within the arm, and the pool cut to `k*4` keeps the arm selective - matching 137-328 of 376 chunks is fine because only the top 24 reach the fusion. Also adds the statement-level `ORDER BY` the kw CTE never had: `LIMIT` without it takes an arbitrary slice, which was harmless while the arm returned 0-1 rows and is not once it returns hundreds | decided (M5) |
| 18 | Grounding floor vs `RETRIEVAL_K` | keep the constant / derive from `RRF_K` + `RETRIEVAL_K` / drop the floor | derive it, and refuse to start on a value that would delete returnable hits | The two settings were coupled with nothing saying so. A single-arm hit scores `1/(RRF_K + rank)`, so at `K=6` the worst hit the pool can return scores `1/66 = 0.015151` and the shipped floor was `0.015` - a 0.00015 margin. At `K=7` rank 7 scores `1/67 = 0.014925` and every such hit vanishes below the same unchanged constant, with no error and no log line: raising `K` would have *reduced* recall. `single_arm_floor(k)` now derives it and main.py raises at startup if a configured value sits above it. Worth stating plainly: this makes the floor a no-op by construction, which is what the evals showed it already was - RRF scores encode *rank*, not similarity, so rank 1 scores `1/61` whether the match is perfect or worthless, and a rank-based floor cannot express "nothing relevant". Every refusal in the golden set came from the prompt guardrail (`NOT_IN_CONTEXT`), not from the floor. Decision 8 said "both"; honestly it is one. A floor on the vector arm's cosine distance would be a real second guardrail - backlog | decided (M5) |

Add a row every time you make a non-obvious call. This table feeds the README.

## Non-goals (say so in the README, don't build them)

Auth, multi-user tenancy, document deletion UI, streaming tokens, migrations
tooling (init.sql is fine at this scale), conversation memory across questions.

## Backlog (if time remains, in order)

1. Page-level PDF metadata -> citations point at pages, not just files
2. `where` filter UI (ask within one document)
3. LLM-graded answer quality in evals (behind an --llm flag)
4. Reranker stage between retrieval and generation
5. ~~(M4) Render assistant messages as markdown~~ — done in M4: react-markdown
   + remark-gfm, with KaTeX for the formulas (decision 15)
6. ~~(M4) Make the inline `[n]` numbers agree with the citation chips~~ — done
   in M4: `app/citations.py` renumbers and dedupes, so `citations[j]` is the
   source of every `[j+1]` (decision 14)
7. Lazy-load KaTeX: it is ~300 kB of the bundle and nothing needs it until the
   first answer arrives. Not worth the Suspense boundary at this scale
