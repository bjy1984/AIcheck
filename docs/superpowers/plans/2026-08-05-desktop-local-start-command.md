# Desktop Local Start Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing macOS desktop command start the API, frontend, and PostgreSQL MinerU worker with one consistent local-only environment.

**Architecture:** Replace the duplicated desktop launcher body with a thin local wrapper around `scripts/start-local-dev.zsh`. The wrapper preserves local role bootstrap variables, stops stale MinerU worker processes before launch, opens the local browser URL, and clearly rejects use as a server deployment command.

**Tech Stack:** zsh, macOS `.command`, existing repository local startup script.

## Global Constraints

- Do not modify server deployment configuration or application runtime behavior.
- Local startup must set optional object storage through the canonical repository script.
- Preserve the existing local role password behavior without printing secrets during verification.
- Do not create a second competing desktop launcher.

---

### Task 1: Replace the desktop launcher with a canonical local wrapper

**Files:**
- Modify: `/Users/hankieyooly/Desktop/启动KnowledgeTools服务.command`
- Consume: `/Volumes/7up/github/knowledgetools/scripts/start-local-dev.zsh`

**Interfaces:**
- Consumes: `AICHECK_DEV_NO_FOLLOW`, local role bootstrap environment variables, and `scripts/start-local-dev.zsh`.
- Produces: a double-clickable local macOS command that starts all three processes with matching storage policy.

- [ ] **Step 1: Verify the old launcher fails the contract** by checking that it contains no `apps.mineru_worker.main` or canonical `scripts/start-local-dev.zsh` invocation.
- [ ] **Step 2: Replace the launcher** with a zsh wrapper that validates the repository path, stops existing local MinerU worker processes, exports the existing local bootstrap password variables, runs `AICHECK_DEV_NO_FOLLOW=true zsh scripts/start-local-dev.zsh`, opens `http://localhost:4000/`, and reports the log directory.
- [ ] **Step 3: Preserve executable permissions** with `chmod 700 /Users/hankieyooly/Desktop/启动KnowledgeTools服务.command`.
- [ ] **Step 4: Verify syntax and dry-run output** using `zsh -n` and `AICHECK_DEV_DRY_RUN=true` without starting duplicate services.
- [ ] **Step 5: Inspect repository status** to confirm the desktop artifact is outside Git and no unrelated workspace file was changed.
