# W0 审计基线

- Captured from branch `main` at `705f81f9cb2f1cb8dde7a343dd784e5437269b84`.
- Upstream was `origin/main`, ahead/behind 0/0.
- Before audit artifacts were created, the worktree contained 21 modified files and 1 untracked source file: `backend/libs/official_ocr_control.py`.
- `git status` does not report an active rebase, although `.git/REBASE_HEAD` exists. The audit records the marker but does not modify or resolve it.
- Recovery material:
  - `worktree.patch`
  - `untracked-backup/backend/libs/official_ocr_control.py`
  - `worktree-manifest.json`
  - status and Git operation marker files
- OCR release evidence copied under `../release/` reports score 79, `ok=false`, 0 human-labeled cases, and 0/100 ready-for-evaluation cases.

## Baseline tests

All targeted existing suites passed when run with `backend/.venv/bin/python`:

- Review orchestration + FDE console
- Aliyun OCR runtime + pipeline hardening
- OCR release gates + Celery priority contract
- Targeted contract health/readiness/human-decision/operation tests

The first attempted run with the system Python failed because that interpreter did not have pytest installed; the output was overwritten by the successful project-venv run and is not treated as a product failure.
