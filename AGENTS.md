# Repository Guidelines

## Project Structure & Module Organization

This repository contains small Python autocollectors for Wizardry Variants Daphne store rewards.

- `main.py` is the international store collector, using Selenium against `https://store.wizardry.info/`.
- `main_jp.py` is the JP webstore collector, using Playwright against `https://webstore.wizardry.info/`.
- `requirements.txt` lists runtime dependencies.
- `.github/workflows/python-app.yml` runs the international collector on the weekly GitHub Actions schedule.
- `.github/workflows/keep-alive.yml` keeps scheduled workflows from being disabled after inactivity.
- `cloud-init/oci-github-runner.yml` provisions the OCI self-hosted runner used by the JP collector.
- Runtime screenshots and traces are written to `artifacts/` and must remain uncommitted.

## Build, Test, and Development Commands

Create an isolated environment before installing dependencies:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run the international collector locally:

```sh
python main.py YOUR_WIZARDRY_USER_ID
```

Run the JP collector locally after setting credentials:

```sh
export WIZARDRY_JP_EMAIL="you@example.com"
export WIZARDRY_JP_PASSWORD="..."
python main_jp.py
```

For first-time Playwright setup, install browser binaries with `playwright install chromium`.

## Coding Style & Naming Conventions

Use Python 3.10-compatible code for GitHub Actions. Follow the existing style: 4-space indentation, lowercase function names, uppercase constants such as `FREE_PRODUCT_IDS`, and concise comments only where browser behavior or regional constraints need context. Keep selectors and product IDs close to the flow that uses them, and prefer explicit exit codes for automation-facing scripts.

## Testing Guidelines

There is no formal test suite yet. Before submitting changes, run the affected collector manually against a non-sensitive test account when possible. For JP changes, inspect `artifacts/trace_jp.zip` with:

```sh
playwright show-trace artifacts/trace_jp.zip
```

If tests are added, place them under `tests/`, name files `test_*.py`, and document any mocked browser behavior.

## Commit & Pull Request Guidelines

Recent history uses short conventional prefixes: `feat:`, `fix:`, `docs:`, `ci:`, and `chore:`. Keep commit subjects imperative and scoped, for example `fix: handle missing GDPR banner`.

Pull requests should include a summary, affected script or workflow, local run result, and any relevant trace or screenshot notes. Do not attach credentials, user IDs, cookies, or raw Playwright traces containing logged-in session data.

## Security & Configuration Tips

Store secrets only in GitHub Actions secrets or local environment variables. Never commit `.env`, `artifacts/`, `.playwright-cli/`, screenshots, traces, or browser profiles because they may contain account identifiers or session data.
