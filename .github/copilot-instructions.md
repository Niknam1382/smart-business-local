# Copilot Instructions — Smart Business Local

## Project context
- **Product**: A local-first, offline-first smart business assistant for Persian-speaking small business owners.
- **Stack**: Python 3.12, Flet (UI), SQLite, local LLM via GGUF/llama.cpp, Telegram Bot API, Bale Pay gateway.
- **Architecture**: All AI inference runs locally. No cloud AI calls. No telemetry. No user data leaves the machine except Telegram messages and Bale Pay API calls initiated by the user.
- **Language**: UI is Persian (RTL). Code comments and docstrings may be Persian or English. Commit messages and PR descriptions MUST be in English.
- **Versioning**: `app/version.py` is the single source of truth. Never bump without explicit user request.

## Hard constraints (DO NOT violate)
1. **NEVER commit or push secrets**: `settings.json`, `secret.key`, `*.db`, `*.db-*`, `receipts/`, `models/`, `*.gguf`, `logs/`, private signing keys (`*.key`, `*.pfx`), or any `.env` file.
2. **NEVER touch** `app/branding.py`'s `UPDATE_PUBLIC_KEY_B64` or any signing-related file unless the task explicitly says so.
3. **NEVER force-push** to `main` or to any tag (`v*`). Tags are immutable after a successful release.
4. **NEVER modify** `.github/workflows/release.yml`'s trigger conditions or asset names without explicit instruction — downstream tooling and release notes depend on them.
5. **NEVER change** the UI language, brand colors, logo assets, or `BRAND_*` constants.
6. **NEVER delete or weaken** any test in `tests/test_repo_hygiene.py` — that file is the safety net for secrets/data leaks.
7. **Do not add** new runtime dependencies without updating `requirements.txt` / `pyproject.toml` AND justifying it in the PR description.

## Quality gates (every PR must pass)
1. `ruff check .` → zero findings.
2. `python -m pytest -q` → all tests pass, zero FAILED/ERROR.
3. No new files matching secret/data patterns in `git status --short`.
4. `git status --short` must be clean after `git add -A` and before final commit.
5. All code paths that touch money (payment, refund, invoice) MUST have tests, and any new logic in `app/core/finance.py` requires an accompanying test in `tests/`.

## Preferred workflows
- **Bug-fix PRs**: One logical fix per PR. Include a regression test if the bug was reproducible. Keep diffs small.
- **Optimization PRs**: Separate from bug fixes. Benchmark before/after with a small script and include results in the PR description.
- **Refactor PRs**: Do not mix with feature work. Preserve public APIs unless the task says otherwise.
- **Test-timeouts**: Pre-existing `wait_until(..., timeout=20)` values are intentional for CI stability — do not reduce them.

## Reporting
At the end of every task, provide:
- A summary of what changed (file-by-file).
- Which quality gates were run and their results.
- Any follow-up tasks discovered but not addressed (with reasons).
- Any assumptions made about behavior not covered by tests.

## Out of scope for autonomous work
- Creating GitHub Releases or pushing tags.
- Modifying `CHANGELOG.md` version headers.
- Changing `app/version.py`.
- Touching `scripts/make_signing_key.py` or `scripts/sign_release.py`.
- Anything requiring a real Telegram token, real Bale Pay credentials, or real user data.