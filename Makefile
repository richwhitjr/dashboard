.PHONY: start stop restart backend frontend status logs app build dev run test test-headed test-setup lint fmt db-migrate db-upgrade db-downgrade db-current db-history db-revision

BACKEND_DIR = app/backend
FRONTEND_DIR = app/frontend

# --- Native app ---

start:
	@echo "Stopping any existing servers..."
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@echo "Updating backend dependencies..."
	@cd $(BACKEND_DIR) && source venv/bin/activate && pip install -q -r requirements.txt
	@echo "Updating frontend dependencies..."
	@cd $(FRONTEND_DIR) && npm install --silent
	@echo "Building frontend..."
	@cd $(FRONTEND_DIR) && npm run build
	@echo "Opening Dashboard..."
	@open Dashboard.app

run: dev

dashboard: start

app: build
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@open Dashboard.app

build:
	@cd $(FRONTEND_DIR) && npm run build
	@echo "Frontend built"

# --- Dev mode (hot reload) ---

dev: backend frontend
	@echo "Dev mode running at http://localhost:5173"

backend:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@cd $(BACKEND_DIR) && source venv/bin/activate && uvicorn main:app --port 8000 --reload > /tmp/dashboard-backend.log 2>&1 &
	@sleep 2
	@curl -sf http://localhost:8000/api/health > /dev/null && echo "Backend running on :8000" || echo "Backend failed to start — check /tmp/dashboard-backend.log"

frontend:
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@cd $(FRONTEND_DIR) && npx vite --port 5173 > /tmp/dashboard-frontend.log 2>&1 &
	@sleep 2
	@curl -sf http://localhost:5173 > /dev/null && echo "Frontend running on :5173" || echo "Frontend failed to start — check /tmp/dashboard-frontend.log"

# --- Common ---

stop:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "Backend stopped" || echo "Backend not running"
	@lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "Frontend stopped" || echo "Frontend not running"

restart: stop dev

status:
	@echo "Backend:  $$(lsof -ti:8000 > /dev/null 2>&1 && echo 'running' || echo 'stopped')"
	@echo "Frontend: $$(lsof -ti:5173 > /dev/null 2>&1 && echo 'running' || echo 'stopped')"

logs:
	@echo "=== Backend ===" && tail -20 /tmp/dashboard-backend.log 2>/dev/null || echo "No backend logs"
	@echo ""
	@echo "=== Frontend ===" && tail -20 /tmp/dashboard-frontend.log 2>/dev/null || echo "No frontend logs"

# --- Lint & Format ---

lint:
	@echo "=== Python (ruff) ==="
	@cd $(BACKEND_DIR) && source venv/bin/activate && ruff check . && ruff format --check .
	@echo ""
	@echo "=== TypeScript (tsc + eslint) ==="
	@cd $(FRONTEND_DIR) && npx tsc --noEmit && npx eslint .

fmt:
	@echo "=== Python (ruff) ==="
	@cd $(BACKEND_DIR) && source venv/bin/activate && ruff check --fix . && ruff format .
	@echo ""
	@echo "=== TypeScript (eslint) ==="
	@cd $(FRONTEND_DIR) && npx eslint --fix .

# --- Tests (Playwright) ---

test:
	@curl -sf http://localhost:5173 > /dev/null 2>&1 || (echo "Dev servers not running. Run 'make dev' first." && exit 1)
	@cd app/test && npx playwright test

test-headed:
	@curl -sf http://localhost:5173 > /dev/null 2>&1 || (echo "Dev servers not running. Run 'make dev' first." && exit 1)
	@cd app/test && npx playwright test --headed

test-setup:
	@cd app/test && npm install && npx playwright install chromium

# --- Database Migrations (Alembic) ---

db-migrate: db-upgrade
	@echo "Migrations applied successfully"

db-upgrade:
	@echo "Running database migrations..."
	@cd $(BACKEND_DIR) && source venv/bin/activate && alembic upgrade head

db-downgrade:
	@echo "Rolling back last migration..."
	@cd $(BACKEND_DIR) && source venv/bin/activate && alembic downgrade -1

db-current:
	@echo "Current database version:"
	@cd $(BACKEND_DIR) && source venv/bin/activate && alembic current

db-history:
	@echo "Migration history:"
	@cd $(BACKEND_DIR) && source venv/bin/activate && alembic history

db-revision:
	@echo "Creating new migration..."
	@read -p "Enter migration message: " msg; \
	cd $(BACKEND_DIR) && source venv/bin/activate && alembic revision -m "$$msg"
