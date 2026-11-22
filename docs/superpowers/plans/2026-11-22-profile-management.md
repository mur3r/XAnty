# Profile management implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement all nine profile management improvements.
**Architecture:** Extend the atomic accounts JSON envelope with trash and audit events; integrate lifecycle timing in AccountManager and expose it through existing API and a focused UI module.
**Tech Stack:** Python 3.9+, unittest, aiohttp, vanilla JS/CSS.
**Spec:** docs/superpowers/specs/2026-11-22-profile-management-design.md

## Global Constraints

- Preserve legacy accounts and browser directories.
- UI supports Russian, English and Ukrainian.
- Never expose credentials in history.
- Trash expiry: 0 (forever) or 1–3650 days, default 30.
- Checkpoint runtime every 30 seconds; purge expired trash every minute and at startup.

## Review Focus

- Legacy profiles retain identity and data after migration/restart.
- Restore and expiry never delete an active or unrelated profile directory.
- Runtime is counted once on manual close, shutdown and restart.
- Favorites sort before pagination and search includes tags/numbers.
- History records bulk changes and masks credentials.

### Task 1: Persistent metadata, audit, trash, runtime

Files: xgenius/profile_metadata.py, xgenius/accounts/manager.py, tests/test_profile_management.py.
Interfaces: AccountManager.update_profile_metadata(names, data), trash_profiles(names, days), restore_profiles(names), set_trash_retention(names, days), purge_trash(names=None), profile_history(username=None), start_profile_session(username), finish_profile_session(username), checkpoint_sessions().

- [x] Write behavioral tests with temporary real files for migration, audit sanitization, retention/restore/purge and runtime boundaries; run and observe missing behavior.
- [x] Implement JSON envelope migration and atomic state/history writes, safe path cleanup, checkpoint timing.
- [x] Run new tests.

### Task 2: Lifecycle and HTTP integration

Files: accounts/auth.py, accounts/health.py, web/engine.py, web/actions.py, web/server.py, preferences.py; tests/test_profile_management.py.
Interfaces: PATCH /api/accounts/metadata, GET /api/history, GET/POST /api/trash and /api/trash/restore, /retention, /purge; existing delete accepts retention_days. Preferences accept columns and trash_retention_days.

- [x] Test real API validation, snapshot and session lifecycle behavior.
- [x] Wire manager calls to actual browser creation/closure and maintenance task; expose metadata API and preserve existing CRUD behavior.
- [x] Run affected tests and complete suite.

### Task 3: Table and management dialogs

Files: web/static/profile-management.js, app.js, dialogs.js, i18n.js, index.html, style.css; tests/profile_management_ui.test.js.
Interfaces: ProfileUI.columns(), applyColumns(), metadata(), trash(), history(), rename(), remove().

- [x] Add executable JS tests for favorites, cross-field search and column ordering.
- [x] Add status editing/filtering, favorites, persistent configurable columns, date/runtime, double-click rename, retention/restore/purge dialogs, history; add three translations.
- [x] Verify JS syntax and behavior, full Python suite, compileall, visual UI smoke test; update README.

## Execution record

- Baseline: .venv/Scripts/python.exe -m unittest discover -s tests -q — 85 passed.
- Ruling: Work in the requested clean checkout, without an extra worktree or approval interruption; user requested implementation and higher-priority autonomy instructions apply. No commit/push requested.
- Review: independent read-only reviewer found toolbar/script-order regressions, Windows filename aliases, stale runtime writes, reused-name audit filtering, persistence-failure lifecycle and import collisions. Each reproduced in an executable regression test and fixed.
- Ruling: runtime transition timestamps remain queued in memory until persisted, so a temporary disk error cannot extend a closed session or lose the original opening time.
- Final timing regression: pending events follow UUID through username changes and trash, and are applied before every JSON commit; only active profiles accumulate checkpoints.
- UI smoke checks use a separate TemporaryDirectory and preferences directory, without opening real account browsers.
- Final verification: 109 Python tests, 5 executable JS tests, JS syntax checks, compileall, and UI search/favorite/status/rename/columns/trash/retention/restore/history checks passed.
- Delivery: one-file Windows build 2026.11.22.6 in dist/2026.11.22.6/XAnty.exe. No release publication or remote writes requested.
