# Predictable launch and readable profile identity

User reports proxy verification opening/changing tabs and false failures, requests complete removal of colored frames, and readable profile names in the browser and on the Windows taskbar (explicitly confirmed taskbar, not notification icons).

## Evidence
- Launch performs an independent HTTP proxy IP request, steers Chrome to search settings, then to ipify and about:blank. It rejects any difference between two IPs, including legitimate rotating exits. prepare_workspace may create a tab and restore_tabs later closes/selects tabs. Manual-login path also navigates to about:blank.
- Colored-frame feature exists in native monitor, model/settings, API preferences and editor; it must be removed, not merely disabled.
- Taskbar icons are too small for arbitrary full names. The user explicitly requires text inside the icon image and declined global Windows taskbar label changes. Use the full short name or a readable abbreviation, with an optional icon text field (up to eight characters), and retain the full name in the browser and window title.

## Chosen behavior
- Verify proxy and browser route with bounded diagnostics and no direct network fallback; avoid comparing independent rotating exits as a correctness requirement. Keep bad authentication/transport failures explicit. Diagnostic work must not navigate or focus user tabs. Keep restored tabs exactly once, including their active page where possible.
- Preserve the bundled No Search repair without visible settings-page churn, using a hidden CDP target if supported. Do not replace a working chosen search engine.
- Remove all colored-frame runtime code, controls, preferences and credential fields. Keep unrelated cookies, proxy settings and recorded history intact; legacy color keys may remain inert in old data.
- Set native Chrome profile name before launch, and exact-owned Chrome window titles/icons/taskbar AppID after launch. Use stable profile identity across renames. Render contrasting text inside the icon; short names fit in full and longer names use a configurable abbreviation. A pinned toolbar badge uses the same image and exposes the full profile name in its popup and tooltip, without site permissions or page injection. No cross-process owned overlay windows.
- Preserve Windows tray behavior of the main app, startup update/rollback, shared Chromium selection and other earlier features. Leave global Windows taskbar behavior unchanged.

## Verification
Use red/green tests for rotating IP and endpoint errors, background request/target cleanup, restored-tab invariants, absence of frame controls, Unicode/stable profile labels, exact-window ownership and native resource cleanup. Native tests use synthetic profiles/local fixtures. Build a new verified onefile executable and stage beside the installed app; no real user profiles or active processes are modified.
