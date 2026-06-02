# Implementation Status (May 31, 2026)

## Implemented now

- Backend service architecture under `backend/app`
- Document ingestion pipeline
- Hybrid retriever + citation verifier
- Contract chat endpoint with persistence
- Contract type detection
- Clause extraction and classification storage
- Deterministic risk engine with structured findings
- Clause explorer APIs
- Frontend integration for analysis, clause explorer, and chat
- Advanced RAG upgrades:
  - query intent detection
  - query rewriting
  - clause-aware retrieval filtering
  - reranking stage
  - confidence scoring formula
  - unsupported-answer fallback hardening
- Report module:
  - generated final risk reports
  - markdown/text export
  - downloadable report endpoint
  - report list and report summary endpoints
  - frontend report generation and download actions
- Part 5 evaluation module:
  - evaluation runs and per-case result persistence
  - default auto-generated test cases for each analyzed contract
  - optional RAGAS aggregate metric integration
  - custom legal metrics (amount/date/clause/risk/citation/refusal)
  - evaluation APIs and frontend dashboard
- Test coverage across Part 1 through Part 5 core services

## Known limitations

- Default DB is SQLite for zero-friction startup; PostgreSQL + pgvector migration is still pending
- Optional RAGAS mode requires extra dependencies (`pip install -e '.[evaluation]'`)
- Heuristic answer fallback is used when Groq API key is not configured
- OCR for scanned PDFs is deferred to a future phase
