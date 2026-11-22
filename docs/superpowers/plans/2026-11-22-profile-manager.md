# Profile Manager Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Improve daily profile management and deliver opt-in GitHub Releases updates.

**Architecture:** Extend the current aiohttp API and plain JS frontend. Separate network geography and update installation from UI logic.

**Tech Stack:** Python, unittest, aiohttp, requests, WebView2, plain JavaScript, PowerShell, PyInstaller.

**Spec:** docs/superpowers/specs/2026-11-22-profile-manager-design.md

## Global Constraints

- Existing user data and browser launch behavior remain compatible.
- Geography requests use the selected proxy; failure must not invalidate a working proxy.
- Update installs require closed profiles and no active transfers, a configured repository, a onefile build and verified GitHub SHA-256.
- No publication or real self-update during verification.

## Review Focus

- A changed proxy must never inherit a previous proxy's country or late check result.
- A partial geography failure still shows a working proxy and IP.
- Filters must not silently select unrelated profiles.
- A completed transfer with errors must notify with report access.
- Corrupt downloads and busy profiles must never start replacement.

### Task 1: Geography and launch diagnostics

**Files:** xgenius/proxy_service.py, models.py, web/actions.py, web/engine.py, accounts/auth.py; tests/test_proxy_button.py and new geography/launch tests.

**Interfaces:** `lookup_proxy_location(proxy, ip) -> dict`; runtime `proxy_location`, `launch_error`; public account rows include those fields.

- [x] Write failing behavior tests for geography routing, partial failure, stale result and launch error redaction.
- [x] Run tests and observe expected failures.
- [x] Implement safe location lookup, state reset and actionable launch errors.
- [x] Run focused tests.

### Task 2: Table and shared styling

**Files:** web/static/app.js, index.html, i18n.js, style.css, assets/flags; tests/test_profile_ui.cjs.

**Interfaces:** search/status/proxy filters consume account state from task 1; batch checks use existing proxy endpoint.

- [x] Write failing Node tests for combined filtering, filtered selection, transient states and launch/transfer notifications.
- [x] Implement filtered selection, batch checking, flag/location cells, error details and dismissible notifications.
- [x] Unify CSS tokens and responsive toolbar behavior; bundle licensed SVG flags.
- [x] Run Node tests and visually inspect dark/light UI.

### Task 3: GitHub updater

**Files:** new xgenius/updates.py, update_config.json, update_helper.ps1, web/static/updates.js; server.py, desktop.py, build script/spec, release instructions/workflow; tests/test_updates.py.

**Interfaces:** GET /api/updates; POST /api/updates/check, /download, /install. State includes configured/status/release/error/can_install.

- [x] Write failing tests for numeric versions, release asset validation, checksum failure, download cleanup and install guards.
- [x] Implement release checking, streamed verified download and helper generation/launch.
- [x] Implement banner, notes, manual checking and install flow; persist last check/notification metadata.
- [x] Add release/build configuration and documentation.
- [x] Run full unittest suite, Node tests, syntax checks and separate Windows build.

## Execution ledger

- Baseline: 62 unittest tests pass. Workspace has no .git; use source backup and file comparison for review, no git operations.
- Ruling: execute requested UI improvements directly; the user's update-button approval covers the proposed updater design. Repository remains a configurable integration point until supplied.

- Final verification: 81 Python tests pass; Node UI behavior and JS syntax checks pass; Python compilation passes.
- Selenium QA: dark/light themes, all three languages, compact layout, flag assets, combined filters, selection scope, batch checks, launch failures, update banner and fast XHR import completion passed with no browser console errors.
- Independent review: updater concurrency, active uploads, joining running proxy checks, fast import tracking, country search and helper restart findings were fixed and rechecked.
- Windows helper tests use only temporary files and a stubbed process launch: atomic replacement, backup, restart failure rollback, checksum failure and restarting the original all pass.
- Build: onefile 2026.11.22.3 produced in dist/2026.11.22.3; final build and frozen smoke results are recorded under tmp and output/manager-qa.
- Pending external integration: the user will create and provide the GitHub repository. The channel deliberately remains disabled. A live release/update between two test builds must be checked after connection.
