# MicroBlog Changelog

## [v1.3.6] - 2026-10-10

Schema refactor: the single 20-column `site_config` row is split into three single-row tables by domain — `site_setting`, `mail_setting`, `about_profile` — with an automatic, idempotent startup migration that copies, verifies and only then drops the legacy table. Also ships the logging overhaul (configurable level, friendly-error switch, log rotation, container log volume) and removes a dead module.

### Changed

- **`site_config` split into three tables**: site identity/appearance (`site_setting`: name, favicon, logo, background, comments toggle, sidebar style), SMTP credentials (`mail_setting`), and the about-page profile (`about_profile`). Each table keeps the single-row (id=1) pattern, and the "the only row has id ≠ 1" legacy compatibility fixed in v1.3.5 carries over via a shared `_get_single_row` accessor. Beyond tidiness: the SMTP password no longer lives in a table that any template-rendering path reads — the front-end global context now loads only display fields plus the about nickname, and mail credentials are read exclusively by the mail sender.
- **Startup migration `_migrate_site_config_split`** (decision: drop the legacy table immediately). Copy + row-count verification run in one DML transaction; the legacy table is dropped only after all three new tables verify exactly one row (MySQL DDL implicitly commits, so verify-then-drop is the closest achievable to atomic there). On any failure the legacy table is left untouched and the migration retries on next boot — no data can be lost between copy and drop. Restoring an older backup (SQLite file swap / MySQL dump import) that resurrects `site_config` automatically re-runs the split: the restored row **overwrites** stale rows in the new tables, because a restore is an explicit user intent. Databases as old as v1.0 (table with only `site_name`/`favicon`) migrate too — missing columns take defaults, replacing the old per-column ALTER approach. New installs get the three tables from `MySQL/init.sql` (with `INSERT IGNORE` defaults) or `create_all` + `ensure_default_settings`.
- **Logging system upgrade**: new `BLOG_LOG_LEVEL` (auto/DEBUG/INFO/WARNING/ERROR/CRITICAL; `auto` follows DEBUG, invalid values fall back to INFO with a warning instead of blocking startup) now governs *what gets logged*, while `DEBUG` solely governs *what error pages show* — off means friendly HTML/JSON pages with the stacktrace confined to logs. Log files rotate via `RotatingFileHandler` (5 MB × 5 copies) with zero new dependencies, compatible with gunicorn multi-worker shared-append handles; docker-compose maps `./data/logs:/app/logs` so logs persist across container recreation.
- **Schema-version migration framework** (`schema_version` **history table** + `SCHEMA_VERSION` in code): migrations trigger when the program's schema version is **greater** than the database's recorded version — automatically at startup *and* manually from the new admin page. Versions are **real release numbers** (e.g. `1.3.6`), never opaque internal integers, so logs and the admin page show the release you actually run; comparison is semantic (`1.3.10` > `1.3.6` — plain lexicographic order would get this wrong). Each migration registers as (release, description, callable) and appends **one history row** (version PK + applied time + note) right after success, so a mid-run failure resumes without redoing completed steps; "current database version" is the semantically highest row, and the admin page renders the history as the audit trail. First-time adoption infers the initial version (legacy `site_config` table present → baseline `1.3.5`; fresh install → current); the site_config split is the framework's first registered migration (`1.3.6`). If the database is *ahead* of the code (downgraded binary), migrations are skipped with a warning instead of letting older code touch a newer schema. On MySQL the whole run holds a named lock (`GET_LOCK('microblog_schema_migration')`) so concurrent worker startups or a manual run racing an automatic one can never interleave DDL — a connection-level lock, it is released automatically if the process dies.
- **Maintenance gate + auto/manual migration mode** (`BLOG_AUTO_MIGRATE`): a schema-changing upgrade can break login itself, so with `false` the startup step touches **nothing** — it detects pending migrations and routes every request that is not an allowlisted endpoint (`static`, health probe, uploaded files, login/logout, the migrate page) to a standalone 503 upgrade page showing database/target version and the pending list. That page deliberately neither extends `base.html` nor queries any business table (nor `current_user`, which would hit `admin`), so it renders under any lagging schema. Only `admin`, `login_attempt` and `rate_limit` are declared **immutable across versions**, and login is the single entry point to migration. The gate re-checks pending migrations on every request and clears itself the moment any entry point finishes them (this worker, another worker or the CLI) — no restart needed.
- **New timestamps `banner.update_time` / `login_attempt.update_time`**: banner edits, withdraws and re-enables each stamp the time (so a withdrawn banner shows its "withdrawn at" in the list, with a new "last changed" column), and every failed sign-in refreshes its timestamp, feeding a new "Failed sign-in attempts" card on the admin account page (IP / account / fail count / last failure / locked state). Both columns come with idempotent startup `ALTER TABLE` migrations for legacy tables and are created directly by `MySQL/init.sql` on new installs.
- **New admin page "Migrate Database"** under the Ops & Security menu: shows current vs. target schema version, the pending-migration list, and a confirm-guarded button that runs the exact same entry point as startup. Page and flash texts added to both locales' .po/.mo.
- **Backup tolerates non-root MySQL accounts**: `mysqldump` flags that previously were hardcoded (`--no-tablespaces`) are now behavior-driven candidates like the TLS flags — `--single-transaction` already avoids the LOCK TABLES privilege, and the candidate chain adds `--no-tablespaces` (no PROCESS privilege needed) and `--set-gtid-purged=OFF` (restore side needs no SUPER for GTID). An old client that rejects a flag (pre-8.0.21 has no `--no-tablespaces`) falls back flag-by-flag — the stderr names the offending option, so only combos still containing it are skipped; privilege errors (access denied) are surfaced as-is without retries.

