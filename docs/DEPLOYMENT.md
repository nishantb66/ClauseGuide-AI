# ClauseGuide AI Deployment

This repository is structured as a monorepo:

- `backend/` FastAPI app for Render
- `frontend/` Vite React app for Vercel

## Backend: Render

Use the root `render.yaml` blueprint.

Required secret/environment values to set in Render:

- `GROQ_API_KEY`
- `SMTP_USERNAME`
- `SMTP_FROM_EMAIL`
- `SMTP_APP_PASSWORD`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `CORS_ORIGIN_CSV`

Recommended production values:

- `GOOGLE_REDIRECT_URI=https://YOUR_VERCEL_DOMAIN/google/callback/`
- `CORS_ORIGIN_CSV=https://YOUR_VERCEL_DOMAIN`

After Render creates the backend, copy its URL. The API base will be:

```text
https://YOUR_RENDER_SERVICE.onrender.com/api
```

## Frontend: Vercel

Create a Vercel project from this GitHub repository and set:

- Root Directory: `frontend`
- Build Command: `npm run build`
- Output Directory: `dist`

Required Vercel environment variable:

```text
VITE_API_BASE=https://YOUR_RENDER_SERVICE.onrender.com/api
```

## Google OAuth

Update Google Cloud OAuth settings after deployment:

Authorized JavaScript origins:

```text
https://YOUR_VERCEL_DOMAIN
```

Authorized redirect URIs:

```text
https://YOUR_VERCEL_DOMAIN/google/callback/
```

Then set the same redirect URI in Render as `GOOGLE_REDIRECT_URI`.

## Storage Note

The current Render config uses SQLite with a Render disk mounted at `backend/storage`. This is fine for a demo deployment. For larger production use, migrate to PostgreSQL/object storage.
