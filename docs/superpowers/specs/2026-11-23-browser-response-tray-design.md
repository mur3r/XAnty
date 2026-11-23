# Browser responsiveness and background desktop mode

User asks to fix sluggish manual use, especially Alt+Tab back to managed Chrome, and hide XAnty to the Windows notification area with Esc; full exit must be available from its tray icon.

## Evidence and chosen behavior
- Host is Windows 10 build 19045 with Intel HD630 / NVIDIA GTX1050. Current browser launch unconditionally passes `--disable-gpu`, a legacy server setting unsuited to interactive desktop browsing. Remove it and let Chrome select supported hardware acceleration. Preserve profile/proxy/authentication policies and normal background resource management; do not globally disable timer throttling as an assumed fix.
- Windows 10 colored frames use four cross-thread owned popup strips. Polling their shared input queue every150ms can stall foreground activation. Investigate with an isolated native harness, replace polling-only wait with message-aware waking, and avoid repeated native geometry/visibility mutations. Keep foreground-only, click-through, nonactivating frames.
- Esc hides the XAnty window without stopping its engine or profile sessions. Existing dialogs/inline rename consume Esc first; row action menus close first. Modified Escape shortcuts retain their usual meaning. No global keyboard hook, so Esc in managed Chrome is unaffected.
- A notification icon has Open and Exit actions plus double-click restore. Hide is allowed only when the icon is ready, so tray failure cannot strand a hidden app. Exit uses the existing normal window-destroy/server-drain path. The existing X close behavior remains full exit. Loading/error pages use the same Esc script.
- Tray icon belongs to a dedicated native message thread; recreate on Explorer taskbar restart, remove on shutdown. No additional runtime dependencies.

## Approaches
Chosen: small stdlib Win32 adapter for tray plus existing pywebview bridge, existing colored-frame monitor with a native message-aware wait. This preserves the current app and packaging. A new tray library adds a dependency with the same native lifecycle requirements; ownerless frame overlays complicate z-order and obscuration safety. Neither is needed.

## Verification
Tests pin launch flags, Esc event precedence, bridge/tray availability, show/hide/full exit, icon lifecycle and message waiting. Run isolated real Chrome GPU diagnostics and native frame/message harness; never change or open user profile data. Verify full suites and a newly built onefile EXE version2026.11.23.1. Quantify the mechanism fixed; do not claim all possible website/network slowness is eliminated.
