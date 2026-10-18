# Changelog

## v1.3.6 (2026-10-11)

- **Added**
  - Site settings split by domain, with an idempotent startup migration.
  - Versioned schema migrations: run automatically, or manually from the admin panel with a visible history.
  - Manual mode: an upgrade page serves every other request until the migrations are done, then the site recovers on its own.
  - "Migrate Database" admin page.
  - Configurable log level; log files rotate by size and live on the host.
  - Timestamps for banner changes and failed sign-ins.
  - Refuse to start when the code is older than the database, with an opt-out switch.
  - Admin Guide in both languages and an upgrading chapter.
- **Fixed**
  - Database backups work with non-root accounts.
  - Password reset links no longer carry the password hash.
  - The site enters maintenance mode when a schema migration fails.
  - Database errors roll back the session before fallback.
  - MySQL passwords are URL-encoded in the connection URI.
  - Article deletion no longer reports failure after commit.
  - Admin article and draft lists are paginated.
  - Concurrent first visits to admin settings pages no longer collide.
  - Very large page numbers no longer cause a server error.
  - Admin error messages no longer expose raw exception text.
  - Article and settings forms report validation errors.
  - Orphan-image lookup matches keywords literally.
  - Table-of-contents anchors skip unpaired heading tags.
  - Language switching uses a POST request.
  - Failed comments and replies roll back and report the failure.
  - GIF animations keep frame count, per-frame duration and loop count.
- **Improved**
  - Dead code removed.
  - Standardized comment wording.

## v1.3.5 (2026-09-16)

- **Added**
  - Pre-start environment check for Compose.
  - The container generates and persists its own session key.
  - Admin comment management, with deletion of comments and replies.
  - Configurable session lifetime.
- **Fixed**
  - SQLite restore validates before replacing the live database, and is mutually exclusive across processes.
  - Site settings read and written as a single row.
  - Expired rate-limit rows are cleaned up.
  - Search keywords match literally.
  - The database init script is safe to re-run.
  - Profile links reject pseudo-schemes.
  - Backup and restore work with newer database clients.
  - Missing images fall back to built-in placeholders.
  - Search row layout in the collapsed mobile menu.
  - The theme switcher works on touch again.
  - Admin breadcrumbs show their sidebar group.
  - The reverse proxy no longer advertises its version.
- **Improved**
  - Database image upgraded to 8.4; existing accounts keep authenticating.
  - Unused config removed.
  - Workflow dependencies pinned to fixed versions; code security scanning added.
  - Quality gate adds type checks, format checks and dependency-consistency checks.
  - Vulnerability scanning blocks the build on the main branch and the scheduled run.
  - Dependencies with known vulnerabilities upgraded.

## v1.3.4 (2026-09-12)

- **Added**
  - Security headers are issued by the application.
  - Hotlink protection for uploaded assets.
  - Configurable static-asset caching.
- **Fixed**
  - The setup wizard no longer errors when two processes create the first account.
- **Improved**
  - The reverse proxy config is plain proxying.
  - First-install logging is informational instead of a misleading warning.

## v1.3.3 (2026-09-12)

- **Added**
  - Health probe.
  - Startup waits for the database to become ready.
  - The image entrypoint fixes bind-mount ownership.
  - A Windows-capable WSGI server.
  - A ready-to-uncomment HTTPS template for the reverse proxy.
  - Icon fonts bundled locally.
- **Fixed**
  - Login failures and redirect loops behind the reverse proxy.
  - The health-probe path was rewritten by the proxy.
- **Improved**
  - Compose works out of the box; SQLite mode needs no configuration.
  - Startup order follows container health.
  - Ports publish to the host loopback only.

## v1.3.2 (2026-09-11)

- **Added**
  - First-install wizard.
  - Password recovery by email.
  - Database backup and restore.
  - Article SEO metadata and a sitemap.
  - Article table of contents.
  - Pinned marker, test-email button and category style switch.
- **Fixed**
  - A wrong password can no longer establish a session.
  - Unreadable archive text in the dark reading theme.
  - Database restore no longer hangs or damages tables.
  - Database errors and error pages degrade gracefully.
- **Improved**
  - The mail password is stored encrypted and never echoed back.
  - Backup filenames are checked against path traversal.
  - Password recovery always answers the same, preventing account enumeration.
  - Login redirects are restricted to on-site paths.
  - Absolute URLs no longer trust the request Host.
  - Comments, replies and likes are rate-limited by IP.
  - Category menus render from a single template.
  - Account email and mail settings merged into one page.
  - Admin page layout unified.
  - Backups use a consistent snapshot.
  - The config template documents every setting.

## v1.3.1 (2026-09-06)

- **Added**
  - "About Me" page with its admin page.
  - Log out from the public pages.
- **Fixed**
  - Likes are clickable on list pages.
  - Contrast of success toasts.
- **Improved**
  - The list "all comments" link is plain text.

## v1.3.0 (2026-09-02)

- **Added**
  - Admin redesign: sidebar menu and admin home.
  - Full-site search.
  - RSS and Atom feeds.
  - Category rename.
  - Banner enable/disable.
- **Improved**
  - Article content is sanitized at render time, keeping formatting.

## v1.2.0 (2026-09-01)

- **Added**
  - Glassmorphism UI across the site.
  - Animated backgrounds and a built-in gallery, switchable and remembered.
  - Cursor effect, toasts and language switch.
  - Grouped navigation dropdowns.
  - Published-article management, recall to drafts, batch banner withdrawal.
  - Category deletion, Markdown file import, logo upload.
- **Fixed**
  - Drafts are no longer reachable anonymously.
  - Old uploads are cleaned up when articles or images are replaced.
- **Improved**
  - Likes use atomic increments, one per IP.
  - Docker deployment fixes and real client IPs behind the proxy.
  - Line endings and formatting normalized.
  - CI pipeline and security scanning.
  - Contributing, security and code-of-conduct docs added.

## v1.0.0 (2026-08-15)

- **Added**
  - Blog core: publishing, Markdown editor, code highlighting, drafts, article pages.
  - In-editor image upload with automatic compression.
  - Comments with replies, likes and category management.
  - Banner carousel with admin management.
  - Admin backend: login, site settings, password change, content management.
  - Chinese and English locales.
  - Docker deployment and dual-database support.
  - Deployment docs and screenshots in both languages.
- **Improved**
  - Refactored onto an ORM with a layered module structure.
  - Security baseline: CSRF protection, content sanitization, login lockout, upload validation.
  - Unified error page.
