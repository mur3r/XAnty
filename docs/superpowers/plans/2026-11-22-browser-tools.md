# Browser tools implementation plan

> **For agentic workers:** Apply test-first implementation; isolated archive, extension and window-frame modules can run in parallel.

**Goal:** Add requested profile-transfer/session/browser tools, items 10–19.
**Architecture:** Keep current aiohttp/vanilla UI. New focused modules own workspace snapshots, OS leases, network diagnostics, extension sets and window frames; existing actions expose them.
**Tech Stack:** Python 3.9+, Selenium/CDP, psutil, ctypes/Win32, aiohttp, vanilla JS, unittest/node:test.
**Spec:** docs/superpowers/specs/2026-11-22-browser-tools-design.md

## Global constraints
- Keep existing profiles, cookies and all nine previous features.
- No new remote publication, browser login or installed extension downloads.
- Corrupt packages and conflicting sessions must cause no profile-data changes.
- Diagnostics distinguish failure/inconclusive from measured success.

## Review focus
- Archive mutation, missing bytes, legacy packages and cancellation before commit.
- Two processes launching the same profile, cancellation and process ownership.
- Manual window close, bootstrap tabs and snapshot/restore ordering.
- Cache deletion preserves cookies/local storage/extensions/sessions and rejects reparse points.
- Cookies and diagnostics apply to the selected profile without changing user tabs.

### Task 1: independent modules
- [x] SHA-256 package integrity and tab portability, with real archive tests.
- [x] Managed extension sets and stable IDs, with temporary-directory tests.
- [x] Optional Windows frame controller, with native-boundary tests.

### Task 2: session runtime
- [x] Write failing tests for cross-process locks, tab snapshots/restore, all-site cookies and selective cache cleanup.
- [x] Implement profile_leases.py, browser_workspace.py and network_diagnostics.py.
- [x] Integrate launch/close/autosave/Chrome settings and eliminate global process cleanup.

### Task 3: APIs and UI
- [x] Extend preferences/profile settings and add tools endpoints, validation and API tests.
- [x] Add editor/settings/cookie/diagnostic/extension dialogs and row actions; three translations.
- [x] Verify existing/new suites, JavaScript, UI smoke test, review and build 2026.11.22.7.

## Execution record
- Baseline: 109 Python tests passed using .venv/Scripts/python.exe.
- Existing uncommitted earlier feature work is preserved; no worktree/commit/push requested.

- Final verification: 196 Python tests ran, one symlink privilege skip; 5 JS tests passed; syntax and compileall checks passed.
- Real bundled Chrome 128 smoke: two HTTP pages and HttpOnly session cookie survived close/reopen; no extra bootstrap tab remained.
- UI smoke: global interval/frame settings persisted, local MV3 set created, a profile materialized the selected set, all-site cookie paste preserved both sites.
- Writer safety ruling: one writable XAnty per base directory; OS lease acquired before metadata initialization and released after owned pending operations finish.
- Review fixes: initialization rollback, explicit closing/file-worker drains, first-launch/bootstrap cleanup, exact driver identity, external rename leases, extension deselection and unmeasured IP handling.
- Maintenance checkpoint and purge workers now share the shielded drained future set; late mutation requests are rejected once shutdown starts.
