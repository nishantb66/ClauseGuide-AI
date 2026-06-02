# ClauseGuide AI Backend

Backend for ClauseGuide AI with Part 1 through Part 5 implemented.

## Features in current phase

- Document upload (PDF, DOCX, TXT)
- Page-wise text extraction and cleaning
- Legal-aware chunking
- Local embeddings (deterministic fallback + optional sentence-transformers)
- Hybrid retrieval (semantic + keyword)
- Contract type detection
- Clause extraction and classification
- Deterministic rule-based risk analysis
- Clause explorer APIs
- Advanced retrieval:
  - query intent detection and rewriting
  - clause-aware filtering
  - reranking (heuristic + optional cross-encoder)
  - confidence scoring and safe fallback
- Chat Q&A with source citations and legal disclaimer
- Final report generation and download (markdown/text)
- Evaluation framework with custom legal metrics and optional RAGAS aggregate metrics
- SQLite default for local setup (PostgreSQL + pgvector migration planned in later phase)

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

Optional RAGAS support:

```bash
pip install -e '.[evaluation]'
```

## Run tests

```bash
pytest
```
