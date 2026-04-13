# AGENTS.md

## Cursor Cloud specific instructions

### Project Overview

AI Art Generator (`artgen`) — a CLI-first batch AI art generation tool with an optional React-based interactive approval web UI. Two components: Python backend (FastAPI) and React/Vite frontend.

### Services

| Service | Command | Port | Notes |
|---------|---------|------|-------|
| Backend (FastAPI) | `cd backend && python -m app.main --port 8000` | 8000 | Requires venv activated. CWD becomes the project root. |
| Frontend (Vite) | `cd frontend && npm run dev -- --host 0.0.0.0` | 5173 | Optional — only needed for interactive approval UI. |

### Running Tests

- **Backend**: `cd backend && python -m pytest -v --tb=short` (from the workspace root with venv activated). Default runs fast unit tests only; use `-m live` for tests hitting real AI APIs.
- **Frontend lint**: `cd frontend && npm run lint`
- **Frontend build** (includes TypeScript check): `cd frontend && npm run build`

### Linting

- Backend has no dedicated linter config; rely on pytest and type checking.
- Frontend uses ESLint: `cd frontend && npm run lint`

### Non-obvious Caveats

- The backend server treats its CWD as the project root. When run from `backend/`, it auto-creates/loads an `artgen.json` there. If you need a clean project, use a temp directory.
- The CLI entrypoint is `backend/artgen.py`. Run as `python artgen.py <command>` from the `backend/` directory, or use `artgen <command>` after `pip install -e ".[dev]"`.
- Frontend `npm run build` has pre-existing TypeScript errors in the repo (unused vars, type-cast issues in `InteractiveQueue.tsx` and `App.tsx`). These are pre-existing and not introduced by environment setup.
- Backend pytest has 8 pre-existing test failures (5 from missing `StepType.IMAGE_SEARCH`, 1 from missing fixture data, 2 from API behavior). 200 tests pass.
- The Python virtual environment lives at `/workspace/.venv`. Always activate with `source /workspace/.venv/bin/activate`.
- API keys are loaded from `.env.local` files (see README for search order). Core image generation requires `GOOGLE_API_KEY`.
