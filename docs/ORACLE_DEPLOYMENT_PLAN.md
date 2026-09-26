# Oracle Cloud Always Free Deployment Plan
**Ambedkar Digital Heritage Archive (SIH26096)**  
**Document Reference**: `docs/ORACLE_DEPLOYMENT_PLAN.md`  
**Target Environment**: Oracle Cloud Infrastructure (OCI) Always Free VM (Ubuntu 22.04/24.04 LTS — Ampere A1 or E2.1.Micro)  
**Deployment Model**: Single-Host Production Orchestration (Nginx + React/Vite + FastAPI + PostgreSQL/pgvector + Redis + Workers)

---

## Executive Summary & Guiding Directives

This deployment plan specifies the end-to-end operational roadmap for hosting the complete Ambedkar Digital Heritage Archive on an **Oracle Cloud Infrastructure (OCI) Always Free VM** as **ONE unified, self-contained production deployment**.

### Inviolable Constraints:
1. **Zero UI Redesign**: No visual changes, modifications to components, or CSS refactoring.
2. **Zero Architecture Rewrite**: Preserve FastAPI modular router structure, React/Vite SPA layout, and Dublin Core archival data models.
3. **No Mock APIs**: Every route in production executes against real PostgreSQL storage, verified document checksums, and authentic retrieval algorithms.
4. **No Localhost Presumptions**: All inter-service communication, reverse-proxy hops, and database bindings must use verified network configurations and UNIX sockets/localhost host bindings behind Nginx.
5. **Radical Curatorial Honesty**: Production vector retrieval utilizes PostgreSQL + `pgvector` (`VECTOR_BACKEND=PGVECTOR`); zero hallucination or artificial metrics.

---

## 20-Point Comprehensive Repository Audit

