.PHONY: start stop restart backend frontend status logs app build dev run test test-headed test-setup lint fmt dmg release db-migrate db-upgrade db-downgrade db-current db-history db-revision whatsapp whatsapp-stop setup ship

BACKEND_DIR = app/backend
FRONTEND_DIR = app/frontend

# --- Setup ---

setup: venv
	@cd $(FRONTEND_DIR) && npm install
	@echo "Setup complete. Run 'make dev' to start."

PYTHON := $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)

venv:
	@if [ ! -d $(BACKEND_DIR)/venv ]; then \
		if $(PYTHON) -c 'import sys; exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then \
			echo "Creating Python virtual environment using $$($(PYTHON) --version)..."; \
			$(PYTHON) -m venv $(BACKEND_DIR)/venv; \
			cd $(BACKEND_DIR) && source venv/bin/activate && pip install -q -r requirements.txt; \
			echo "Virtual environment created and dependencies installed."; \
		else \
			echo "Error: Python 3.11+ required. Found: $$($(PYTHON) --version 2>&1)"; \
			echo "Install with: brew install python@3.13"; \
			exit 1; \
		fi \
	fi

# --- Native app ---

start: venv
	@echo "Stopping any existing servers..."
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@echo "Updating backend dependencies..."
	@cd $(BACKEND_DIR) && source venv/bin/activate && pip install -q -r requirements.txt
	@echo "Updating frontend dependencies..."
	@cd $(FRONTEND_DIR) && npm install --silent
	@echo "Building frontend..."
	@cd $(FRONTEND_DIR) && npm run build
	@if python3 -c "import json,os;p=os.path.join(os.environ.get('DASHBOARD_DATA_DIR',os.path.expanduser('~/.personal-dashboard')),'config.json');c=json.load(open(p));exit(0 if c.get('connectors',{}).get('whatsapp',{}).get('enabled') else 1)" 2>/dev/null; then \
		lsof -ti:3001 | xargs kill -9 2>/dev/null || true; \
		(cd app/whatsapp && npm install --silent); \
		cd app/whatsapp && node index.js > /tmp/dashboard-whatsapp.log 2>&1 & \
		sleep 2; \
		curl -sf http://localhost:3001/status > /dev/null && echo "WhatsApp sidecar running on :3001" || echo "WhatsApp sidecar failed — check /tmp/dashboard-whatsapp.log"; \
	fi
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

dev: venv backend frontend whatsapp
	@echo "Dev mode running at http://localhost:5173"

backend:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@cd $(BACKEND_DIR) && source venv/bin/activate && uvicorn main:app --port 8000 --reload > /tmp/dashboard-backend.log 2>&1 &
	@sleep 2
	@curl -sf http://localhost:8000/api/health > /dev/null && echo "Backend running on :8000" || echo "Backend failed to start — check /tmp/dashboard-backend.log"

frontend:
	@lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@if [ ! -d $(FRONTEND_DIR)/node_modules ]; then echo "Installing frontend dependencies..."; cd $(FRONTEND_DIR) && npm install; fi
	@cd $(FRONTEND_DIR) && npx vite --port 5173 > /tmp/dashboard-frontend.log 2>&1 &
	@sleep 2
	@curl -sf http://localhost:5173 > /dev/null && echo "Frontend running on :5173" || echo "Frontend failed to start — check /tmp/dashboard-frontend.log"

# --- Common ---

stop:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "Backend stopped" || echo "Backend not running"
	@lsof -ti:5173 | xargs kill -9 2>/dev/null && echo "Frontend stopped" || echo "Frontend not running"
	@lsof -ti:3001 | xargs kill -9 2>/dev/null && echo "WhatsApp sidecar stopped" || echo "WhatsApp sidecar not running"

restart: stop dev

status:
	@echo "Backend:   $$(lsof -ti:8000 > /dev/null 2>&1 && echo 'running' || echo 'stopped')"
	@echo "Frontend:  $$(lsof -ti:5173 > /dev/null 2>&1 && echo 'running' || echo 'stopped')"
	@echo "WhatsApp:  $$(lsof -ti:3001 > /dev/null 2>&1 && echo 'running' || echo 'stopped')"