### Removed

- Dead module `app/banner/queries.py` (`get_all_banner`): zero callers — all three real consumers query inline — and semantically wrong, as it did not filter `is_active`, so wiring it back would have resurrected withdrawn banners.

### Tests

- **362** tests passing (+24): the split gets a dedicated migration suite (copy-and-drop with value assertions, idempotent re-run, old-backup restore overwriting stale new-table rows, v1.0 missing-column tolerance, legacy-table preservation on copy failure) plus single-row accessor tests for all three tables; the schema-version framework gets its own suite (fresh-db stamping, legacy detection and step-by-step migration, ahead-of-code guard, per-version history rows with timestamps and notes, integer-stamp normalisation, dev-era single-row table rebuild, `quiet` log suppression, startup auto vs. manual mode, error-tolerant startup step, maintenance gate allowlist/503/self-clear, end-to-end manual migration from the admin page, admin page status+history+manual badge); backup gains non-root flag-fallback and privilege-error tests, and the new timestamps are covered for banner withdraw/enable and failed sign-ins.

## [v1.3.5] - 2026-09-16

Ops & UI hardening: docker-compose pre-start guard, MySQL 8.4 upgrade with auth-plugin compatibility, configurable 24-hour session lifetime, mobile collapsed-navbar search layout, touch support fix for the theme switcher, nginx version hiding, plus admin comment management and breadcrumb group fixes.Security and correctness fixes: the session key no longer falls back to the repository's public default, SQLite restore now validates and atomically replaces the database file under a cross-process lock, site settings are read and written as a single row, and rate-limit cleanup is no longer rolled back.

### Added