| # | Audit Item | Findings & Repository Location | Production Implication for Oracle VM |
| :--- | :--- | :--- | :--- |
| **1** | **Frontend Entrypoint** | `frontend/src/main.tsx` mounts `frontend/src/App.tsx` into `<div id="root">` inside `frontend/index.html`. | Served as static pre-compiled SPA bundle via Nginx root `/usr/share/nginx/html` or `/var/www/archive/frontend/dist`. |
| **2** | **Backend Entrypoint** | `backend/app/main.py` defines ASGI application instance `app = FastAPI(...)` with `lifespan` managing startup DB migrations and initial seeding. | Started via Uvicorn multi-worker daemon (`uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4`). |
| **3** | **Frontend Build Command** | `npm run build` inside `frontend/` (executes `tsc -b && vite build`). Produces static assets in `frontend/dist/`. | Executed during CI/CD or VM bootstrap. Requires Node.js 20+ / 22+ LTS. |
| **4** | **Backend Start Command** | Local dev: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`. Production: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`. | Run via systemd daemon (`ambedkar-backend.service`) or Docker Compose backend container. |
| **5** | **Database Configuration** | Defined in `backend/app/core/config.py` and `backend/app/db/session.py`. Connection string driven by `DATABASE_URL`. Connection pool settings: `DATABASE_POOL_SIZE=20`, `DATABASE_MAX_OVERFLOW=10`, `DATABASE_POOL_PRE_PING=True`. | Migrate from development SQLite (`archive_phase1.db`) to PostgreSQL 16 with native `pgvector` extension. |
| **6** | **Localhost/127.0.0.1 References** | Found in `backend/app/core/config.py` (`REDIS_URL`, `CELERY_BROKER_URL`, default `BACKEND_CORS_ORIGINS`), `backend/app/core/security_middleware.py` (default client IP fallback), `frontend/src/config/api.ts` (dev proxy check). | Safe when services bind to `127.0.0.1` locally on the VM behind Nginx reverse proxy. |
| **7** | **Hardcoded URLs** | `frontend/src/config/api.ts` contained development URLs. Backend CORS allowed `https://frontend-kappa-six-80.vercel.app` and `https://.*\.vercel\.app`. | Replaced in production by relative `/api/v1` URL in frontend (same-origin) and binding Oracle VM public IP/domain into `BACKEND_CORS_ORIGINS`. |
| **8** | **VITE_API_URL Usage** | `frontend/src/config/api.ts` consumes `import.meta.env.VITE_API_URL`. Currently defaults to `/api/v1` for both dev proxy and same-origin production. | In Oracle deployment, Nginx serves frontend and backend on port 80/443; leaving `VITE_API_URL` empty or setting to `/api/v1` ensures 100% same-origin operation. |
| **9** | **FastAPI CORS Configuration** | `backend/app/main.py` applies `CORSMiddleware` using `settings.BACKEND_CORS_ORIGINS` and `allow_origin_regex=r"https://.*\.vercel\.app"`. | Extend `BACKEND_CORS_ORIGINS` to include the Oracle VM's public IP (`http://<ORACLE_VM_IP>`) and custom domain (`https://<DOMAIN>`). |
| **10** | **File Upload/Storage Implementation** | `backend/app/services/storage.py` (`StorageService`). Saves files to `backend/storage/uploads` with SHA-256 validation. Optional S3 object storage via boto3 if env vars present. | Mount `/var/www/ambedkar-archive/storage/` as a persistent block volume directory with dedicated subdirectories (`uploads`, `derivatives`, `media`, `audio`). |
| **11** | **OCR Dependencies** | `backend/app/services/ocr/` provides PaddleOCR (`paddle_provider.py`) and Tesseract (`tesseract_provider.py`). Image processing via OpenCV (`opencv-python-headless`) and Pillow. | Install OS packages: `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-hin`, `tesseract-ocr-mar`, `libgl1-mesa-glx`, `libglib2.0-0`. Python: `pytesseract`. |
| **12** | **RAG/Embedding Dependencies** | `backend/app/services/search/embeddings/bge_m3.py` (BAAI/bge-m3), `backend/app/services/search/vector_store/pgvector_store.py` (PostgreSQL + pgvector), Hugging Face API router client. | Enable `vector` extension in PostgreSQL. On ARM Ampere A1 (24GB RAM), sentence-transformers runs locally or via Hugging Face router token. |
| **13** | **Background Jobs** | FastAPI `BackgroundTasks` in `ocr.py`, `import_pipeline.py`. Optional Celery task queue configured with Redis broker in `config.py`. | Start Redis server (`redis-server`). Run background ingestion workers alongside FastAPI. |
| **14** | **Environment Variables** | Consolidated in `backend/app/core/config.py` and `backend/.env.example`. | Require production `.env` containing secure `SECRET_KEY`, PostgreSQL `DATABASE_URL`, and OCI paths. |
| **15** | **Authentication & RBAC** | JWT Bearer tokens via `python-jose[cryptography]` and `passlib[bcrypt]`. 5 Roles: `SUPER_ADMIN`, `ARCHIVIST`, `RESEARCHER`, `REVIEWER`, `VISITOR`. | Default seed creates 4 official institutional accounts with bcrypt passwords. Tokens expire in 480 minutes (8 hours). |
| **16** | **Existing Docker Configuration** | `docker-compose.yml` (development), `docker-compose.production.yml` (full multi-service: postgres, redis, backend, nginx), `backend/Dockerfile`, `frontend/Dockerfile`. | Production Compose file is already available and tailored for containerized VM deployment. |
| **17** | **Existing Deployment Scripts** | `scripts/kiosk/linux_kiosk_launch.sh`, `scripts/backup/backup_archive.py`, `scripts/backup/restore_verification.py`. | Provide single-command bootstrap script for Oracle VM setup. |
| **18** | **SQLite/Dev Assumptions** | SQLite database file (`archive_phase1.db`) used in dev/serverless. `VECTOR_BACKEND=sqlite_dev_fallback`. | Switch to PostgreSQL 16 + pgvector (`VECTOR_BACKEND=PGVECTOR`). Run Alembic migrations and master seed script. |
| **19** | **Local Filesystem Paths** | Paths in `storage.py` and `config.py` use relative directory lookups (`../../storage/uploads`). | Ensure system user (`archive`) owns the storage tree or bind-mount persistent volumes. |
| **20** | **Ports Other Than HTTP/HTTPS** | Port 8000 (FastAPI), 5432 (Postgres), 6379 (Redis). | **Never expose to public internet**. Bind strictly to `127.0.0.1` or internal Docker network. Only ports 80 (HTTP), 443 (HTTPS), and 22 (SSH) open in OCI Security List. |

