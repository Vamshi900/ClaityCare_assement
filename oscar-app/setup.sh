#!/bin/bash
set -e

echo "=== Oscar Guidelines — Setup ==="
echo ""

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "python3 required but not found"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "node required but not found"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm required but not found"; exit 1; }
sudo -u postgres psql -c "SELECT 1;" >/dev/null 2>&1 || { echo "PostgreSQL required but not running"; exit 1; }
echo "[1/6] Prerequisites OK (python3, node, npm, postgres)"

# Environment
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[!] Created .env from .env.example — add your ANTHROPIC_API_KEY before running extraction"
else
    echo "[2/6] .env exists"
fi

# Database
echo "[3/6] Setting up database..."
sudo -u postgres psql -c "CREATE DATABASE oscar_guidelines;" 2>/dev/null || true
sudo -u postgres psql -c "CREATE USER oscar WITH PASSWORD 'oscar_dev_pw';" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE oscar_guidelines TO oscar;" >/dev/null
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON SCHEMA public TO oscar;" >/dev/null
sudo -u postgres psql -d oscar_guidelines < backend/db/init.sql >/dev/null 2>&1
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO oscar;" >/dev/null
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO oscar;" >/dev/null
sudo -u postgres psql -d oscar_guidelines < backend/db/migrate_001_status.sql >/dev/null 2>&1
echo "       Database ready"

# Backend dependencies
echo "[4/6] Installing backend dependencies..."
cd backend
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
python -m app.bootstrap
cd ..
echo "       Backend ready"

# Frontend dependencies
echo "[5/6] Installing frontend dependencies..."
cd frontend
npm install --silent 2>/dev/null
cd ..
echo "       Frontend ready"

# Storage directories
mkdir -p storage/pdfs storage/text

# Start services
echo "[6/6] Starting services..."
cd backend
source venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
    --reload-dir app --reload-dir ../extraction \
    > /tmp/oscar-backend.log 2>&1 &
cd ..

cd frontend
nohup npx vite --host 0.0.0.0 > /tmp/oscar-frontend.log 2>&1 &
cd ..

sleep 3

echo ""
echo "=== Ready ==="
echo ""
echo "  Frontend:  http://localhost:5173"
echo "  Backend:   http://localhost:8000"
echo "  API Stats: http://localhost:8000/api/stats"
echo ""
echo "  Next steps:"
echo "    1. Add your ANTHROPIC_API_KEY to .env"
echo "    2. Open the UI and click Discover → Download → Structure"
echo "    3. Or use the API: curl -X POST http://localhost:8000/api/jobs -H 'Content-Type: application/json' -d '{\"type\":\"discovery\"}'"
echo ""
echo "  Logs: tail -f /tmp/oscar-backend.log"
echo "  Stop: make stop"
