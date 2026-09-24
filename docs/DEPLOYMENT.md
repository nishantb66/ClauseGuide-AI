# ClauseGuide AI deployment

ClauseGuide runs as two Vercel projects from this repository:

| Project | Root directory | Framework | Production URL |
| --- | --- | --- | --- |
| clauseguide-ai | repository root | Vite | https://clauseguide-ai.vercel.app |
| clauseguide-ai-api | backend | FastAPI | https://clauseguide-ai-api.vercel.app |

All ClauseGuide accounts, documents, file chunks, analyses, notes, chats,
evaluations, and reports use the single MongoDB namespace csi.clauseguide_ai.
Every record has a kind field. Uploaded documents are split into 2 MB records
so the app can accept files up to 25 MB within Vercel's request limit.
The backend uses temporary disk space only while parsing a file.
The production frontend and backend are deployed on Vercel. The owner chose
an empty MongoDB start; no SQLite data was imported.

## Backend environment

Set these on the clauseguide-ai-api Vercel project for Production and Preview.
Store secrets as sensitive environment variables.

| Variable | Purpose |
| --- | --- |
| MONGODB_URI | MongoDB Atlas connection string for the csi database |
| MONGODB_DATABASE | Must be csi |
| MONGODB_COLLECTION | Must be clauseguide_ai |
| JWT_SECRET, OTP_SECRET | Independent high entropy signing keys |
| GROQ_API_KEY | Contract Q&A model access |
| GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET | Google OAuth web client |
| GOOGLE_REDIRECT_URI | https://clauseguide-ai.vercel.app/google/callback/ |
| GOOGLE_AUTO_SIGNUP_ENABLED | true if Google users may create accounts |
| CORS_ORIGIN_CSV | https://clauseguide-ai.vercel.app |
| SMTP_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_APP_PASSWORD, SMTP_FROM_EMAIL | Email OTP delivery |

The backend is deployed from backend/pyproject.toml and backend/vercel.json.
Keep the repository root as the frontend project root; its existing
vercel.json builds frontend/.

## Frontend environment

Set these on clauseguide-ai for Production:

    VITE_API_BASE=https://clauseguide-ai-api.vercel.app/api
    VITE_GOOGLE_CLIENT_ID=<same Google web client ID as backend>
    VITE_GOOGLE_REDIRECT_URI=https://clauseguide-ai.vercel.app/google/callback/

Vite embeds these values at build time, so redeploy the frontend after any
change. The Google Cloud OAuth client needs the frontend origin and callback
URI in its authorized origin and redirect URI lists.

## Optional legacy data import

The production cutover used an empty collection. If an older SQLite snapshot
is needed later, export its database and uploads/ and reports/ directories.
From backend/, validate the export:

    python -m scripts.migrate_sqlite_to_mongo \
      --database /path/to/export/clauseguide.db \
      --files-root /path/to/export

The command reports table counts and stops if a referenced file is missing.
After checking the counts, add --apply. Re-running the import is safe: it
inserts only missing records and restores the referenced file chunks.
Confirm that the target collection has no conflicting records before importing.

## Production verification

1. Confirm the API health endpoint returns a status of ok.
2. Confirm the frontend bundle contains the Vercel API URL and no old API URL.
3. Verify sign-in, a document upload over 4.5 MB, analysis, PDF review, chat,
   notes, report download, and evaluation on the Vercel backend.
4. Verify the Google OAuth redirect URI and complete sign-in with a real Google
   account when one is available.
5. The owner will delete the old deployment after checking the live site.