---

## A. Current Architecture (As Audited)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CURRENT REPOSITORY TOPOLOGY                           │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ FRONTEND (Vite + React 19 SPA)       │ BACKEND (FastAPI + Python 3.12/3.13)  │
│ - Relative/VITE_API_URL endpoints    │ - 23 REST Endpoint Routers           │
│ - Broadsheet/Curatorial UI           │ - SQLite development database        │
│ - Client-side state & AuthContext    │ - Hybrid retrieval & RRF engine      │
│ - Dual-target: local dev & serverless│ - StorageService (local disk + S3)   │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ LOCAL STORAGE / EMBEDDED STATE                                              │
│ - SQLite database: `backend/archive_phase1.db` (56 docs, 8 collections)     │
│ - Storage directories: `backend/storage/uploads/`, `derivatives/`, `audio/` │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## B. Oracle Cloud Target Architecture

```
                                  PUBLIC INTERNET
                                         │
                                         ▼ (Ports 80, 443)
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ORACLE CLOUD ALWAYS FREE VM (HOST)                       │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                            NGINX (PORT 80/443)                        │  │
│  │  - TLS Termination (Let's Encrypt / Certbot)                          │  │
│  │  - Rate Limiting (api_general: 20r/s, api_auth: 5r/s)                 │  │
│  │  - Static Asset Cache (Gzip, Brotli, HTTP/2, 7d asset cache)          │  │
│  └────────────────┬──────────────────────────────────┬───────────────────┘  │
│                   │                                  │                      │
│       location /  │                      location /api/v1/   location /storage/ │
│                   ▼                                  ▼                      ▼
│  ┌─────────────────────────────┐    ┌───────────────────────────┐ ┌──────────┐
│  │   Vite Static Production    │    │  Uvicorn FastAPI Workers  │ │  Static  │
│  │   Build (/usr/share/.../dist│    │  (127.0.0.1:8000 - 4 core)│ │ Derivative│
│  │   React 19 SPA Broadsheet   │    │  - Archival REST APIs     │ │ Media    │
│  └─────────────────────────────┘    │  - Zero-Hallucination RAG │ │ Vault    │
│                                     │  - Dublin Core / Ingestion│ └──────────┘
│                                     └─────────────┬─────────────┘           │
│                                                   │                         │
│                    ┌──────────────────────────────┴───────────────┐         │
│                    ▼                                              ▼         │
│  ┌───────────────────────────────────┐    ┌──────────────────────────────┐  │
│  │       PostgreSQL 16 + pgvector    │    │         Redis 7 Cache        │  │
│  │  (127.0.0.1:5432 - Internal only) │    │  (127.0.0.1:6379 - Internal) │  │
│  │  - Full Relational Schema (P1-P9) │    │  - Response Cache            │  │
│  │  - pgvector HNSW Index (BGE-M3)   │    │  - Celery / Task Queue       │  │
│  │  - Dublin Core & Ledger Records   │    │  - Rate Limiting State       │  │
│  └───────────────────────────────────┘    └──────────────────────────────┘  │
│                    │                                                        │
│                    ▼                                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      PERSISTENT STORAGE VOLUMES                       │  │
│  │  /var/www/ambedkar-archive/storage/                                   │  │
│  │  ├── uploads/ (Preserved master binaries with SHA-256 integrity)      │  │
│  │  ├── derivatives/ (High-resolution folio images & thumbnails)         │  │
│  │  └── audio/ (Preserved historical speeches and narrations)            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## C. Required Code Changes

| File | Nature of Change | Justification |
| :--- | :--- | :--- |
| `backend/app/core/config.py` | Ensure `BACKEND_CORS_ORIGINS` dynamically loads JSON strings or comma-separated origins from environment without crashing on boot. Add default support for private loopback and host reverse-proxy headers. | Ensures VM public IP and custom domains resolve without preflight CORS rejection. |
| `nginx/conf.d/archive.conf` | Update `proxy_pass http://backend_api;` to ensure proxy preserves headers: `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`. Update static build directory to match VM installation path (`/var/www/ambedkar-archive/frontend/dist`). | Seamless single-origin reverse proxying. |
| `frontend/vite.config.ts` | Ensure base path is set to `/` and rollup chunking splits vendor libraries cleanly for production builds. | Optimal caching on 1-core to 4-core Oracle instances. |
| `backend/app/db/session.py` | Ensure SQLite fallback remains available if PostgreSQL connection string fails pre-ping, while failing loudly only when `ENVIRONMENT=production` and `VECTOR_BACKEND=PGVECTOR`. | Preserves operational resilience. |

