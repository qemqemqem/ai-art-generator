# Agent guide (AI Art Generator / artgen)

This file is for **coding agents and contributors** working in this repository. It summarizes how the project is organized, how to run checks, and what to watch for when changing code.

## What this repo is

- **CLI-first batch AI art generation** (`artgen`) with optional **FastAPI + web UI** for approval workflows.
- **Python** package (`artgen`, `backend*`, `frontend*` per `pyproject.toml`). Requires **Python ≥ 3.11**.
- Image/text providers include **Google GenAI (Gemini)**, **OpenAI**, **Anthropic**, and routing via **LiteLLM** where applicable.

## Setup

From the repo root:

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

Or use `python -m venv` + `pip install -e ".[dev]"` as in `README.md`.

## Layout (high level)

| Area | Role |
|------|------|
| `backend/` | CLI (`artgen.py`), pipeline/core logic, FastAPI app (`app/`), tests (`tests/`), `pytest.ini` |
| `frontend/` | Web UI assets used with the interactive workflow |
| `pipelines/` | Example and product pipeline YAML/configs |
| `examples/` | Sample inputs and smaller example projects |

The installable console script is **`artgen`** → `backend.artgen:main`.

## Configuration and secrets

- API keys live in env files (e.g. **`.env.local`**). **Do not commit** secrets or real keys.
- CLI env file resolution is documented in `README.md` (`--env`, `ARTGEN_ENV_FILE`, `.env.local`, etc.).

## Tests

Run from **`backend/`** so `pytest.ini` is picked up:

```bash
cd backend && pytest
```

- **`@pytest.mark.live`**: hits **real APIs** and can **incur cost**. Only run when explicitly intended, e.g. `pytest -m live` (see `backend/pytest.ini` and live test modules such as `test_*_live.py`).
- Default config uses **verbose, short tracebacks**; async mode is **auto** for pytest-asyncio.

## Making changes

- Prefer **small, task-focused diffs**; match existing style and patterns in the touched files.
- **Imports at the top of files**; if circular imports appear, **split modules** (e.g. utils/content modules) rather than lazy-importing as a first resort.
- Avoid drive-by refactors and unrelated formatting churn unless the task requires it.

## Docs and planning

- If you add a **planning doc** for substantial work, put it under **`notes/ai/`** or **`docs-ai/`** (or a scoped `*/notes/` pattern consistent with repo conventions).

## User-facing documentation

- **`README.md`** remains the primary user guide for install, CLI options, and formats.
