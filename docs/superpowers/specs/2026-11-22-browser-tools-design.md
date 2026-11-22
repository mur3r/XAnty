# Browser tools, items 10–19

Extend the existing desktop manager and preserve the earlier nine profile features. Independent archive integrity and extension-store implementations run in parallel; core integration stays in this checkout, with no remote publication.

- Export new SHA-256 checked packages; staged import verifies every payload before committing. Legacy packages show missing integrity verification explicitly. Include tab snapshots and managed extension files.
- Restore normal HTTP(S) pages with Chrome's native session restoration and a periodically saved URL snapshot. Preserve native restored pages while proxy verification/sign-in use a bootstrap tab. Do not promise unsaved form/JavaScript state.
- Local unpacked Manifest V3 extension sets are copied to managed storage and into profile directories, loaded alongside proxy authentication. No automatic third-party downloads. Selecting a set at creation materializes it immediately; changes apply on next launch.
- View all-site cookies, paste JSON/Netscape or load a local file, merge into a closed profile; next launch applies independently of X automatic sign-in. Existing X-only endpoints remain compatible.
- Open a validated profile directory through Windows Explorer. Cache clearing touches only known cache directories and requires an exclusive idle profile lease.
- Autosave cookies and tab snapshots, default 60 seconds, configurable 30–3600 seconds, with a global switch. Tab snapshots refresh every 10 seconds for manual-close recovery. Chrome retains persistent local storage itself.
- Diagnose browser egress IP, WebRTC ICE public-address mismatches and observed DNS resolvers using dnsleak.dev's documented API from a temporary browser tab. Failure/inconclusive results never become a pass. DNS operators/geography alone do not prove a leak. Clearly name external test services in the UI.
- Optional per-profile window color and global frame switch; Windows DWM with a foreground-only click-through fallback on older Windows.
- An OS-held lock plus exact Chrome profile-process detection prevents conflicting starts across application instances. Failed/cancelled launches release it only after cleanup; no global Chrome/ChromeDriver killing at startup/shutdown.

Runtime Selenium operations serialize per browser. Close waits for an in-flight save/diagnostic; configuration/file operations reject busy/open/external profiles. Tests use temporary roots and fake browser boundaries; final build is version 2026.11.22.7.
