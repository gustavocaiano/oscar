# CI/CD Pipeline — GitHub Actions

## Context

Oscar is a Python Telegram personal assistant bot deployed via Docker Compose on a single self-hosted server. There is **no existing CI/CD** and **no linting/formatting tooling** configured. The project uses:

- **Language:** Python 3.12
- **Build:** setuptools via `pyproject.toml`, `pip install -e .[dev]`
- **Tests:** pytest (7 test files in `tests/`)
- **Container:** Docker (single-stage `python:3.12-slim`) + Docker Compose (assistant + cliproxyapi)
- **Deployment target:** Self-hosted Docker Compose (~4 GB RAM budget)

---

## Prerequisites (tooling to add first)

Before the pipeline can run, add these to `pyproject.toml` dev dependencies:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.8",      # linting + formatting (replaces flake8, isort, black)
    "mypy>=1.10",     # type checking
]
```

Create `py.typed` marker if desired, and add `[tool.ruff]` / `[tool.mypy]` config sections.

---

## Pipeline Overview

### Workflow 1: CI — `ci.yml` (on every push & PR)

```
┌──────────────────────────────────────────────┐
│  Trigger: push, pull_request (all branches)  │
├──────────────────────────────────────────────┤
│                                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────────┐ │
│  │  Lint    │  │  Test   │  │ Docker Build │ │
│  │  (ruff)  │  │ (pytest)│  │  (validate)  │ │
│  └────┬────┘  └────┬────┘  └──────┬───────┘ │
│       │             │              │         │
│       └─────────────┴──────────────┘         │
│                     │                        │
│              ┌──────▼──────┐                 │
│              │  Compose    │                 │
│              │  Validate   │                 │
│              └─────────────┘                 │
└──────────────────────────────────────────────┘
```

#### Jobs

| Job | Runner | Steps | Purpose |
|-----|--------|-------|---------|
| **lint** | `ubuntu-latest` | Checkout → Setup Python 3.12 → Install deps → `ruff check` → `ruff format --check` | Catch lint/format errors early |
| **test** | `ubuntu-latest` | Checkout → Setup Python 3.12 → Install deps → `pytest --tb=short -q` | Run unit tests |
| **typecheck** | `ubuntu-latest` | Checkout → Setup Python 3.12 → Install deps → `mypy src/` | Static type analysis |
| **docker-build** | `ubuntu-latest` | Checkout → Docker build → `docker compose config` | Validate image builds and compose file is valid |

All four jobs run **in parallel** for speed. The test job installs Playwright Chromium if any test imports it (conditional).

#### Branch protection

Configure GitHub branch protection on `main`:
- Require `lint`, `test`, `typecheck`, and `docker-build` jobs to pass before merge
- Require PR reviews (1 approval minimum)

---

### Workflow 2: CD — `deploy.yml` (on push to main or version tag)

```
┌──────────────────────────────────────────────────┐
│  Trigger: push to main (staging) or tag v* (prod)│
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────┐                                 │
│  │ CI Pipeline │  (reuse ci.yml via workflow_call)│
│  └──────┬──────┘                                 │
│         │                                        │
│  ┌──────▼──────┐                                 │
│  │ Build &     │                                 │
│  │ Push Image  │  → GHCR (ghcr.io/<org>/oscar)   │
│  └──────┬──────┘                                 │
│         │                                        │
│  ┌──────▼──────┐                                 │
│  │ Deploy      │  → SSH to server                │
│  │             │  → docker compose pull           │
│  │             │  → docker compose up -d          │
│  └─────────────┘                                 │
└──────────────────────────────────────────────────┘
```

#### Jobs

| Job | Condition | Steps |
|-----|-----------|-------|
| **ci** | Always | Reuse `ci.yml` workflow (ensures CI passes before deploy) |
| **build-and-push** | After CI passes | Checkout → Docker login GHCR → Build + push image tagged with `sha` + `latest` (or version tag) |
| **deploy** | After build-and-push | SSH to server → `docker compose pull` → `docker compose up -d` → Health check |

#### Image tagging strategy

| Trigger | Tags |
|---------|------|
| Push to `main` | `main-latest`, `main-<short-sha>` |
| Tag `v*` | `<version>`, `stable` |

#### Deployment via SSH

Use `appleboy/ssh-action` or native `ssh` with secrets:

```yaml
deploy:
  needs: build-and-push
  runs-on: ubuntu-latest
  steps:
    - name: Deploy via SSH
      uses: appleboy/ssh-action@v1
      with:
        host: ${{ secrets.DEPLOY_HOST }}
        username: ${{ secrets.DEPLOY_USER }}
        key: ${{ secrets.DEPLOY_SSH_KEY }}
        script: |
          cd /opt/oscar
          docker compose pull assistant
          docker compose up -d assistant
          sleep 5
          docker compose ps assistant
```

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Server IP/hostname |
| `DEPLOY_USER` | SSH username |
| `DEPLOY_SSH_KEY` | Private SSH key |
| `GHCR_TOKEN` | GitHub PAT with `write:packages` |

---

## File Structure

```
.github/
├── workflows/
│   ├── ci.yml           # Lint, test, typecheck, docker-build (parallel)
│   └── deploy.yml       # Build-push-deploy (sequential, gated on CI)
```

---

## Implementation Tasks

1. **Add dev dependencies** — Add `ruff` and `mypy` to `pyproject.toml` `[project.optional-dependencies]`
2. **Add ruff config** — Add `[tool.ruff]` section (line-length, select rules, per-file ignores for tests)
3. **Add mypy config** — Add `[tool.mypy]` section (python_version, ignore missing stubs for telegram/whisper/etc.)
4. **Create `.github/workflows/ci.yml`** — Lint + test + typecheck + docker-build jobs in parallel
5. **Create `.github/workflows/deploy.yml`** — Reusable CI → build-push → deploy pipeline
6. **Fix existing lint issues** — Run `ruff check --fix` and `ruff format` on the codebase, fix mypy errors
7. **Add GitHub Secrets** — Configure `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `GHCR_TOKEN` in repo settings
8. **Set branch protection** — Require CI checks on `main`, require PR approval
9. **Update docker-compose.yml** — Reference GHCR image for the `assistant` service instead of local build (for deploy target)
10. **Test the pipeline** — Open a PR, verify all CI checks pass, then merge and verify deploy

---

## Notes

- **Playwright in CI:** The `test` job should only install Playwright Chromium if needed. Add `pip install playwright && playwright install chromium --with-deps` as a conditional step, or create a separate test job for browser-dependent tests.
- **Docker layer caching:** Use `docker/build-push-action` with `cache-from`/`cache-to` for GHCR to speed up builds.
- **Rollback:** Keep the previous image tagged; if deploy fails, SSH and `docker compose up -d assistant:<previous-sha>`.
- **Notifications:** Add Slack/Telegram notification step on deploy failure (post to a channel via webhook secret).
- **The cliproxyapi service** uses a pre-built image (`eceasy/cli-proxy-api:latest`) — no build needed, just pull on deploy.
