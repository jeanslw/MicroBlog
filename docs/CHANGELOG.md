# MicroBlog Changelog

## [1.3.0] - 2026-09-02

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

## [1.2.0] - 2026-09-01

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

## [1.0.0] - 2026-08-15

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
