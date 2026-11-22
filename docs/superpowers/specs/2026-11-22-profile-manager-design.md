# XAnty: profiles, proxy geography and GitHub updates

The requested changes improve the existing Python/aiohttp/WebView2 application. Keep the existing storage and browser launch paths. The user approved updates initiated with an Update button; the GitHub repository is still pending.

## Approaches

Extend the existing table rather than replace the frontend: preserve folders and editing, add proxy filters, filtered selection, batch proxy checks and visible error details. This is the smallest change compatible with existing users.

Use GitHub Releases rather than git pull or an installer service. Releases distribute the existing onefile EXE without requiring Python or Git on the user's machine. Download only the configured repository's XAnty.exe, require its GitHub SHA-256 digest, and install after the user closes profiles and transfers. Keep the previous EXE for rollback. Source and onedir runs support checking releases but do not self-replace.

## Behavior

- Neutral surfaces and borders; purple actions and focus, green success, red failure. Consistent control heights, spacing, stroke icons and accessible status messages.
- Search name, folder, proxy address, checked IP, country and region. Combine status and proxy filters. Select page or all matching rows, show hidden selections, retain selection between pages. Batch operations use selected existing profiles only.
- Proxy check preserves fail-closed routing. After a successful IP check query ipwho.is for that IP through the same proxy. A location-service failure leaves proxy success intact and explains missing geography. Show bundled country flag, country (US displayed as USA), region and IP. Clear location after proxy changes or failed checks. Reject stale results if a proxy changes during a check.
- Persist a safe, actionable launch failure in runtime state. Notify when a launch fails and when a transfer finishes, fails, or completes with per-profile errors. Existing detailed reports remain available.
- Updates check at startup and daily while running. A banner shows version and release notes. Manual checking reports network/no-release/configuration errors without blocking profiles. Concurrent checks/downloads share work. Verify size, PE header and SHA-256 before install. A hidden PowerShell helper waits for this process to exit, backs up and replaces the EXE, restarts it and rolls back on replacement failure. Never replace account/browser data.
- Update source lives in a bundled JSON configuration and can be overridden by environment for development. No repository is fabricated. Include release publication instructions and optional GitHub Actions workflow.

## Verification

Unit tests for geography parsing, routing, partial failures, credential redaction, stale results, update version ordering and download integrity; API tests for update guards. Node behavioral tests for filters, selection and notifications. Full existing unittest suite, JS syntax checks and visual QA with isolated demo profiles. Build a new EXE into a separate output directory.
