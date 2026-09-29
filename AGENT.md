# WebAudit Project Guide

WebAudit is an autonomous web testing agent implemented in Python. It retains the original QA Agent's Observe–Think–Act loop, the single-page Plan–Execute flow, SQLite state, and MCP tool names. The TypeScript to Python migration path mapping and parity rules are in `MIGRATION_PLAN.md`.

## Stack

- Python managed with uv (`pyproject.toml`, `uv.lock`)
- Playwright async API and Chromium
- LangChain Core with Google Gemini or OpenAI-compatible models
- SQLite via `sqlite3`
- MCP Python SDK over stdio
- questionary for the interactive CLI
- pytest for migrated tests

Generated E2E tests are Python Playwright `*_spec.py` files executed with pytest in the uv environment. The generator prompt, output extension, and runner were updated to remove the former JavaScript runtime dependency.

## Paths and Public Names

The directory and file basenames match the original project. TypeScript source and test file extensions become `.py`; hyphenated and dotted basenames remain unchanged. Public classes and functions keep their original camelCase names. Examples:

```text
src/agents/exploratory.py             ExploratoryAgent
src/agents/single-page.py             SinglePageTestingAgent
src/auth/auth-manager.py              AuthenticationManager
src/repositories/session.repository.py SessionRepository
src/tools/broken-images.py            findBrokenImages
src/tools/layout-audit.py             runLayoutAudit
src/tools/visual-regression.py        runVisualRegression
src/services/test-generator.py        TestGenerator
src/services/test-executor.py         TestExecutor
src/mcp/server.py                     TestingAgentMCPServer
src/index.py                          main
```

Use `importlib.import_module()` for files with hyphens. Load `session.repository.py` with `importlib.util.spec_from_file_location()` because its basename contains a dot.

## Main Flow

1. `ExploratoryAgent.start()` opens Chromium, crawls the base URL, optionally authenticates, and resumes or initializes state.
2. `ExploratoryAgent.step()` captures visible elements, constructs the original LLM prompt, parses an action, executes it, scans for browser errors, and persists session state.
3. `SinglePageTestingAgent.start()` discovers elements, generates or falls back to a test plan, executes cases, then runs layout and optional visual regression checks.
4. MCP tools start background sessions and return a `sessionId`; status and session list tools read in-memory and SQLite state.

The migration preserves known source behavior, including the existing action error handling and MCP report resource behavior. The generated test format and runner are intentionally Python now.

## Setup and Commands

```bash
uv sync
uv run python -m playwright install chromium
cp .env.example .env
uv run python -m src.index
uv run python -m src.mcp.index
uv run pytest
uv run ruff check src tests
uv run python -m src.cli.run-tests
```

Set `GOOGLE_AI_STUDIO_API_KEY` or `OPEN_AI_API_KEY`; `OPEN_AI_API_URL` supports OpenAI-compatible local services. Environment variables retain their original names and take precedence over `.env`.

`scripts/deploy-mcp.sh` creates `/tmp/qa-agent-mcp-wrapper.sh` to launch the Python MCP server. `docs/mcp-server.md` has client configuration.

## Files to Preserve

Keep `docs/`, `scripts/`, `assets/`, `.gemini/`, `test-results/`, and `tests/test-resources/` under their original names. `docs/rfc-*.md` and `docs/issue-single-page-testing-agent.md` record the historical TypeScript design and are marked as such.
