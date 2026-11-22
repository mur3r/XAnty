# Responsive startup, logo and GitHub release

**Goal:** use the supplied logo, remove blocking desktop startup and connect the public GitHub update channel.

**Decisions:** Preserve the supplied artwork exactly and generate ICO sizes as file-format conversion. Create the native window with a local loading page before importing or initializing the backend; start the server through pywebview's background startup callback and navigate once ready. Closing during startup must not reopen the window. Failures stay visible in the window and are written to a bounded startup log. Keep existing profile storage and updater verification.

**GitHub:** The user explicitly approved making mur3r/XAnty public. Verify tracked files are distributable, update repository configuration, push only reviewed source files, build and publish a release. Verify anonymous release metadata and asset download. GitHub connector is disconnected; use existing Git credentials without exposing them.

- [ ] Add regression tests showing the window starts before a slow backend and errors remain visible.
- [ ] Implement nonblocking startup, graceful startup cancellation and diagnostic timing.
- [ ] Replace PNG with the supplied file; generate full ICO size set and bump version.
- [ ] Configure mur3r/XAnty, update release documentation, run full checks and build.
- [ ] Review source, publish authorized public repository/release, verify update API and installation on isolated test copies.
- [ ] Deliver executable and report verified results and any remaining limitations.
