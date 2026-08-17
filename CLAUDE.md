# CLAUDE.md — conventions for AI-assisted sessions in this repo

This file is part of the deliverable: the assignment asks how I make
AI-assisted development repeatable. These are the standing rules.

## Workflow
- Plan first: consult docs/PLAN.md before coding; new non-obvious decisions
  get a row in the decision log in the same commit.
- Test-first for logic: chunking, retrieval contract, and service behaviour
  are specified in backend/tests before implementation changes.
- Run `pytest` after every change; the suite is offline and takes a few
  seconds, there is no excuse to skip it.
- Run `ruff check .` before committing.

## Boundaries
- Everything below backend/app/main.py depends on ports (backend/app/ports.py),
  never on a vendor SDK. New providers = new adapter, wiring only in main.py.
- Score convention is app-wide: higher is better. Convert at the adapter.
- db/init.sql changes require a decision-log row (embedding dimension is a
  contract, not a config value).

## Human-review-required (never accept generated output blind)
- SQL (especially the hybrid retrieval query)
- Prompts (adapters/anthropic_llm.py SYSTEM)
- Anything in README.md — that file must be my voice, per the assignment

## Style
- Python 3.12, type hints at boundaries, dataclasses frozen.
- Small commits, imperative messages, reference the milestone (M1, M2...).
