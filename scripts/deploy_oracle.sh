#!/usr/bin/env bash
# ==============================================================================
# SIH26096: Dr. B. R. Ambedkar Digital Heritage Archive
# Oracle Cloud Always Free VM — Production Deployment Automation Script
# ==============================================================================
# Target: Ubuntu 22.04 / 24.04 LTS (x86_64 or ARM64 Ampere A1)
# Architecture: Nginx (80/443) -> React SPA -> FastAPI -> PostgreSQL 16 + pgvector
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}  Ambedkar Digital Heritage Archive — Oracle Cloud Production Deployment     ${NC}"
echo -e "${BLUE}==============================================================================${NC}"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# ------------------------------------------------------------------------------
# 1. System Package & Docker Validation
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[1/7] Checking system dependencies and Docker runtime...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker not found. Installing Docker CE...${NC}"
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER" || true
    echo -e "${GREEN}Docker CE installed successfully.${NC}"
fi

# Ensure docker compose is available (v2 plugin or standalone)
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}Error: Neither 'docker compose' nor 'docker-compose' found.${NC}"
    exit 1
fi
echo -e "${GREEN}Docker runtime verified: $($DOCKER_COMPOSE version)${NC}"

# Check Node.js for frontend build
if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}Node.js not found. Installing Node.js 22 LTS...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo -e "${GREEN}Node runtime verified: $(node -v) / npm $(npm -v)${NC}"

# ------------------------------------------------------------------------------
# 2. Build Frontend Static Bundle
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[2/7] Building Frontend React/Vite SPA...${NC}"
cd "$PROJECT_DIR/frontend"
npm ci
npm run build
cd "$PROJECT_DIR"
echo -e "${GREEN}Frontend production bundle generated in frontend/dist.${NC}"

# ------------------------------------------------------------------------------
# 3. Storage Directory & Permissions Initialization
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[3/7] Setting up persistent storage hierarchy...${NC}"
mkdir -p "$PROJECT_DIR/storage/uploads"
mkdir -p "$PROJECT_DIR/storage/derivatives"
mkdir -p "$PROJECT_DIR/storage/media"
mkdir -p "$PROJECT_DIR/storage/audio"
mkdir -p "$PROJECT_DIR/storage/packages"
mkdir -p "$PROJECT_DIR/nginx/ssl"
mkdir -p "$PROJECT_DIR/nginx/logs"
chmod -R 775 "$PROJECT_DIR/storage"
echo -e "${GREEN}Storage hierarchy initialized.${NC}"

# ------------------------------------------------------------------------------
# 4. Production Secrets & Environment File
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[4/7] Validating production environment configuration...${NC}"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${YELLOW}No .env found. Generating secure production .env...${NC}"
    POSTGRES_PASS=$(openssl rand -hex 16)
    SECRET_KEY=$(openssl rand -hex 32)
    REDIS_PASS=$(openssl rand -hex 16)
    
    cat <<EOF > "$PROJECT_DIR/.env"
# ==============================================================================
# Auto-generated Production Secrets — Ambedkar Digital Heritage Archive
# ==============================================================================
POSTGRES_USER=archive_user
POSTGRES_PASSWORD=${POSTGRES_PASS}
POSTGRES_DB=ambedkar_archive
SECRET_KEY=${SECRET_KEY}
REDIS_PASSWORD=${REDIS_PASS}
BACKEND_CORS_ORIGINS=["http://localhost","http://127.0.0.1"]
ENVIRONMENT=production
ARCHIVE_PHASE=PHASE_10_FINAL_INTEGRATION
VECTOR_BACKEND=PGVECTOR
SECURITY_HEADERS_ENABLED=true
RATE_LIMIT_ENABLED=true
EOF
    chmod 600 "$PROJECT_DIR/.env"
    echo -e "${GREEN}Generated secure .env file with fresh cryptographic keys.${NC}"
else
    echo -e "${GREEN}Existing .env file detected.${NC}"
fi

# ------------------------------------------------------------------------------
# 5. Build & Launch Docker Production Stack
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[5/7] Building and starting production Docker containers...${NC}"
$DOCKER_COMPOSE -f docker-compose.production.yml build
$DOCKER_COMPOSE -f docker-compose.production.yml up -d

echo -e "Waiting for PostgreSQL and Redis health probes..."
for i in {1..30}; do
    if $DOCKER_COMPOSE -f docker-compose.production.yml ps | grep -q "healthy"; then
        echo -e "${GREEN}Core database infrastructure is healthy.${NC}"
        break
    fi
    sleep 2
done

# ------------------------------------------------------------------------------
# 6. Database Migrations & Initial Seed Verification
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[6/7] Executing database migrations and master catalog verification...${NC}"
# Enable pgvector extension inside postgres
$DOCKER_COMPOSE -f docker-compose.production.yml exec -T postgres psql -U archive_user -d ambedkar_archive -c "CREATE EXTENSION IF NOT EXISTS vector;" || true

# Run Alembic migrations
$DOCKER_COMPOSE -f docker-compose.production.yml exec -T backend alembic upgrade head

# Run seed verification
$DOCKER_COMPOSE -f docker-compose.production.yml exec -T backend python -c \
  "from app.db.session import SessionLocal; from app.db.seed import seed_database; db = SessionLocal(); seed_database(db); db.close()"
echo -e "${GREEN}Database schema and master archival folios verified.${NC}"

# ------------------------------------------------------------------------------
# 7. End-to-End Verification Probes
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[7/7] Running system verification probes...${NC}"
sleep 5

# Probe 1: Top-level Health Live
HEALTH_STATUS=$(curl -sf http://127.0.0.1/health/live || echo "FAILED")
echo -e "Probe 1 (Health Live): $HEALTH_STATUS"

# Probe 2: API v1 Health
API_HEALTH=$(curl -sf http://127.0.0.1/api/v1/health || echo "FAILED")
echo -e "Probe 2 (API v1 Health): $API_HEALTH"

# Probe 3: Search Query Probe
SEARCH_RESULTS=$(curl -sf "http://127.0.0.1/api/v1/search?q=Constitution" | grep -o '"total_results":[0-9]*' || echo "FAILED")
echo -e "Probe 3 (Search Retrieval): $SEARCH_RESULTS"

# Probe 4: Catalog Documents Probe
DOC_COUNT=$(curl -sf "http://127.0.0.1/api/v1/documents?page=1&page_size=1" | grep -o '"total":[0-9]*' || echo "FAILED")
echo -e "Probe 4 (Catalog Ledger): $DOC_COUNT"

echo -e "\n${GREEN}==============================================================================${NC}"
echo -e "${GREEN}  DEPLOYMENT COMPLETE!                                                       ${NC}"
echo -e "${GREEN}  Your Ambedkar Digital Heritage Archive is running at:                      ${NC}"
echo -e "${GREEN}  --> http://$(curl -s https://api.ipify.org || echo '<YOUR_ORACLE_VM_IP>')/ ${NC}"
echo -e "${GREEN}==============================================================================${NC}"
