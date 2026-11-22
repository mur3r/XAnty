# Workspace operations, items 20–32

Preserve the existing nineteen features and all user data. Use the existing Python/aiohttp/vanilla UI and one writable workspace lease; no git publication.

- Measure each profile's Chrome directory plus cookie/tab snapshots in a background worker, skipping links/reparse points. Show GB in the table without including the shared Chromium installation.
- Reuse selective cache cleanup for temporary browser cache, including batch actions for closed profiles. Never clear cookies, local storage, sessions or extensions.
- Expose one shared selected Chromium/Chrome-for-Testing build per workspace and compatible driver; install official paired Windows builds into managed version folders, switch only with profiles closed, retain bundled fallback. No unverified mirror downloads.
- Preview and delete only aged recognized update/cache staging artifacts, excluding active downloads, current executable, profile data, backups and the rollback executable. Never sweep global Windows temp directories.
- Per-profile Image/Media/Font controls plus native Safe Browsing and a local MV3 suspicious-navigation warning. Heuristics supplement vendor protections, not a guarantee against all phishing.
- Important or favorite profiles require a typed DELETE confirmation before manual trash/permanent removal.
- Full verified local backups configured with destination, interval and retention; disabled until a destination is chosen. Run while XAnty is active and when all profiles are idle/closed; postponed state is visible. Retention removes only this workspace's own backup files.
- Safe export is explicitly settings-only when any secret exclusion is requested; omit cookies, arbitrary metadata, tokens/passwords/proxy credentials and raw browser storage. Full transfer remains available as a separate choice.
- Named window sets store stable profile IDs. Opening a set resolves exactly its membership; missing/trashed members reject the operation. Exact mode saves/closes profiles outside the set after an in-product confirmation.
- Reminders store timezone-aware UTC action dates and a note; UI uses local time, shows overdue/upcoming reminders and supports completion/rescheduling. Notifications happen inside XAnty while open and at the next launch.
- Error panel groups current launch/proxy errors into clear causes, actions and retry/edit/check buttons, with credentials redacted.

Agents own Chromium manager, safe export/backups, and browser policy modules. Root owns metadata/window sets/storage/cleanup/error panel, UI and integration. Tests use temporary roots and browser/network doubles; final executable version 2026.11.22.8.
