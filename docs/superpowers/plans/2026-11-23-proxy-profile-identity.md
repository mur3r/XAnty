# Proxy startup and profile identity plan

**Goal:** Predictable no-churn browser launch, no profile frames, readable browser/taskbar identities.
**Spec:** docs/superpowers/specs/2026-11-23-proxy-profile-identity-design.md
**Architecture:** Focused proxy/CDP and Windows identity adapters integrated with current BrowserManager and profile metadata. Existing main-app tray is preserved.
**Constraints:** Preserve uncommitted user work and .10 compatibility; don't use real user proxy credentials/data in tests, don't change unrelated Windows settings or publish commits/releases.

- [x] Reproduce proxy IP rotation and service navigation behavior with focused tests.
- [x] Implement quiet proxy verification, bounded authentication readiness and tab preservation.
- [x] Remove colored-frame module, runtime hooks, UI and settings.
- [x] Implement stable profile name/icon/AppID and native Chrome profile labels.
- [x] Resolve taskbar label preference and apply only the user's authorized choice.
- [x] Integrate, review, run full suites and isolated native/browser smoke.
- [x] Build/inspect version2026.11.23.2, stage alongside installation and report exact behavior.

## Final implementation and evidence

- Proxy checks run in the exact extension worker, without creating page targets. The browser socket must use the configured proxy; independent exit IPs need not match. Authentication, certificate and proxy connection failures remain explicit. An unavailable IP service can use the second service through the same proxy. Canonical URL matching includes the slash Chrome adds before query parameters.
- Optional search-provider repair uses a non-activating background target and caches verified success per Chrome major version. Existing selected search providers and user tabs survive. Restoration is idempotent, and manual sign-in no longer forces about:blank.
- All frame runtime code and controls were removed. Old saved frame preferences are ignored and rejected by the preferences endpoint.
- The user requested text inside the taskbar icon and declined global taskbar label changes. Native ICOs contain full short names or an abbreviation, with an optional eight-character `icon_text`. Full names appear in native window titles, Chrome profile preferences and the pinned local toolbar badge popup. No Windows taskbar settings were changed. Recovery retains profile identity and workspace options.
- Full Python suite: 301 tests, OK, three environment-dependent skips. Node: 16 tests plus the existing profile UI runner passed. Python compilation, all static JavaScript syntax and git diff whitespace checks passed.
- Real Chromium 128 tests: two authenticated CONNECT launches accepted different synthetic exit IPs; each retained a single unchanged tab; a wrong password was rejected. Separate browser smoke preserved focus/tabs, repaired/cached No Search, avoided duplicate restored tabs and rendered the full-name popup. Native Windows smoke verified AppID, icon handles, title changes and restoration on detach.
- Frozen EXE smoke in a disposable workspace verified readiness, icon text persistence, removal of frame settings, backups, safe export, reminders/window sets and current static files. Archive inspection matched 22 modules and 279 assets to current source, confirmed websocket dependency and absence of the frame module.
- Built `dist/2026.11.23.2/XAnty.exe` (33,444,943 bytes), SHA-256 `56e76aa1527925e94cf5f666d34027699dae1cb3815e56884bb6c7555749a544`. Identical delivery copy: `<installation>\XAnty-2026.11.23.2.exe`. Original installed executable and real user profiles/processes were left intact.
