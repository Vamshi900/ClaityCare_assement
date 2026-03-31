.PHONY: setup start stop restart logs backend frontend db-init db-migrate db-reset extract status

# One-command setup + start
setup:
	./setup.sh

# Start both services
start: backend frontend
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:5173"

# Stop all services
stop:
	@pkill -f "uvicorn app.main" 2>/dev/null || true
	@pkill -f "vite" 2>/dev/null || true
	@echo "Stopped"

# Restart
restart: stop start

# Logs
logs:
	@tail -f /tmp/oscar-backend.log

# Start backend only
backend:
	@cd backend && source venv/bin/activate && \
		nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--reload-dir app --reload-dir ../extraction \
		> /tmp/oscar-backend.log 2>&1 &
	@echo "Backend started on :8000"

# Start frontend only
frontend:
	@cd frontend && nohup npx vite --host 0.0.0.0 > /tmp/oscar-frontend.log 2>&1 &
	@echo "Frontend started on :5173"

# Database
db-init:
	sudo -u postgres psql -c "CREATE DATABASE oscar_guidelines;" 2>/dev/null || true
	sudo -u postgres psql -c "CREATE USER oscar WITH PASSWORD 'oscar_dev_pw';" 2>/dev/null || true
	sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE oscar_guidelines TO oscar;"
	sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON SCHEMA public TO oscar;"
	sudo -u postgres psql -d oscar_guidelines < backend/db/init.sql
	sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO oscar;"
	sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO oscar;"

db-migrate:
	sudo -u postgres psql -d oscar_guidelines < backend/db/migrate_001_status.sql

db-reset:
	sudo -u postgres psql -c "DROP DATABASE IF EXISTS oscar_guidelines;"
	$(MAKE) db-init
	$(MAKE) db-migrate

# Run extraction (10 policies)
extract:
	curl -s -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d '{"type":"structure"}'

# Check status
status:
	@curl -s http://localhost:8000/api/stats 2>/dev/null | python3 -m json.tool || echo "Backend not running"
