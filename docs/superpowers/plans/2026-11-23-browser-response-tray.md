# Browser responsiveness and tray implementation plan

**Goal:** Fix evidenced rendering/frame delays and deliver Esc-to-tray with full tray exit.
**Architecture:** Existing Chrome launch, native frame thread and pywebview lifecycle; focused stdlib Win32 tray adapter and one shared Esc handler.
**Spec:** docs/superpowers/specs/2026-11-23-browser-response-tray-design.md
**Constraints:** Preserve uncommitted prior features and user profiles. No global Esc interception or process-wide Chrome cleanup. No commits/pushes. Build2026.11.23.1.

- [x] Measure current rendering mode and native frame wait/mutation behavior in isolated fixtures.
- [x] Add failing browser flag test; remove forced software rendering and verify native launch.
- [x] Add failing frame/message wait tests; implement responsive message wake and idempotent native calls.
- [x] Add tray/desktop lifecycle tests; implement recoverable hide, restore, full exit and Explorer restart.
- [x] Test Esc precedence and implement shared handler in main/loading/error views.
- [x] Run complete Python/JS verification, review shutdown and recovery paths, document use.
- [x] Build and inspect EXE; smoke actual new executable with isolated data.

## Verification evidence
- Isolated Chrome128 SystemInfo: old forced software mode disabled GPU compositing/canvas/rasterization; default mode enabled them with NVIDIA GTX1050 Direct3D11. ChromeDriver already passes the occlusion test switch, so additional broad background CPU switches were not added.
- Native hidden-desktop frame probe: median synchronous window-message response158.81ms old vs0.12ms new; native wake0.31ms, proper event handle closure. These are message response measurements, not end-to-end physical Alt+Tab timings. 35 frame tests pass.
- Independent review found elevated TaskbarCreated filtering; scoped ChangeWindowMessageFilterEx added with failure keeping app reachable. No OS elevation or Explorer restart was done during QA.
- Installed EXE was2026.11.22.10 while cwd source was.8. Compared packaged modules and preserved immutable upstreamtag v2026.11.22.10 (commit d4b674a94d1d57f676be5db87432b690d97dea31): runtime browser fallback, startup updates, installer mutex, health acknowledgement/rollback. Added regression coverage for Exit during update download/install progress.
- Final Python305 tests, 3 skips, zero failures; JS15 tests, legacy UI runner, syntax and compile checks pass.
- Onefile EXE2026.11.23.1 built. Required packaged Python modules normalized against current source code and JS/startup/helper assets checked byte-for-byte. SHA256 dc00e59e35ad02a8a4c99b6e134bb18c47319ec19b4a7f720be198171960d7ce;33,421,617bytes.
- Actual frozen EXE started against isolated synthetic data. CUA Esc changed its HWND from visible to hidden, while its API remained ready and kept its test profile. Shutdown drained backend and kept profile metadata. Native tray dispatch, restore, menu exit and Explorer recovery were tested through unit/native adapter tests; the CUA surface did not expose taskbar controls, so no claim is made of manually clicking the tray menu. Disposable process was terminated only after backend stopped; existing installed app and user profiles were untouched.
