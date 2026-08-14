"""Golden-set evals against the running API.

Usage:
    docker compose up -d && python evals/run_evals.py

Replace evals/golden.jsonl with 10-15 questions about YOUR uploaded documents:
- expect_citation: a source filename that must appear in the citations
- expect_refusal: true for questions the corpus cannot answer (the guardrail
  must refuse instead of hallucinating)

Measures retrieval + grounding, not prose quality. LLM-graded answer quality
is backlog (PLAN.md #3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

API = "http://localhost:8000/api/ask"


def main() -> int:
    cases = [
        json.loads(line)
        for line in Path(__file__).with_name("golden.jsonl").read_text().splitlines()
        if line.strip()
    ]
    passed = 0
    for case in cases:
        response = httpx.post(API, json={"question": case["question"]}, timeout=60)
        response.raise_for_status()
        body = response.json()

        if case.get("expect_refusal"):
            ok = body["grounded"] is False
        else:
            ok = body["grounded"] and case["expect_citation"] in body["citations"]

        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['question']!r}  citations={body['citations']}")

    print(f"\n{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
