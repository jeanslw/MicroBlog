# MicroBlog Changelog

## [v1.3.2] - 2026-09-11

First-install setup wizard, email password recovery, database backup/restore, article SEO + sitemap, plus security hardening and a unified admin UI overhaul.

### Added

- First-install wizard (`/admin/setup`): when no admin account exists, every admin route redirects there to create the initial account (username / email / password) and sign in automatically.
- Email password recovery: `Admin` gains an `email` column (idempotent migration) plus an account-email management page; `/admin/forgot` + `/admin/reset` use signed single-use tokens (30-min expiry, bound to the current password hash).
- Database backup & restore: SQLite file copy and MySQL `mysqldump`/`mysql`, with list / download / delete / restore; a pre-restore snapshot is taken automatically for rollback (named `*_snapshot.zip`).
- Article SEO metadata: optional per-article description & keywords (auto-filled from content/category when left blank), rendered as `<meta>` and Open Graph tags.
- `sitemap.xml` (and a `Sitemap:` declaration in `robots.txt`).
- Article table of contents (h1–h3) with anchor jumps and scroll-spy highlighting.
- "[Pinned]" marker before the title of pinned articles.
- "Send Test Email" button on the mail settings page to verify the SMTP configuration with one click.
- Site settings adds "Category Tree Style": Book Tree (book icons replace ">" arrows, expandable, adapts to light/dark themes) vs Classic, switched via radio cards.

### Security

- `site_config.mail_password` encrypted at rest with Fernet (key derived from `SECRET_KEY`); it is never echoed back in the admin form.
- Backup/restore filenames validated with `werkzeug.safe_join` against path traversal (CodeQL path-injection).
- Forgot-password responds with a generic message regardless of match, preventing account enumeration.
- Fixed a login-route indentation bug: a wrong password could no longer establish an authenticated session; lockout message shows remaining attempts.
- Anti open redirect: the login `next` parameter only allows on-site relative paths, blocking `//evil.com` and backslash bypasses.
- Anti Host-header injection: new `BLOG_CANONICAL_URL` / `BLOG_TRUSTED_HOSTS` settings; absolute URLs no longer trust the request Host; nginx now sends CSP, X-Frame-Options, X-Content-Type-Options and Referrer-Policy headers.
- Production refuses to start without `BLOG_SECRET_KEY` (prevents random-key breakage of sessions and encrypted fields).
- Rate limiting by IP on comment / reply / like endpoints (database-backed, shared across workers); exceeded requests are told to retry in 5 minutes.
- MySQL restore hardening: dispose the connection pool before restore (removes MDL blocking that caused hangs and table loss), filter `LOCK TABLES` statements from dumps, a concurrency lock, and a post-restore integrity check (the `admin` table must exist and be non-empty).

### Changed & Fixed

- Category menus are now rendered from a single source `templates/blog/_macros.html` (navbar dropdown and sidebar tree share one template).
- Fixed unreadable archive year text in the article detail dark reading theme (tree colors now use CSS variables).
- Merged "Account Email" and "SMTP Mail Settings" into a single "Account & Mail Settings" page (old URL redirects); the two forms submit independently.
- Unified admin page widths (Site Settings / About Me / Account & Mail Settings match the article page) with right-aligned action buttons; widened the admin sidebar (clamp-based).
- The background gallery now uses an auto-fill grid so thumbnails no longer stretch; shorter English theme-switcher labels (BG 1…BG 10, Ink Wash, Lake View).
- Removed the "Log Out" button from the front-end navbar; logout lives in the admin sidebar only.
- SQLite backup now uses `VACUUM INTO` for a consistent snapshot; backup filenames use millisecond precision.
- MySQL restore no longer hangs the page: 120-second subprocess timeout + stderr capture with clear error messages.
- The backup page risk warning is now dismissible; after a SQLite restore a reminder asks the user to restart the service.
- Localized form error messages (`flash_form_errors`).
- Resilient session loading and error handling: database errors fall back to anonymous access and error-page failures render plain HTML instead of a site-wide 500.

### Config & Docs

