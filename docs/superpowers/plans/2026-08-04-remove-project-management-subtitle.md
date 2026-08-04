# Remove Project Management Subtitle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the project-management subtitle without leaving an empty subtitle element.

**Architecture:** Keep the existing page-title map and represent the deliberate absence of the project subtitle with an empty string. Render the shared subtitle element conditionally so all other admin tabs continue using the same path.

**Tech Stack:** Vue 3, TypeScript, Playwright

## Global Constraints

- Preserve the project title, actions, and governance summary cards.
- Do not change subtitles for other admin tabs.

---

### Task 1: Remove the project subtitle

**Files:**
- Modify: `frontend/e2e/aicheck-smoke.spec.ts`
- Modify: `frontend/src/views/AICheck/AdminOverview.vue`

- [x] Add a Playwright assertion that the project subtitle is absent while the page title remains visible.
- [x] Run a focused regression check and confirm it fails for the old subtitle.
- [x] Empty the project subtitle configuration and conditionally render the subtitle element.
- [x] Re-run the focused regression check and TypeScript check.
- [x] Review the diff for scope and formatting.