- docker-compose pre-start guard `env-check` (profiles `mysql`/`full`): before `db` starts, a one-shot container verifies that `MySQL/init.sql` exists (prevents an empty bind-mount directory shadowing initialization) and that `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD` are neither the template placeholder (`请替换为强密码`) nor explicitly set to the public test defaults — any of these aborts startup with bilingual guidance. When both passwords are simply left unset (no `.env.docker` at all) the guard only emits a security warning and passes, reusing the built-in test passwords of the `db` service so that `--profile full up -d` still works out of the box locally instead of being silently blocked; it likewise warns when `BLOG_SECRET_KEY` is still the public test key. `db` depends on the guard completing successfully. Note that `up -d` does not print this one-shot container's output — inspect failures with `docker compose --profile full logs env-check`.
- Admin comment management: the published-article list gains a comment-count badge column and a "Comment Management" entry; `/comment/manage/<article id>` lists every comment and reply of that article with newest comments first and offers per-row deletion — deleting a comment cascades to its replies through the ORM, while a single reply can also be removed on its own; afterwards the admin returns to the same management page (or to the article list if the article no longer exists). Comments/replies are loaded with one comment query plus one reply query (`get_article_comments`) and the article list counts comments with a single `GROUP BY`, so there is no N+1; every route requires admin login and a CSRF token.
- Configurable session lifetime: `PERMANENT_SESSION_LIFETIME` is now driven by `BLOG_SESSION_LIFETIME` (seconds, default `86400` = 24 hours; previously hardcoded 12 hours). Exposed in docker-compose, `.env` examples and the deployment docs; covered by a new `test_session_lifetime_24h`.

### Security

- **Removed the public default session key**: docker-compose used to inject the `BLOG_SECRET_KEY` default that lives in the repository, which effectively meant "no key at all" — anyone with the repo could sign a valid cookie and impersonate the admin, and the existing "refuse to start without a key" check in `config.py` never fired because the variable *was* set. Now the web service injects no default; the container entrypoint generates a random 64-hex key on first boot (when none is given, or when the public default is passed) and persists it to `./data/.secret_key` on the host, handing it to the app via `BLOG_SECRET_KEY_FILE` (the secret never enters the environment, and sessions survive container recreation). `BLOG_SECRET_KEY_FILE` is now a supported config source, and production refuses to boot when it detects the public default key.
- **`safe_url` rejects pseudo-schemes**: inputs that already carry a scheme outside the allow-list (`javascript:`, `data:`, `ftp:` …) used to be treated as bare hosts and prefixed into `https://javascript:alert(1)` (a dead link with the pseudo-scheme stored in the database); they now return an empty string, and a resolvable hostname is required after prefixing.

### Changed & Fixed