---

## D. Required Environment Variables

Create `/var/www/ambedkar-archive/backend/.env`:

```bash
# ==============================================================================
# Oracle Cloud Production Environment Configuration
# ==============================================================================
ENVIRONMENT=production
PROJECT_NAME="Dr. B. R. Ambedkar Digital Heritage Archive"
ARCHIVE_PHASE=PHASE_10_FINAL_INTEGRATION

# Database: PostgreSQL with pgvector extension on local loopback
DATABASE_URL=postgresql+psycopg2://archive_user:YOUR_STRONG_PASSWORD_HERE@127.0.0.1:5432/ambedkar_archive
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_PRE_PING=true
DATABASE_POOL_RECYCLE=3600

# Security & Tokens (Generate with: openssl rand -hex 32)
SECRET_KEY=GENERATE_RANDOM_64_CHAR_HEX_KEY_HERE
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# CORS — Replace with your Oracle VM Public IP and Domain
BACKEND_CORS_ORIGINS=["http://<ORACLE_VM_PUBLIC_IP>","https://<YOUR_DOMAIN>","http://localhost"]

# Vector & Semantic Search
VECTOR_BACKEND=PGVECTOR
EMBEDDING_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-m3

# RAG & LLM Provider Configuration
LLM_PROVIDER=huggingface
HF_BASE_URL=https://router.huggingface.co/v1
HF_MODEL=meta-llama/Llama-3.1-8B-Instruct
HF_TOKEN=your_huggingface_inference_token_here

# Redis Ephemeral Cache & Queue
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_ENABLED=false

# Physical Storage Paths
STORAGE_DIR=/var/www/ambedkar-archive/storage/uploads
AUDIO_STORAGE_DIR=/var/www/ambedkar-archive/storage/audio

# Security & Hardware Hardening
SECURITY_HEADERS_ENABLED=true
RATE_LIMIT_ENABLED=true
KIOSK_IDLE_TIMEOUT_SECONDS=120
KIOSK_WARNING_TIMEOUT_SECONDS=15
```

---

## E. Required System Packages (Ubuntu 22.04 / 24.04 LTS)

```bash
sudo apt-get update && sudo apt-get install -y \
  build-essential \
  curl \
  wget \
  git \
  nginx \
  certbot \
  python3-certbot-nginx \
  python3 \
  python3-pip \
  python3-venv \
  python3-dev \
  libpq-dev \
  postgresql \
  postgresql-contrib \
  redis-server \
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-hin \
  tesseract-ocr-mar \
  libgl1-mesa-glx \
  libglib2.0-0 \
  supervisor
```

### PostgreSQL pgvector Extension Installation:
```bash
# Add official PostgreSQL repository if not already present
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt-get update
sudo apt-get install -y postgresql-16-pgvector
```

---

## F. Required Python Packages

In `backend/requirements.txt`:

```text
fastapi>=0.110.0,<0.120.0
uvicorn[standard]>=0.28.0,<0.35.0
pydantic>=2.6.0,<3.0.0
pydantic-settings>=2.2.0,<3.0.0
sqlalchemy>=2.0.28,<2.1.0
alembic>=1.13.0,<2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
bcrypt>=4.0.1,<4.1.0
python-multipart>=0.0.9
email-validator>=2.1.0
psycopg2-binary>=2.9.9
pgvector>=0.2.5
redis>=5.0.0
aiosqlite>=0.20.0
httpx>=0.27.0
pillow>=10.0.0
pypdf>=4.0.0
numpy>=1.26.0
pytesseract>=0.3.10
opencv-python-headless>=4.9.0
boto3>=1.34.0
pytest>=8.1.0
```