logs:
	@echo "=== Backend ===" && tail -20 /tmp/dashboard-backend.log 2>/dev/null || echo "No backend logs"
	@echo ""
	@echo "=== Frontend ===" && tail -20 /tmp/dashboard-frontend.log 2>/dev/null || echo "No frontend logs"
	@echo ""
	@echo "=== WhatsApp ===" && tail -20 /tmp/dashboard-whatsapp.log 2>/dev/null || echo "No WhatsApp logs"

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

# --- DMG packaging ---

dmg:
	@./scripts/build-dmg.sh $(VERSION)

# --- Release (DMG + GitHub) ---

release:
	@./scripts/release.sh $(VERSION) $(NOTES)

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

# --- WhatsApp sidecar ---

whatsapp:
	@if python3 -c "import json,os;p=os.path.join(os.environ.get('DASHBOARD_DATA_DIR',os.path.expanduser('~/.personal-dashboard')),'config.json');c=json.load(open(p));exit(0 if c.get('connectors',{}).get('whatsapp',{}).get('enabled') else 1)" 2>/dev/null; then \
		lsof -ti:3001 | xargs kill -9 2>/dev/null || true; \
		(cd app/whatsapp && npm install --silent); \
		cd app/whatsapp && node index.js > /tmp/dashboard-whatsapp.log 2>&1 & \
		sleep 2; \
		curl -sf http://localhost:3001/status > /dev/null && echo "WhatsApp sidecar running on :3001" || echo "WhatsApp sidecar failed — check /tmp/dashboard-whatsapp.log"; \
	fi

whatsapp-stop:
	@lsof -ti:3001 | xargs kill -9 2>/dev/null && echo "WhatsApp sidecar stopped" || echo "WhatsApp sidecar not running"

# --- Ship (commit, push, PR, optional merge) ---
# Usage:
#   make ship                    # commit, push, open PR
#   make ship m="feat: add X"   # custom commit message
#   make ship merge=1            # also merge the PR after creating it

ship:
	@if [ -z "$$(git status --porcelain)" ]; then echo "Nothing to commit."; exit 1; fi
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$BRANCH" = "main" ] || [ "$$BRANCH" = "master" ]; then \
		echo "Error: You're on $$BRANCH. Create a feature branch first."; \
		exit 1; \
	fi; \
	echo "=== Staging & Committing ==="; \
	git add -A; \
	if [ -n "$(m)" ]; then \
		MSG="$(m)"; \
	else \
		echo "Generating commit message with Claude..."; \
		MSG=$$(git diff --cached | claude -p "Write a short, conventional commit message (one line, no quotes) for this diff. Just output the message, nothing else." 2>/dev/null); \
		MSG="$${MSG:-Update $$BRANCH}"; \
		echo "Commit: $$MSG"; \
	fi; \
	git commit -m "$$MSG"; \
	echo "=== Pushing $$BRANCH ==="; \
	git push -u origin "$$BRANCH"; \
	echo "=== Creating PR ==="; \
	DIFF=$$(git log main..HEAD --pretty=format:"%s%n%n%b" 2>/dev/null); \
	FULL_DIFF=$$(git diff main..HEAD 2>/dev/null); \
	echo "Generating PR title and body with Claude..."; \
	TITLE=$$(echo "$$DIFF" | claude -p "Write a short PR title (under 70 chars, no quotes) summarizing these commits. Just output the title, nothing else." 2>/dev/null); \
	TITLE="$${TITLE:-$$MSG}"; \
	BODY=$$(echo "$$FULL_DIFF" | claude -p "Write a PR description for this diff. Format: ## Summary with 2-4 bullet points, then ## Changes listing key file changes. Just output the markdown, nothing else." 2>/dev/null); \
	BODY="$${BODY:-$$(git log main..HEAD --pretty=format:'- %s')}"; \
	echo "PR: $$TITLE"; \
	PR_URL=$$(gh pr create --title "$$TITLE" --body "$$BODY" 2>&1); \
	if echo "$$PR_URL" | grep -q "already exists"; then \
		echo "PR already exists for this branch."; \
		PR_URL=$$(gh pr view --json url -q .url); \
	fi; \
	echo "$$PR_URL"; \
	if [ "$(merge)" = "1" ]; then \
		echo "=== Merging PR ==="; \
		gh pr merge --squash --delete-branch; \
	fi