- **SQLite restore can no longer corrupt the live database**: restore is now "write a temp file → validate it with a dedicated engine (`PRAGMA integrity_check` plus a non-empty `admin` table) → `os.replace` atomically → ask gunicorn to restart gracefully (SIGHUP) so every worker reopens the database file". Previously the live file was overwritten in place with `"wb"`, which under `gunicorn -w 4` readily produced `database disk image is malformed`, and a corrupt or empty backup was reported as a successful restore.
- **Restore mutual exclusion now spans processes**: a module-level `threading.Lock` only guards a single worker, so a `backups/.restore.lock` file lock (`O_CREAT|O_EXCL`, stale locks older than one hour can be taken over) was added — concurrent restores can no longer run truly in parallel.
- **Site settings read and written as one row**: new `database.get_site_config()` / `get_or_create_site_config()` used by the front end (global template context, about page, feeds, comment switch) and the admin pages (site settings, about, account/mail), fixing "saving settings in the admin panel has no effect on the front end" when the single config row has a primary key other than 1; `fetch_global_context` now reads the site fields with one query instead of eight.
- **Rate-limit rows stop growing forever**: the lazy cleanup of expired rows now commits on its own, so a rejected request still keeps the cleanup (the old `rollback()` threw it away as well); `rate_limit` gains an `(action, create_time)` index (`MySQL/init.sql`, the ORM model and an idempotent startup migration).
- **Search keywords are matched literally**: `search_articles` now uses `contains(..., autoescape=True)`, so `%` and `_` no longer act as wildcards, and keywords are capped by `SEARCH_KEYWORD_MAX_LEN = 100`.
- **`MySQL/init.sql` is idempotent**: tables use `CREATE TABLE IF NOT EXISTS` and seed data uses `INSERT IGNORE`, so re-running it against a live database no longer drops data (previous versions started with `DROP TABLE IF EXISTS`); `article.is_pinned` and `rate_limit.idx_action_time` were added.
- **Dead config removed**: `PERMANENT_SESSION_LIFETIME_DELTA` was never read by any code and is gone.
- MySQL image upgraded 8.0 → 8.4 (guard image kept in sync): the `--default-authentication-plugin=mysql_native_password` flag — removed in 8.4 — was dropped and replaced with `--mysql-native-password=ON`, so legacy accounts on pre-existing 8.0 data volumes keep authenticating after the in-place upgrade (note: 8.0 → 8.4 is one-way; do not downgrade afterwards). Verified on a fresh 8.4 volume: container healthy, app account TCP auth passes (8.4 default `caching_sha2_password` is fully supported by PyMySQL 1.2.0 + cryptography — no app change needed).
- Mobile collapsed navbar (<992px): the search row (search box + button + language switch) now renders at the **top** of the expanded menu, right-aligned with the search box capped at 210px — echoing the desktop top-right search position instead of spanning the full width under the category links. Desktop (≥992px) layout untouched.
- Theme switcher works on touch devices again: `onPointerDown` no longer calls `e.preventDefault()` on `touchstart` — on touch screens that suppresses the browser-synthesized `click`, so tapping the palette button did nothing (desktop was unaffected because `mousedown` default-prevention does not block `click`). Scroll-blocking during drags is already handled by CSS `touch-action: none`; mouse/touch dragging and position memory are unchanged. Cache stamp bumped to `?v=20260916a`.
- Admin breadcrumbs now carry their parent sidebar group: drafts, new/edit article and the article list live under "Article Management"; change password and account mail settings under "Account Security" (the latter was previously misparented under "Site Settings"); database backup under "Operations & Security" (also previously under "Site Settings"). Groups that have no landing page render as plain, non-clickable text so no dead links appear.
- nginx config hides the version number: `server_tokens off` at the http level — the `Server` response header and default error pages now show plain `nginx` without the version, effective for both the HTTP(80) server and the commented HTTPS(443) template.
- Database backup/restore no longer trips over client versions: `--skip-ssl` (added for the MariaDB client inside the image) **was removed from MySQL 8.4's `mysqldump`**, so bare-metal runs with an 8.4 client failed the backup instantly with exit code 2 (`unknown option`) and without ever connecting. The app now works **behaviour-driven** instead: it first runs with `--skip-ssl`, and if the client reports an unknown option it automatically retries with `--ssl-mode=DISABLED` (an unknown option fails during parsing, so nothing connects and nothing is written), finally dropping the flag to keep the client default; whichever spelling worked is cached and shared by both the backup and restore paths. `--version` probing is deliberately not used: `mysql --skip-ssl --version` prints the version and exits 0 (that client returns early on `--version` without validating the remaining options) while `mysqldump` does report the error — the same flag is validated at different moments in the two clients, so the probe cannot be trusted; subprocess calls also dropped `check=True`, so a failure surfaces the client's raw stderr (unknown option / bad password / missing privileges) on the page instead of a bare exit code, plus a readable message when the client binary is absent. EN/CN FAQs gained the matching troubleshooting entry.
- Rendering fallback for the "database-only restore" trap: uploaded files (logo, avatar, custom background, images embedded in articles) are not part of a database backup, so after restoring onto another machine the URLs in the database point at missing files and the browser paints the broken image together with its `alt` text — the navbar logo's `alt` is the site name, which is why the page read "My Blog My Blog" as if the site name were stored twice (the classic symptom after restoring a Windows backup into a Linux container). Rendering now checks that on-site static assets exist (new `app.utils.static_url_exists`; external http(s) URLs are still left to the browser): a missing logo/avatar falls back to the built-in icon and placeholder avatar, so no broken images or duplicated text appear, and the database URL is left untouched so display recovers as soon as the file is back. EN/CN FAQs gained a "backups contain the database only — copy `static/uploads/` for a full migration" entry with the commands.

### Tests & Docs

