# Production Cloud Deployment Guide: Render Backend + Vercel Frontend

**Dr. B. R. Ambedkar Digital Heritage Archive (SIH261096)**  
**Target Repository**: `https://github.com/tushar-bit-sketch/drambedkar-ai.git`  
**Live Frontend**: `https://frontend-kappa-six-80.vercel.app`

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT BROWSER                          │
│         https://frontend-kappa-six-80.vercel.app            │
└──────────────────────────────┬──────────────────────────────┘
                               │
               HTTPS API Calls │ (/api/v1/*)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 RENDER.COM FASTAPI BACKEND                  │
│       https://ambedkar-archive-backend.onrender.com         │
│  - Python 3.13 + Uvicorn                                    │
│  - Bundled SQLite (archive_phase1.db) with 20+ docs & users │
│  - Zero-Hallucination RAG & Hybrid Retrieval Engine         │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Step 1: Deploy Backend to Render (Free Tier, 2 Minutes)

1. Open **[Render Dashboard](https://dashboard.render.com/)** and click **New +** > **Blueprint**.
2. Connect your GitHub repository:
   ```
   https://github.com/tushar-bit-sketch/drambedkar-ai
   ```
3. Render will automatically detect the updated `render.yaml` with the **free** tier configuration:
   - **Name**: `ambedkar-archive-backend`
   - **Plan**: `free` ($0/month)
   - **Runtime**: Python 3.13
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Database**: Bundled `archive_phase1.db` (auto-loaded with all seeded records)
4. Click **Apply**.
5. Once deployment completes, copy your live backend URL:
   ```
   https://<your-service-name>.onrender.com
   ```

---

## 3. Step 2: Connect Frontend on Vercel

1. Open **[Vercel Dashboard](https://vercel.com/)** > Select the **`frontend`** project.
2. Go to **Settings** > **Environment Variables**.
3. Add a new variable:
   - **Key**: `VITE_API_URL`
   - **Value**: `https://<your-service-name>.onrender.com/api/v1`
   - **Environments**: Check **Production**, **Preview**, and **Development**.
4. Click **Save**.
5. Go to **Deployments** > click the three dots on the latest deployment > **Redeploy** (or trigger a new build via `npx vercel --prod`).

---

## 4. Step 3: Verification Checklist

Once both services are running, verify:
- [ ] Backend Health: `https://<your-backend>.onrender.com/api/v1/health` returns `{"status": "healthy"}`
- [ ] Search API: `https://<your-backend>.onrender.com/api/v1/search?q=Ambedkar` returns verified documents
- [ ] Live Frontend: Open `https://frontend-kappa-six-80.vercel.app/search` — search results load live from the backend
- [ ] Admin Portal: Open `https://frontend-kappa-six-80.vercel.app/admin` — real-time statistics and user records render cleanly
