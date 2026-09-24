# ClauseGuide AI backend

FastAPI service for legal document analysis. Accounts, document bytes,
analyses, chats, notes, evaluations, and reports are stored in the single
MongoDB collection csi.clauseguide_ai.

## Local setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e '.[dev]'

Create a local, untracked .env with MONGODB_URI, JWT_SECRET, OTP_SECRET,
Google OAuth settings, email OTP settings, and GROQ_API_KEY. Then run:

    uvicorn app.main:app --reload --port 8000

Run tests with pytest. See ../docs/DEPLOYMENT.md for Vercel environment
variables and data import.
