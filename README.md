# ClauseGuide AI

ClauseGuide AI is an AI-powered contract risk analyzer built as a phased production-style project.

## Current Status

Part 1 through Part 5 are implemented:

- FastAPI backend architecture with typed schemas and modular services
- Upload support for PDF, DOCX, and TXT
- Page-wise parsing, text cleaning, and legal-aware chunking
- Local embedding service (deterministic fallback + optional sentence-transformers)
- Hybrid retrieval (semantic + keyword)
- Contract type detection
- Clause extraction and classification pipeline (keyword + embedding signals)
- Deterministic rule-based risk engine with clause-level findings
- Clause explorer APIs and frontend integration
- Advanced retrieval features (intent detection, query rewriting, clause-aware filtering, reranking, confidence scoring)
- Contract Q&A with citation verification and legal disclaimer
- Final report generation with downloadable markdown/text outputs
- Part 5 evaluation pipeline:
  - run-based evaluation framework
  - custom legal metrics (amount/date/clause/risk/citation/refusal)
  - retrieval-quality metrics (faithfulness/relevancy/context precision/context recall)
  - optional RAGAS aggregate integration
  - evaluation dashboard in frontend
- Unit tests across Part 1 through Part 5 services

## Project Structure

```text
ClauseGuide AI/
  backend/
  frontend/
  docs/
  docker-compose.yml
```

## Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8000
```

Optional RAGAS support:

```bash
pip install -e '.[evaluation]'
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

## API Endpoints (Part 5)

- `POST /api/documents/upload`
- `POST /api/documents/{document_id}/process`
- `GET /api/documents`
- `GET /api/documents/{document_id}/analysis`
- `GET /api/documents/{document_id}/clauses`
- `GET /api/documents/{document_id}/clauses/{clause_id}`
- `POST /api/documents/{document_id}/chat`
- `POST /api/documents/{document_id}/report`
- `GET /api/documents/{document_id}/reports`
- `GET /api/reports/{report_id}`
- `GET /api/reports/{report_id}/download`
- `POST /api/documents/{document_id}/evaluations/run`
- `GET /api/documents/{document_id}/evaluations`

## Legal Safety

- The app includes legal disclaimers in responses.
- It does not provide legal advice.
- Unsupported answers default to conservative fallback behavior.

## Next Phase (Part 6)

- Deployment hardening, CI/CD, and production packaging
