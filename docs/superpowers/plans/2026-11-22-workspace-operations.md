# Workspace operations implementation plan

> **For agentic workers:** Use test-first implementation; independent version, backup/export and browser-policy modules run in parallel.

**Goal:** Implement items 20–32 and deliver a verified Windows executable.
**Architecture:** Focused modules under existing engine/actions with tracked background workers and the workspace lease. Extend profile metadata and append a workspace-tools UI module.
**Tech Stack:** Python 3.9+, unittest, aiohttp, Selenium/CDP, Chrome MV3, vanilla JS.
**Spec:** docs/superpowers/specs/2026-11-22-workspace-operations-design.md

## Global constraints
- Preserve user profiles, authentication, previous features and rollback executable.
- No shared-source commits/pushes or automatic downloads before the user presses Install.
- Never label a partial/heuristic check a complete security guarantee.
- Defer backups/version switching when files are in use.

## Tasks
- [x] Version manager with official compatible build pairs and validation tests.
- [x] Settings-only safe export, atomic verified local backup and retention tests.
- [x] Browser resource policies and phishing-warning extension with executable logic tests.
- [x] Profile size, aged-artifact cleanup, important-profile guard, named sets, reminders and classified errors with tests.
- [x] Wire APIs, background maintenance and three-language UI; review and verify all suites.
- [x] Build/inspect executable 2026.11.22.8 and report exact limitations.

## Evidence
- Baseline: 196 Python tests ran, one symlink privilege skip, no failures.
- Work proceeds in the user's existing checkout, preserving prior uncommitted features.
- Final Python: 282 tests passed, 3 symlink-privilege skips. Node: 12 tests passed plus legacy profile UI behavior runner. All JS syntax, Python compilation and diff whitespace checks passed.
- Real bundled Chrome 128: selected image requests blocked; suspicious main-frame navigation intercepted before the local server; 26 regexes accepted; full query/fragment preserved; continue-once works and revisits warn again. Fixed its fragment matching after the native smoke exposed it.
- Live official CfT manifest: 2,605 complete Windows pairs and all four channels returned. No actual CfT binaries were downloaded during QA.
- CUA with isolated synthetic data: backup saved/verified, reminder edited at correct local time, important deletion requires DELETE, profile policy fields present, English/Russian workspace rendering confirmed.
- Independent integration review found the dict-vs-keyword progress callback mismatch; corrected with a regression test. Final additional review agent could not finish because its usage limit was reached; no success claim is made for that review.
- One-file EXE built and contents verified against source static files and required modules. Frozen EXE launched in an isolated workspace and passed real backup, settings-only secret exclusion, reminder/window-set persistence and static-file checks.
- Artifact: dist/2026.11.22.8/XAnty.exe, 33,405,275 bytes, SHA-256 e1270e0a1973b83b622b94bac9dd3fe57c272663039b3b1d5921166947d86089.
- Limits are documented in UI and README: scheduled work requires XAnty open; backups defer while profiles open; URL heuristics supplement Safe Browsing; CfT manifests do not publish signed vendor hashes; secret exclusions use settings-only export.