- `.env.example` now documents every configuration item (mail, reverse proxy, reset-token TTL), commented out by default so each is opt-in.
- `.env.docker.example` and docker-compose now include the SMTP group (`BLOG_MAIL_*`) and `BLOG_RESET_TOKEN_MAX_AGE`; compose adds a `backups` volume and no longer exposes ports 5000/3306 by default.
- The database-restore page now shows a prominent risk warning.
- Chinese/English changelogs updated; i18n catalogs recompiled.

---

## [v1.3.1] - 2026-09-06

About Me page, clickable list like, public-site logout and toast contrast fixes on top of v1.3.0.

### Added

- Public “About Me” entry in the top navigation linking to a new standalone page (`/about`), managed from a dedicated backend page `/admin/about_setting` under *Site settings*: avatar (upload / URL / clear), bio, email, GitHub and personal-homepage links (protocol auto-prefixed with `https://`).
- Navbar “Log Out” button while logged in, so the session can be ended right from the public pages.
- `SiteConfig` columns for the About page content, with an idempotent `ALTER TABLE` migration for existing databases and matching MySQL `init.sql` updates.

### Changed & Fixed

- Article like on list pages (home / category) is now clickable: the vote is cast in place and returns to the same list page; the `next` parameter is validated against open redirects.
- List “View all comments” link restyled into plain “All comments” text (no default blue underline look).
- Success toasts (login success etc.) now use a green glass background with a clearly visible white close (X) button (removed the CSS filter that overrode Bootstrap’s `btn-close-white`).
- Chinese/English i18n catalogs updated with the new entries and recompiled.

### Testing, Docs & i18n

- New `test_about.py`, plus list-vote and nav-logout cases (**210 test functions**); READMEs and changelogs bumped to v1.3.1.

---

## [v1.3.0] - 2026-09-02

Admin panel redesign, full-site search, and RSS/Atom feeds.

### Added

- Redesigned admin backend: dedicated glassmorphism layout (`admin_base.html`) with a sticky left sidebar menu (site settings / article & category / banner / change password / logout) and glass content cards.
- New backend home `/admin/panel` (defaults to the site-settings view); login now lands in the backend directly; site-settings form extracted into a shared partial reused by the panel and the standalone page.
- Full-site article search (`/search`): keyword fuzzy match over title & body, pagination, dedicated results page.
- RSS 2.0 (`/rss`) and Atom (`/feed`) feeds built with `feedgen`, with RSS/Atom auto-discovery `<link>` tags and footer feed icons; feed timestamps use Asia/Shanghai time with a `tzdata` fallback for Windows/slim images.
- Category rename (articles follow automatically via `category_id`).
- Banner enable/disable (`is_active`) with an idempotent lightweight migration (`ALTER TABLE`) for existing databases.

### Changed & Fixed

- Theme styles adapted for the new search/admin pages; theme-switcher enhanced; stylesheet cache-busting stamp bumped.
- Post-edit sanitization changed to store raw content and sanitize with the nh3 whitelist at render time (XSS defense kept, formatting preserved).
- `Banner` model adds `is_active`; MySQL `init.sql` schema updated accordingly.
- New dependencies: `feedgen==1.0.0`, `tzdata==2026.3`.

### Testing, Docs & i18n

- Tests extended with new `test_feed.py` plus broader auth/banner/blog coverage (**≈200 test functions**).
- i18n message catalogs greatly expanded (en +146 / zh +137 lines) covering RSS, search and backend terms.
- READMEs, screenshots (incl. new Admin Panel shots EN/ZH), `.dockerignore` and ignore rules updated to v1.3.0; document version pinned in the final commit.

---

## [v1.2.0] - 2026-09-01

Glassmorphism UI + theme switcher + Python CI + full test suite, plus dozens of admin/blog feature and bug-fix commits on top of the v1.0.0 baseline.

### Added

