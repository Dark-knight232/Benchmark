# Orchard Gate — Prospect Dashboard (Vercel frontend)

This directory is gitignored because the live frontend is deployed from
`frontend-deploy/`. This copy is the same file, kept in the repo so the
latest version is always recoverable.

## Run locally

```bash
python -m http.server 5500
# then open http://localhost:5500/coffee_dashboard.html
```

## Deploy to Vercel

```bash
cd frontend-deploy
vercel --prod
```

The page calls the backend at `https://orchard-gate-api.onrender.com`, so no
env configuration is needed.