---

## G. Required Node Packages

Managed via `frontend/package.json` (Node 20+ LTS / Node 22+ LTS):

```bash
# Frontend dependencies are already locked in package.json
# Installed during build via:
cd frontend && npm ci
```

---

## H. Database Migration Requirements

1. **Initialize PostgreSQL database & user**:
   ```sql
   sudo -u postgres psql -c "CREATE USER archive_user WITH PASSWORD 'archive_secure_password_2026';"
   sudo -u postgres psql -c "CREATE DATABASE ambedkar_archive OWNER archive_user;"
   sudo -u postgres psql -d ambedkar_archive -c "CREATE EXTENSION IF NOT EXISTS vector;"
   sudo -u postgres psql -d ambedkar_archive -c "GRANT ALL PRIVILEGES ON DATABASE ambedkar_archive TO archive_user;"
   ```

2. **Execute Alembic migrations**:
   ```bash
   cd /var/www/ambedkar-archive/backend
   source venv/bin/activate
   alembic upgrade head
   ```

3. **Migrate Historical Data from Master Seed**:
   Run the database seed script to populate Dublin Core metadata, 56 primary documents, 8 collections, 5 languages, and initial RBAC users:
   ```bash
   python -c "from app.db.session import SessionLocal; from app.db.seed import seed_database; db = SessionLocal(); seed_database(db); db.close()"
   ```

---

## I. Storage Requirements

Directory layout on the Oracle VM:

```
/var/www/ambedkar-archive/
├── frontend/
│   └── dist/                     # Static compiled HTML/JS/CSS assets
├── backend/
│   ├── app/                      # Application code
│   └── venv/                     # Python 3 virtual environment
└── storage/                      # Persistent storage mount
    ├── uploads/                  # Master archival binaries (read-only after hash)
    ├── derivatives/              # Web-optimized imagery and OCR thumbnails
    ├── media/                    # Audio-visual recordings & waveforms
    └── packages/                 # Offline museum backup packages
```

Permissions setup:
```bash
sudo mkdir -p /var/www/ambedkar-archive/storage/{uploads,derivatives,media,packages}
sudo chown -R www-data:www-data /var/www/ambedkar-archive/storage
sudo chmod -R 775 /var/www/ambedkar-archive/storage
```

---

## J. CORS Configuration

In single-origin Oracle deployment, Nginx proxies both frontend static files and `/api/v1` on port 80/443. This inherently prevents browser cross-origin requests.

However, to support direct programmatic API access and kiosk clients:
- In `backend/.env`:
  ```bash
  BACKEND_CORS_ORIGINS=["http://<ORACLE_VM_IP>","https://<YOUR_DOMAIN>","http://localhost","http://127.0.0.1"]
  ```

---

## K. Nginx Configuration

File: `/etc/nginx/sites-available/ambedkar-archive.conf`

```nginx
upstream backend_fastapi {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name _; # Or replace with your domain (e.g. archive.yourdomain.org)

    client_max_body_size 50M;

    # Security Headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), camera=(self), microphone=(self)" always;

    # 1. Frontend Single Page Application (React / Vite)
    location / {
        root /var/www/ambedkar-archive/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;

        # Cache static CSS, JS, Fonts, and Images
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2|woff|ttf)$ {
            expires 7d;
            add_header Cache-Control "public, no-transform";
        }
    }

    # 2. Backend REST API Endpoints
    location /api/ {
        proxy_pass http://backend_fastapi;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 3. System Probes
    location /health/ {
        proxy_pass http://backend_fastapi;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        access_log off;
    }

    # 4. Derivative Media Storage
    location /storage/derivatives/ {
        alias /var/www/ambedkar-archive/storage/derivatives/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }
}
```

---

## L. Process Management Strategy

We configure **systemd** for automated lifecycle management, auto-restart upon reboot, and crash recovery.

### 1. Backend Service: `/etc/systemd/system/ambedkar-backend.service`

```ini
[Unit]
Description=Ambedkar Digital Heritage Archive - FastAPI Backend
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/ambedkar-archive/backend
EnvironmentFile=/var/www/ambedkar-archive/backend/.env
ExecStart=/var/www/ambedkar-archive/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ambedkar-backend
sudo systemctl start ambedkar-backend
```