- Glassmorphism transparent UI across the whole site (cards, tables, navbar, breadcrumbs, manage pages), with the known “solid white / opaque card” issues systematically fixed via high-specificity CSS overrides.
- Five dynamic animated backgrounds — Aurora / Starry / Flow / Bubbles / Classic — switchable from a floating palette button; choice remembered in `localStorage`.
- Built-in gallery of 12 HD 1920×1080 background images; custom backgrounds can be uploaded or set by URL in the admin panel.
- Theme switcher (`theme-switcher.js`), cursor particle effect (`cursor-effect.js`), Flash messages upgraded to Toast notifications (`flash-toast.js`), language toggle dropdown (`lang-toggle.js`).
- Navigation refactor with dropdowns: *Article management* (drafts / new article / recall) and *Banner management* (list / add / withdraw all).
- New manage page for published articles (`/article/manage`) with edit / recall / delete; articles can be recalled back to drafts (`/article/recall`); batch banner withdrawal (`/banner/withdraw_all`).
- Delete category feature (articles under it revert to “uncategorized”).
- Markdown article file import directly in the editor (front-end upload).
- Admin panel enhancements: Logo upload, background gallery management, richer site settings.

### Security, Fixes & Refactors

- Like/vote switched to atomic DB-side increments with a `UNIQUE(article_id, ip)` constraint.
- Drafts no longer accessible anonymously; login `next` redirect hardened against open redirects.
- Deleting articles/swapping images now cleans up old uploaded files; GIF animation frames preserved; `favicon_path` config takes effect.
- Removed hardcoded test `SECRET_KEY` that failed CI secret scanning.
- Docker deployment fixes: compose now mounts `static/uploads`, container TZ/timezone support, `ProxyFix` for real client IPs behind nginx.
- Project-wide line endings normalized to LF via `.gitattributes`.
- `ruff format` normalization across the codebase; pyright type-checking config added.

### Testing & CI/CD

- GitHub Actions CI pipeline: ruff + pytest matrix; `pip-audit` security scan; Docker image publish workflow; release & security workflows; Dependabot config.
- Full pytest suite tracked in version control and expanded to **177 tests** covering auth / blog / comments / banner / i18n / models / security / site / utils / UI-theme / smoke.

### Docs & i18n

- New `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT` (EN/ZH); READMEs updated to v1.2.0 with fresh screenshots.
- i18n entries expanded (zh ≈143 / en ≈149); stale `messages.pot` template and dev-only translation helper scripts removed.

---

## [v1.0.0] - 2026-08-15

The complete first release, covering everything from the initial commit to the ruff-normalized baseline . 

### Added

- Blog core: article publishing & editing with the EasyMDE Markdown editor, code highlighting (Prism), draft/publish workflow, article detail pages.
- In-editor image upload with automatic compression/rescaling via Pillow, plus anti-hotlinking rules in nginx.
- Comments with replies, IP-based like/vote on articles, category (栏目) management with sidebar filtering.
- Banner carousel with backend management (add/edit/delete/reorder, image upload).
- Admin backend: admin login, site settings, change-password, banner & article management.
- Chinese/English i18n (Flask-Babel): auto-detects browser language, manual switch via a topbar dropdown.

### Architecture & Security

- Refactored onto SQLAlchemy ORM with a layered module structure (`models` / `forms` / `utils` / `database`, app factory + Blueprints).
- Security hardening: CSRF protection on all write actions, nh3 HTML sanitization against stored XSS, login brute-force lockout (IP + username, 5 fails → 5 min), secure session config (HttpOnly / SameSite / Secure), upload validation (MIME whitelist, UUID names, size cap), `SECRET_KEY` from environment variables, DEBUG off by default.
- Performance optimizations and query improvements.
- Unified error handling with a generic `error.html`.

### Deployment

- Docker deployment support: production Dockerfile (python:3.11-slim + gunicorn, non-root, healthcheck), `docker-compose.yml` (web + db + nginx), nginx reverse proxy serving static assets, `.env.example` / `.env.docker.example` templates.
- Dual database support: SQLite (out of the box) and MySQL; WSGI entry (`wsgi.py`), gunicorn & uWSGI configurations.
- Full Chinese/English deployment documentation and screenshots.

---
