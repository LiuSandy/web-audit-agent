# Repository Guidelines

## Project Structure & Module Organization

`src/index.py` starts the interactive WebAudit CLI; `src/mcp/index.py` starts the MCP server. Agent workflows live in `src/agents/`, browser checks in `src/tools/`, authentication in `src/auth/`, and LLM, persistence, and reporting code in `src/services/`, `src/repositories/`, `src/database/`, and `src/utils/`. Handwritten tests are in `tests/`; browser fixtures are in `tests/test-resources/`. `docs/` holds design notes, `assets/` holds diagrams, and `scripts/` holds the MCP deployment helper. `generated-tests/`, `reports/`, and `*.sqlite` are runtime output and are ignored by Git.

## Build, Test, and Development Commands

There is no separate build step. Use Python 3.11.7 or newer and `uv`:

```bash
uv sync                              # Install locked dependencies
uv run python -m playwright install chromium
cp .env.example .env                 # Configure one LLM provider
uv run python -m src.index           # Run the interactive agent
uv run python -m src.mcp.index       # Run the MCP stdio server
uv run pytest                        # Run handwritten tests
uv run ruff check src tests          # Check configured lint rules
uv run python -m src.cli.run-tests   # Run saved generated E2E tests
```

## Coding Style & Naming Conventions

Use four-space indentation and follow the surrounding Python style. Ruff enforces selected `E4`, `E7`, `E9`, and `F` rules; run it before submitting changes. This Python port preserves historical hyphenated filenames such as `src/tools/broken-images.py` and public camelCase names such as `findBrokenImages`; retain those names for compatibility. Import hyphenated modules with `importlib.import_module()`. See `AGENT.md` and `MIGRATION_PLAN.md` before changing migrated interfaces.

## Testing Guidelines

Pytest discovers `tests/**/*.test.py` and `*_spec.py`; test functions use `test_` names. Add focused tests beside related tests, and mark async tests with `@pytest.mark.asyncio`. Playwright browser tests require installed Chromium. Keep generated E2E tests under `generated-tests/<category>/` and run them with `uv run pytest generated-tests/<category>/` when investigating a category. No coverage threshold is configured.

## Commit & Pull Request Guidelines

This checkout has no Git history, so no existing commit-message convention can be verified. Use short, imperative subjects that describe the change. In pull requests, explain the behavior changed, list verification commands and results, link any relevant issue, and include screenshots when browser-visible behavior or report output changes.

## Security & Configuration

Copy `.env.example` for local settings and provide either `GOOGLE_AI_STUDIO_API_KEY` or `OPEN_AI_API_KEY`. Keep `.env`, `.auth.key`, SQLite databases, reports, and generated tests out of commits; they may contain credentials or target-site data.