---

## M. Firewall & Network Ports Required

### OCI Console (Security List / Network Security Group):
In the Oracle Cloud Console (Networking > Virtual Cloud Networks > Security Lists):
- **Ingress Rule 1**: Source `0.0.0.0/0`, Protocol `TCP`, Destination Port `80` (HTTP)
- **Ingress Rule 2**: Source `0.0.0.0/0`, Protocol `TCP`, Destination Port `443` (HTTPS)
- **Ingress Rule 3**: Source `<YOUR_ADMIN_IP>/32`, Protocol `TCP`, Destination Port `22` (SSH)

### OS-Level Firewall (`iptables` / `ufw` on Ubuntu):
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

*Note: PostgreSQL (5432) and Redis (6379) are bound strictly to `127.0.0.1` and are never opened in the firewall.*

---

## N. Deployment Commands (Runbook)

```bash
# 1. Clone repository to Oracle VM
sudo mkdir -p /var/www/ambedkar-archive
sudo chown -R $USER:$USER /var/www/ambedkar-archive
git clone https://github.com/tushar-bit-sketch/drambedkar-ai.git /var/www/ambedkar-archive

# 2. Build Frontend
cd /var/www/ambedkar-archive/frontend
npm ci
npm run build

# 3. Setup Python Virtual Environment
cd /var/www/ambedkar-archive/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure Environment & Run Migrations
cp .env.example .env
# Edit .env with production credentials
alembic upgrade head
python -c "from app.db.session import SessionLocal; from app.db.seed import seed_database; db = SessionLocal(); seed_database(db); db.close()"

# 5. Configure Nginx & Systemd
sudo cp /var/www/ambedkar-archive/nginx/conf.d/archive.conf /etc/nginx/sites-available/ambedkar-archive.conf
sudo ln -sf /etc/nginx/sites-available/ambedkar-archive.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 6. Start Application Daemon
sudo systemctl daemon-reload
sudo systemctl enable ambedkar-backend
sudo systemctl restart ambedkar-backend
```

---

## O. Verification Tests

Execute these verification commands after deployment:

```bash
# 1. Verify System Probes
curl -s http://127.0.0.1/health/live | grep "healthy"

# 2. Verify Database Connection & Migration Status
curl -s http://127.0.0.1/api/v1/health | jq .

# 3. Verify Search Retrieval Engine (Faceted Search)
curl -s "http://127.0.0.1/api/v1/search?q=Constitution" | jq '.total_results'

# 4. Verify Document Dublin Core Catalog
curl -s "http://127.0.0.1/api/v1/documents?page=1&page_size=5" | jq '.total'

# 5. Verify Frontend HTTP 200 & Single Page Routing
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/search
curl -I http://127.0.0.1/research
curl -I http://127.0.0.1/admin
```

---

## P. Rollback Procedure

In the event of an operational anomaly during upgrade or migration:

1. **Stop Application Daemon**:
   ```bash
   sudo systemctl stop ambedkar-backend
   ```
2. **Revert Git Working Tree**:
   ```bash
   cd /var/www/ambedkar-archive
   git log -n 5 --oneline
   git checkout <PREVIOUS_STABLE_COMMIT_HASH>
   ```
3. **Rollback Database Migration**:
   ```bash
   cd /var/www/ambedkar-archive/backend
   source venv/bin/activate
   alembic downgrade -1
   ```
4. **Rebuild Frontend Static Assets**:
   ```bash
   cd /var/www/ambedkar-archive/frontend
   npm ci && npm run build
   ```
5. **Restart Services & Verify**:
   ```bash
   sudo systemctl restart ambedkar-backend
   sudo systemctl reload nginx
   curl -s http://127.0.0.1/health/live
   ```

---

## Completion Checkpoint

The comprehensive audit and deployment plan is complete. All 20 audit criteria and architectural sections A through P are formally established in `docs/ORACLE_DEPLOYMENT_PLAN.md`.

**STATUS: AUDIT COMPLETE — STOPPING AS DIRECTED. NO CODE MODIFICATIONS PERFORMED. NO DEPLOYMENT INITIATED.**