- **270** tests passing (24 added here: 8 covering the comment-management delete flows, 1 for the new i18n entries, 12 for backup/restore client-flag fallback and stderr surfacing, and 3 for the missing-upload rendering fallback). Changelog and FAQ updated in both languages, and both READMEs document the new "Article List" / "Comment Management" admin URLs.
- 30 new regression tests: `test_secret_key.py` (including a case that executes the entrypoint's key block for real, covering generate / reuse / honour explicit value / ignore public default), `test_restore_lock.py` (lock contention, stale-lock takeover, corrupt backups never touching the live database), `test_site_config.py`, `test_rate_limit_cleanup.py`, `test_search_escape.py`, plus stricter `safe_url` assertions in `test_security.py` (301 → 331 passing, ruff clean).
- Updated the session-key documentation across both READMEs, both deployment guides, both FAQs, `.env.docker.example` and the docker-compose comments.

### CI & Tooling

- **All GitHub Actions pinned to full commit SHAs**: every `uses:` across the five workflows (ci / security / release / docker-publish / the new codeql) now pins the immutable SHA with the version kept as a trailing comment, following GitHub's official supply-chain guidance — a floating tag can be force-pushed or hijacked upstream, a SHA cannot. `codecov-action` was bumped from the lagging `v7` floating tag to v7.1.1 in the process; all nine SHAs were resolved and double-checked against their release tags via the GitHub API / `git ls-remote`.
- **New CodeQL workflow** (`.github/workflows/codeql.yml`): Python, advanced setup, `build-mode: none`, SARIF uploaded to the repository Security tab; runs on PRs, pushes to main, and a weekly cron shifted off the hour (`23 17 * * 1`) to avoid Actions queue peaks. No false-positive exclusions were needed — if one is ever added it must state the reason inline.
- **CI quality job extended**: added `mypy` type checking (config in repo-root `mypy.ini`, version pinned at 1.13.0), `ruff format --check` as a format gate, and `pip check` for dependency-consistency validation; `ruff check` / `format` / `compileall` now also cover `wsgi.py`, the production gunicorn entrypoint that was previously unchecked. mypy was chosen over putting pyright in CI because pyright produces ~170 `Column[T]` interop false positives on legacy Flask-SQLAlchemy models (pyrightconfig.json keeps serving the IDE). Two caveats documented in `mypy.ini` itself: comments must stay ASCII-only (configparser decodes with the locale encoding, so UTF-8 Chinese comments crash mypy with a GBK UnicodeDecodeError on zh-CN Windows), and per-module overrides in ini files use `[mypy-<pattern>]` sections, not the pyproject.toml-only `[[mypy.overrides]]` syntax.
- **pip-audit is no longer decorative**: the step's `continue-on-error: true` meant no vulnerability could ever fail the job. It now warns-only on PRs (a newly disclosed third-party CVE should not block unrelated contributors) and hard-fails on pushes to main and the scheduled run; the version is pinned at `pip-audit==2.10.1`.
- **Credential scan matches real token formats**: the old `(secret|password|token)=...` regex was broad enough to flag sample values in tests; it now matches genuine formats only (`glpat-`, `ghp_`, `github_pat_`, `AKIA…`, `xox…`, PEM private-key headers), scans more file types (js/json/sql/sh/ini/cfg), and excludes `.venv` / `static` / `.github` / `*.example`. Zero false positives against the current tree.
- **Formatting baseline**: `ruff format` was run once over the tree (14 files, formatting only, no behaviour change) so the new `format --check` gate starts green; 6 small type-annotation fixes accompany it (`reply_map` / `_tls_args_cache` explicit annotations, `Column[str]` boundary `type: ignore`s, a ProxyFix `method-assign` exemption and a `tzinfo` annotation — each with an explanatory comment), reaching a zero-error mypy baseline across 24 source files. Test count is unchanged at 331.
- **New config files**: `.coveragerc` (coverage counts `app/` only — tests and caches excluded, `pragma: no cover` supported) and `.editorconfig` (LF in line with `.gitattributes`, CRLF preserved for bat/ps1, Markdown trailing spaces kept); `.gitignore` gained `/.mypy_cache/`.
- **Pinned the one unpinned core dependency**: `SQLAlchemy` is a transitive dependency of Flask-SQLAlchemy (constraint `>=1.4.18`, no upper bound) and was the only runtime-critical package missing from the otherwise fully pinned `requirements.txt`. The first CI run of the mypy gate silently installed the newly released SQLAlchemy 2.1, whose far stricter typing inference (`TypedReturnsRows`, bare legacy `Column` attributes inferred as `Never`) produced 18 errors — while the local baseline on 2.0.51 was clean, so the gate failed only in CI. `SQLAlchemy==2.0.51` is now pinned, aligning CI, local dev and the production Docker image (whose builds had been drifting the same way: tests ran against 2.0.51 while images installed whatever was newest). Migrating to the stricter 2.1 typing belongs with a future move to annotated `Mapped[]` models, not with a CI fix.
- **First pip-audit hard-fail exercised the new policy — 4 packages upgraded**: the audit that used to be decorative immediately caught 47 advisories across `cryptography` 43.0.1 / `python-dotenv` 1.2.1 / `Pillow` 10.4.0 / `pytest` 8.3.3. All are now upgraded to their highest fix versions (`cryptography 50.0.0` — including PYSEC-2026-3552, disclosed *during* this fix and found by re-running the audit locally rather than trusting the CI list, `python-dotenv 1.2.2`, `Pillow 12.3.0`, `pytest 9.0.3`); every target still supports Python 3.10, the CI matrix floor. Compatibility verified before upgrading: `crypto.py` uses only the rock-stable `Fernet` API, `utils.py` already uses modern Pillow APIs (`Image.Resampling.LANCZOS`, nothing removed in 10→12), and `pytest-cov 5.0.0` only requires `pytest>=4.6`. Full suite (338 tests), mypy, ruff and `pip check` all green; `pip-audit -r requirements.txt` now reports zero known vulnerabilities.

---

## [v1.3.4] - 2026-09-12

Security responsibility migration: response headers / caching / hotlink protection moved from nginx config into the application layer; nginx is now plain proxying.

### Changed & Fixed

- Security headers are now issued by the application layer (`app/__init__.py` `after_request`): CSP (including `media-src 'self' https:` required for external audio/video), `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, and HSTS over HTTPS. The CSP policy is a config item (`CSP_POLICY`). Protection now lives in version control with test coverage, identical across nginx / direct / Docker deployments.
- Hotlink protection moved into the app (`before_request`): `/static/banner/` and `/static/uploads/` allow empty Referer, same-origin, and Host-allowlisted referrers; everything else gets 403, matching the previous nginx `valid_referers` behavior. With no allowlist configured, only same-origin passes.
- Static asset caching moved into the app: when `BLOG_STATIC_MAX_AGE > 0`, static responses carry `Cache-Control: public, max-age=N, immutable` (compose template defaults to 43200); dev default 0 means no caching.
- nginx config reduced to plain proxying: removed `add_header` security headers, static-file locations, and `client_max_body_size` (request size is enforced by the app's `MAX_CONTENT_LENGTH` = 16MB). ⚠️ Never re-add CSP via nginx — browsers intersect multiple CSP headers.
- Clarified first-install messaging: with `BLOG_INIT_ADMIN_PWD` unset, the startup log is now an informational note (previously a misleading warning saying "set it and restart") — leaving it empty is a normal path; visiting any admin route redirects to the `/admin/setup` wizard. The wizard commit now also handles the multi-worker IntegrityError race (graceful redirect to login instead of a 500 when another process created the admin first).

### Tests & Docs

- New `tests/test_security_headers.py` with 13 tests: full header assertions (including a `media-src` regression guard), headers on error responses, HSTS absent on HTTP / present on HTTPS, static cache toggle, and five hotlink scenarios; new `tests/test_setup.py` with 8 tests: admin-route redirects to the wizard when no admin exists, account creation with auto-login, password validation, wizard disabled once an admin exists, and the concurrent-creation race; **240** tests passing in total.
- Deployment docs (EN/CN) updated to reflect the new ownership of headers/caching/hotlink protection.

---

## [v1.3.3] - 2026-09-12

Docker Compose out-of-the-box overhaul, container health probe and database readiness wait, plus a fix for login failures behind an nginx reverse proxy.

### Added

- Health probe `GET /healthz`: the app runs `SELECT 1` to verify database connectivity, returning `{"status":"ok"}` (200) on success or 503 (with rollback) on failure. The path is exempt from the Host allowlist so container health checks and load-balancer probes work.
- MySQL readiness wait on app startup (`wait_for_database`): MySQL mode only — probes every 3s for up to 90s; SQLite passes immediately. gunicorn / waitress direct deployments benefit too, eliminating skipped table creation/initialization caused by slow MySQL first boot.
- New image entrypoint `docker-entrypoint.sh`: starts as root, fixes ownership of bind-mounted directories (`data`, `static/banner`, `static/uploads`, `backups`), then drops privileges to appuser via gosu — resolves Permission denied on native Linux Docker mounts.
- waitress 3.0.2 added as a dependency: on Windows run `waitress-serve --listen=127.0.0.1:5000 wsgi:application` (gunicorn relies on fork and doesn't support Windows).

### Changed & Fixed

- Out-of-the-box docker-compose: test-only built-in defaults are provided for `BLOG_SECRET_KEY` and database passwords — after copying `.env.docker.example`, **only `MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD` must be filled in**. SQLite mode `docker compose up -d web` needs zero configuration and no env file.
- Readiness ordering: web `depends_on` the db health check (`required: false`, automatically ignored in SQLite mode; requires Docker Compose v2.20+), and nginx only routes traffic after web is healthy. The db and image HEALTHCHECKs use `mysqladmin ping` / `/healthz`.
- Fixed login failure / redirect loop behind nginx: the bundled nginx serves plain HTTP (port 80) only, so compose defaults `BLOG_COOKIE_SECURE=false`; set it to `true` after enabling HTTPS. Compose also preconfigures `BLOG_PROXY_XFOR=1`, `BLOG_PROXY_XPROTO=1`, `BLOG_PROXY_XHOST=0`.
- Fixed the nginx `/healthz` proxy: a trailing slash in `proxy_pass` rewrote the path to `/`; also added the forwarded `Host` header.
- Renamed the Host allowlist config key from `TRUSTED_HOSTS` to `HOST_WHITELIST`: Flask 3.1 natively consumes `TRUSTED_HOSTS` and rejects requests with 400 during request context (before `before_request`), making a per-path probe exemption impossible. The environment variable name `BLOG_TRUSTED_HOSTS` is unchanged.
- The web port is now published to host loopback only (`127.0.0.1:5000`, override with `WEB_PORT`); MySQL 3306 is not published by default.
- nginx ships with a complete, fully-commented HTTPS (443) template: TLS 1.2/1.3, modern cipher suites, session caching, HSTS, the same security headers/hotlink-protection locations as port 80, and an 80→443 301 redirect switch. docker-compose also includes commented-out entries for the 443 port and a read-only `./nginx/certs` mount, and `.gitignore` excludes the certs directory. Enabling HTTPS is just: drop in certificates, uncomment, set `BLOG_COOKIE_SECURE=true` — no config writing required.
- Vendored Font Awesome 4.7.0 locally: EasyMDE dynamically injects the Font Awesome stylesheet from the `maxcdn.bootstrapcdn.com` CDN at runtime, which the site CSP (`style-src 'self'`) blocks behind nginx, leaving editor toolbar icons as blank boxes. The CSS plus 5 webfont files are now bundled under `static/lib/` (font `url()` paths rewritten to `./fonts/`), the edit page links the local stylesheet with a `?v=4.7.0` cache-busting query, and EasyMDE initializes with `autoDownloadFontAwesome: false` — zero third-party CDN requests and fully offline-capable.

### Tests & Docs

- New `tests/test_health.py` with 5 tests: probe 200/503, probe exempt from the Host allowlist, MySQL retry-until-ready, SQLite skip-wait. **219 tests** pass in total.
- Both READMEs gain a "Quick Start" section (three Docker Compose profiles + local gunicorn/waitress); the deployment guide documents health checks/startup order/directory permissions, and the FAQ adds entries for reverse-proxy login failure, Host allowlist 400, probe 503, mount permissions, and waitress on Windows.

---

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
