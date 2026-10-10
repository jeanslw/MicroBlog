# Admin Guide

For **administrators of a self-hosted MicroBlog**: where the admin panel lives, what each page does, day-to-day operations (backup / restore / schema migration), account security and troubleshooting.

- First-time deployment, environment variables, HTTPS and Docker: see [Deployment](DEPLOYMENT.md);
- Error messages: see [FAQ](FAQ.md);
- Code structure for developers: see [Project Architecture](ARCHITECTURE.md).

> This guide describes the **admin UI**. Every write goes through a validated form with a CSRF token; the UI language follows `BLOG_LOCALE` and the language switcher in the header.

---

## 1. Quick Navigation

| I want to… | Where |
|------------|-------|
| Sign in | `/admin/login` (or "Admin" in the site header) |
| Create the first administrator | With no admin in the database, any admin URL redirects to `/admin/setup` |
| Change site name / logo / background / category style / comments | Admin "Site Settings" (`/admin/site_setting`; the panel home `/admin/panel` is the same form) |
| Write an article / manage drafts | Admin "Articles → New Article / Drafts / Article List" |
| Moderate comments & replies | "Article List → Comments (per article)" |
| Create / rename / delete categories | **Front-end** sidebar "Categories" (visible once you are signed in) |
| Manage banners | Admin "Banners → Banner List" (`/banner/`) |
| Edit the "About" page | Admin "About Me" (`/admin/about_setting`) |
| Change password / bind email / configure SMTP | Admin "Account → Change Password / Account & Mail Settings" |
| Back up, download or restore the database | Admin "Operations & Security → Database Backup" (`/admin/backup`) |
| Migrate the database after an upgrade, check versions | Admin "Operations & Security → Migrate Database" (`/admin/migrate`) |
| The site suddenly returns 503 "maintenance" | See [§9 Upgrading and Schema Migrations](#9-upgrading-and-schema-migrations) |

---

## 2. Sign-in and Account

### 2.1 First-time setup: create the administrator

When the `admin` table is empty, `/admin/login`, `/admin/panel` and friends **redirect** to `/admin/setup`:

- Fill in username, email (optional, used for password recovery — can be added later) and password (6–128 chars) twice;
- Submitting creates the administrator and redirects you to the sign-in page.

You can also create it from the command line / environment instead:

```bash
# Option 1: created automatically at startup (only when the admin table is empty)
# app.env: BLOG_INIT_ADMIN_USER=admin (default), BLOG_INIT_ADMIN_PWD=your-strong-password

# Option 2: interactive command (idempotent — skipped if the account already exists)
flask create-admin
```

> After bootstrapping, **remove `BLOG_INIT_ADMIN_PWD`** so it does not linger in your config file.

### 2.2 Sign in and sign out

- Sign-in: `/admin/login`. On success you are sent back to the **same-site relative path** in `?next=` (for example back to the migration page when you came from the maintenance page); `next` only accepts same-site paths, which prevents open redirects.
- Sessions: a permanent session is used, valid for **24 hours** by default (`BLOG_SESSION_LIFETIME`, in seconds). In production the cookie carries `Secure` (`BLOG_COOKIE_SECURE=true`), `HttpOnly` and `SameSite=Lax`.
- Sign-out: "Sign out" in the admin menu (POST + CSRF) clears the whole session.

### 2.3 Login lockout (brute-force protection)

- Counted per **IP + username**; after **5** consecutive failures the pair is locked for **5 minutes**; while locked, sign-in returns `429` together with the remaining seconds.
- The counter is persisted in the `login_attempt` table (shared across workers, survives restarts) and is **cleared on a successful sign-in**.
- Where to look: bottom of Admin "Account → Account & Mail Settings" — the last 10 entries (IP / attempts / last failure / status: locked or normal).
- If you locked yourself out, wait 5 minutes, or clear the matching rows yourself (`DELETE FROM login_attempt`).

### 2.4 Forgot password (email recovery)

1. On `/admin/forgot`, enter **username + bound email** (both must match the stored record);
2. The app sends an email containing a one-time token; the link points to `/admin/reset/<token>`;
3. The token is valid for **30 minutes** (`BLOG_RESET_TOKEN_MAX_AGE`) and **expires immediately once the password changes** (the payload is bound to the current password hash, so it is inherently single-use).

Security behaviour worth knowing when debugging:

- Whether or not the account exists, and whether or not the mail was sent, the page shows exactly the same message — to prevent account enumeration;
- The recovery endpoint is rate-limited per IP: **5 requests / 5 minutes**;
- It depends on SMTP: without SMTP configured no mail arrives — reset the password from the CLI instead (§8.3).

### 2.5 Change password

Admin "Account → Change Password"; the current password is required and the new one must be 6–128 characters. A successful change **signs you out everywhere** (other devices' sessions are invalidated too) — sign in again with the new password.

---

## 3. Admin Menu Overview

The sidebar (a drawer on narrow screens) has four groups:

| Group | Item | URL | Purpose |
|-------|------|-----|---------|
| (top) | Site Settings | `/admin/site_setting` | Site name, logo, background, category style, comment switch; `/admin/panel` is the same form |
| (top) | About Me | `/admin/about_setting` | Content of the front-end "About" page |
| Articles | Drafts | `/drafts` | Unpublished articles |
| Articles | New Article | `/article/new` | Markdown editor |
| Articles | Article List | `/article/manage` | Pin / edit / withdraw / delete published articles + comment moderation entry |
| Banners | Banner List | `/banner/` | Add, edit, withdraw/enable, delete |
| Banners | New Banner | `/banner/` (form on the page) | Upload image + title / link / description / sort weight |
| Account | Change Password | `/admin/change_pwd` | Change the login password |
| Account | Account & Mail Settings | `/admin/account` | Account email, SMTP, send test mail, login-failure log |
| Account | Sign out | `/admin/logout` | POST sign-out |
| Operations & Security | Database Backup | `/admin/backup` | Back up now / download / restore / delete |
| Operations & Security | Migrate Database | `/admin/migrate` | Version status, run migration, migration history |

> Category management is **not** in the admin menu — it lives in the **front-end sidebar** (see [§6.5](#65-categories-front-end-sidebar)), because categories belong to the blog structure; signed-in administrators simply get extra edit buttons on the front end.

---

## 4. Site Settings

One form on Admin "Site Settings" (or the panel home); changes take effect immediately:

| Field | Notes |
|-------|-------|
| Site name | Up to 100 characters; shown in the navbar, page titles and footer |
| Site logo | jpg/jpeg/png/webp, ≤2MB; downscaled on upload so the longest edge is at most 400px; leave empty for the default icon |
| Background style | Built-in gallery (background 1–10, `vdysjx`, `bg13`) + "Custom image" + "Classic" |
| Custom background image | Either an image URL (`/uploads/image/backgrounds/xxx.jpg` or `http(s)://...`) or a direct upload (resized to 1920px wide) |
| Category style | **Book tree** (expandable book icon, auto light/dark on article pages) or **Classic** (plain collapse arrows) |
| Comments | Turning "Enable comments" off blocks **all new comments and replies site-wide** (existing comments stay visible) |

How the two background layers interact:

- The admin setting is the **default**, emitted on `<body data-bg="…">`;
- Visitors can switch the style on the page; the choice is stored in the browser's `localStorage` (key `blog-bg-style`) and **overrides** the site default — for that visitor's browser only;
- To send a visitor back to the site default, clear their local storage.

The data lives in the single-row `site_setting` table (split out of the old `site_config` table in v1.3.6 — see [§9](#9-upgrading-and-schema-migrations)).

---

## 5. About Me

Admin "About Me" maintains the front-end `/about` page:

| Field | Limit |
|-------|-------|
| Avatar | Upload jpg/jpeg/png/webp (≤2MB, longest edge scaled to 512px), an external URL, or tick "Clear current avatar" |
| Nickname | ≤100 characters; shown on article pages and the About page |
| Email | ≤200 characters, must be a valid address |
| GitHub link / Homepage | ≤200 characters each |
| Bio | ≤2000 characters, multi-line (line breaks preserved) |

> Avatar precedence: **uploaded file > external URL > clear > keep unchanged**. External URLs are echoed back into the input; internal paths produced by uploads are not (so a working path cannot be silently replaced by a broken one).
> "View on the site" at the top right jumps straight to `/about`.

Data lives in the single-row `about_profile` table.

---

## 6. Content Management

### 6.1 New / edit article

Admin "Articles → New Article" (`/article/new`); editing starts from the article list or drafts:

| Field | Notes |
|-------|-------|
| Title | Required, ≤500 characters |
| Category | Optional ("Uncategorised"); maintained in the [front-end sidebar](#65-categories-front-end-sidebar) |
| Body | Markdown editor (toolbar for code blocks, bold/italic, links, images); required |
| Upload Markdown | Import a `.md` / `.markdown` file (≤2MB) into the body — this **replaces** the current body |
| Upload image | jpg/jpeg/png/gif, ≤10MB; inserted at the cursor (stored locally, no CDN) |
| Insert media | Images / audio and other media types |
| SEO description | ≤300 characters; auto-generated from the body when left empty |
| SEO keywords | ≤300 characters, comma-separated; auto-derived from category/title when empty |
| Save mode | "Save as draft (admin only)" or "Publish (visible to everyone)" |

- The editor **auto-saves drafts** so an accidental tab close does not lose your work;
- A live preview pane is available next to the editor.

### 6.2 Article list

Admin "Articles → Article List" (`/article/manage`):

- Columns: title, category, updated at, comment count, actions;
- Actions:
  - **Pin / unpin** (pinned articles sort first on the home and list pages);
  - **Edit** (opens the editor);
  - **Withdraw** (moves a published article back to drafts so it disappears from the site);
  - **Delete** (irreversible);
  - **Comments** (opens moderation for that article).

### 6.3 Drafts

Admin "Articles → Drafts" (`/drafts`) lists every unpublished article; you can edit or delete them (deletion asks for confirmation). Drafts are invisible to visitors and search engines.

### 6.4 Comments and replies

Reached from the article list via "Comments" (`/comment/manage/<article id>`):

- Shows all comments and replies for that article (with counts); links back to the article or the list;
- **Deleting a comment also deletes all of its replies** (the UI says so explicitly);
- Individual replies can be deleted on their own.

Visitors are additionally throttled per IP (table `rate_limit`): **comments/replies 10 per 5 minutes**, **likes 20 per 5 minutes**.

### 6.5 Categories (front-end sidebar)

Category management lives in the **front-end right sidebar** (home, list and article pages share the same sidebar):

- Once signed in, each category in the "Categories" tree gets rename/delete buttons:
  - **Rename**: prompts for a new name (≤60 characters);
  - **Delete**: confirmation required — **articles in that category become "Uncategorised"** (they are not deleted);
- The "New category" form at the bottom of the sidebar takes a name (required, ≤60) and an optional tag (≤60);
- The tree shows each category's article titles (collapsible) and counts; renames/deletions take effect immediately.

> Categories live in the `category` table; the tag is the badge shown on the category page.

---

## 7. Banner Management

Admin "Banners → Banner List" (`/banner/`), also reachable from the home-page carousel:

| Field | Notes |
|-------|-------|
| Image | jpg/jpeg/png/gif, ≤10MB; resized to 1920px wide on upload (leaving it empty while editing keeps the current image) |
| Title | ≤100 characters |
| Link URL | ≤500 characters; empty means the slide is not clickable |
| Description | ≤200 characters |
| Sort weight | Integer, **higher sorts first** |

Columns and actions:

- Columns: preview, title, link, sort weight, status, **last change**, actions;
- **Status**: `Active` / `Withdrawn`;
- Actions:
  - **Edit** (replace image / text / weight);
  - **Withdraw**: the slide disappears from the home page and can be **re-enabled** at any time (the withdrawal time is recorded in the "last change" column);
  - **Delete** (confirmation required, irreversible);
- Only `Active` banners appear on the home page; "last change" shows when the banner last changed (the `banner.update_time` column added in v1.3.6).

---

## 8. Account and Operations

### 8.1 Account & mail settings (`/admin/account`)

One form covering three things:

1. **Account email**: used for password recovery — make sure it receives mail (≤200 chars, must be valid);
2. **SMTP settings** (used to send recovery mails):
   - SMTP host, port (1–65535, default 587), username, password/app password, sender address;
   - **Leaving the password field empty keeps the existing password** (so you do not have to retype it on every save);
   - Enable either "STARTTLS (port 587)" or "SSL (port 465)" as your provider requires;
   - "Send test mail" sends to the **account email above** to validate the configuration;
   - **Precedence**: the SMTP settings saved here **override** `BLOG_MAIL_*` from `app.env` (a non-empty `mail_setting.mail_host` counts as configured);
3. **Login-failure log**: the last 10 entries (see [§2.3](#23-login-lockout-brute-force-protection)).

### 8.2 Database backup and restore (`/admin/backup`)

- **Back up now** creates a snapshot of the current database and lists it below (file name / size / time);
- Per row: **download**, **restore**, **delete**;
- Backup files are kept in the `backups/` directory of the project root;
- The active database type is shown on the page (the Docker image bundles `mysqldump`/`mysql`, so backup and restore work out of the box).

> **Restore is destructive**: it **overwrites all current data** with the backup and cannot be undone. The UI warns you and asks you to back up first; the app also **takes an automatic backup of the current data** before restoring. Do not use the admin panel or write data while a restore runs (in-process + cross-process file locks guard against concurrency).
>
> **SQLite caveat**: after a restore you **must restart the service** (gunicorn/uwsgi), otherwise other workers may still hold the old database file.

### 8.3 CLI fallback

Run these from the project root (activate the virtualenv and make sure `app.env` is set up):

| Command | Purpose |
|---------|---------|
| `flask init-db` | Create tables + apply pending schema migrations + ensure default settings/admin (**idempotent**, safe to re-run) |
| `flask create-admin` | Interactively create an administrator (skipped when the account exists) |

If you forgot the password and email/SMTP is unavailable, the quickest route is:

```bash
# 1) Make sure the schema is current (idempotent)
flask init-db
# 2) Interactively create/confirm an admin account (if the forgotten account exists, change its
#    password via a database client or create a second account instead)
flask create-admin
```

### 8.4 Logs and health check

- Application logs go to `logs/app.log` (10MB × 5 rotations by default, tunable via `BLOG_LOG_*`) and to the console;
- In production logs are **structured JSON** (parseable by ELK/Loki) and each request carries an `X-Request-ID` for tracing;
- Slow requests (`BLOG_SLOW_REQUEST_MS`, default 500ms) and slow queries (`BLOG_SLOW_QUERY_MS`, default 200ms) are logged as warnings;
- `GET /healthz` — **available even in maintenance mode**, ideal for load balancers and probes.

---

## 9. Upgrading and Schema Migrations

Since v1.3.6 the app records the database **schema version inside the database** (the `schema_version` history table); after upgrading the code, the "Migrate Database" page or the startup path brings the two into line.

### 9.1 Version comparison and trigger rules

| Program vs database version | Behaviour |
|-----------------------------|-----------|
| Program **>** database | Pending migrations exist → auto mode applies them immediately; manual mode enters maintenance until an admin runs them |
| Equal | Nothing to do |
| Program **<** database (code rolled back) | **Log a warning and skip** — older code is never allowed to touch a newer schema |

### 9.2 The two modes (`BLOG_AUTO_MIGRATE`)

| Mode | Config | Behaviour after an upgrade |
|------|--------|----------------------------|
| Auto (default) | unset, or `BLOG_AUTO_MIGRATE=true` | Migrations run at startup; the site serves normally |
| Manual | `BLOG_AUTO_MIGRATE=false` | Startup **does not touch the database**; once pending migrations are detected the whole site returns **HTTP 503** with the upgrade page (`/admin/upgrade_required`) — only static assets, `/healthz`, uploaded files, admin login/logout and the migration page remain reachable |

### 9.3 Recovering in manual mode

1. **Back up first**: the admin "Database Backup" page is **not on the maintenance allow-list** (it returns 503), so make sure you backed up **before** the upgrade; if you are already in maintenance mode, take a manual backup on the server (copy `data/blog.db` for SQLite, `mysqldump` for MySQL).
2. Open `/admin/login?next=/admin/migrate` and sign in (sign-in is **always** available in maintenance mode).
3. Open **Operations & Security → Migrate Database**; the page shows the database version, the target version and the pending migration list.
4. Click "Run migration" (a confirmation is required).
5. The maintenance page disappears by itself — the gate **re-checks on every request**, so as soon as the database version catches up (no matter whether this worker, another worker or the CLI did the work) everyone is let through, **no restart needed**.

### 9.4 The states of the "Migrate Database" page

| Message | Meaning | What to do |
|---------|---------|-----------|
| Green "schema version is up to date" | Database version == program version | Nothing |
| Amber "pending database migrations detected" | Migrations to run, with target version and notes | Back up, then "Run migration" |
| Amber "database version is behind, but no applicable migration is registered in the program" | Incomplete deployment / a release gap | **Verify a complete deployment of the new version** (do not hand-edit the schema) |
| Red "database version is higher than the program version" | The database is newer: you are running old code | Upgrade the code first (the migration was skipped) |
| Red "unable to read the database version" | Connection/privilege problem | Check the database connection and account privileges, then retry |

The "Migration history" table below lists each applied version with its timestamp and note (from `schema_version`).

### 9.5 Guarantees (why it is built this way)

- **Failures are not stamped**: if a migration raises, the framework does **not** mark the version as applied — the next startup or manual run **retries it automatically**, so there is no silent "version bumped but data not migrated" state;
- **Concurrency-safe**: on MySQL a named lock (`GET_LOCK`) serialises migrations — one worker applies while the others time out, log a warning and skip; SQLite is single-process and needs no lock;
- **Migrations are idempotent**: each migration can be re-run (e.g. once the `site_config` split has finished the old table is gone, so re-running is a no-op);
- **One entry point**: startup auto-migration, the admin migration page and `flask init-db` all call the same `run_schema_migrations`, so behaviour is identical;
- **No automatic downgrade**: the framework only brings **older databases** forward. To go back a version, restore the pre-upgrade backup (see [§8.2](#82-database-backup-and-restore-adminbackup)).

### 9.6 Why sign-in still works in maintenance mode

In maintenance mode the database may still lack columns/tables the new version expects, so **only three tables keep their structure across versions** (`admin`, `login_attempt`, `rate_limit`) and sign-in is the single entry point to the migration. That is also the answer when the maintenance page "will not let you in": make sure you use `/admin/login`, not any front-end page.

For the deployment-side detail (MySQL/SQLite differences, rollback notes, backup advice) see [Deployment §2.8 Upgrading and Schema Migrations](DEPLOYMENT.md#28-upgrading-and-schema-migrations).

---

## 10. Environment Variables Affecting the Admin Experience

The variables below shape the admin experience (for the full list with defaults see the [Deployment](DEPLOYMENT.md) variable table):

| Variable | Default | Effect |
|----------|---------|--------|
| `BLOG_AUTO_MIGRATE` | `true` | Auto vs manual migration mode (see [§9.2](#92-the-two-modes-blog_auto_migrate)) |
| `BLOG_INIT_ADMIN_USER` / `BLOG_INIT_ADMIN_PWD` | `admin` / empty | Creates an admin when the database is empty (drop the password entry after bootstrapping) |
| `BLOG_MAIL_*` (HOST/PORT/USER/PASSWORD/FROM/USE_SSL/USE_TLS) | empty / 587 / … | Fallback SMTP config; **settings saved in the admin panel win** |
| `BLOG_RESET_TOKEN_MAX_AGE` | `1800` | Password-recovery token lifetime (seconds) |
| `BLOG_SECRET_KEY` / `BLOG_SECRET_KEY_FILE` | random in dev | Session & token signing key; must be set explicitly in production (the public default refuses to start) |
| `BLOG_SESSION_LIFETIME` | `86400` | Sign-in session lifetime (seconds) |
| `BLOG_COOKIE_SECURE` | `true` in production | Whether the cookie carries `Secure` (set `false` for plain HTTP) |
| `BLOG_PAGE_SIZE` | `6` | Items per page on the front end |
| `BLOG_STATIC_MAX_AGE` | `0` (dev) | Static-asset cache seconds (30 days suggested in production) |
| `BLOG_LOG_*` / `BLOG_SLOW_REQUEST_MS` / `BLOG_SLOW_QUERY_MS` | see Deployment | Log rotation and slow request/query thresholds |
| `BLOG_TRUSTED_HOSTS` | empty | Host allow-list; a wrong value causes 400s (including admin pages) |

> Where they live: `app.env` in the project root for bare metal (template `app.env.example`), `.env.docker` for Docker (template `.env.docker.example`). Changes require a **service restart**.

---

## 11. Security Recommendations

- **Keep a single administrator account**: the app is designed for a single-admin blog — there are no roles or multi-user features; `flask create-admin` only when you need it.
- **Always serve production over HTTPS** and keep `BLOG_COOKIE_SECURE=true`; use a long random `BLOG_SECRET_KEY` and keep it secret (`BLOG_SECRET_KEY_FILE` keeps it out of environment-variable dumps).
- **Back up regularly and copy backups off the server**: files stay in `backups/` by default and are lost together with the host.
- **Back up before every upgrade**, especially in manual mode, and only reopen the site once the migration finished.
- **Turn `BLOG_DEBUG` off**: production then hides tracebacks and returns a generic error page.
- Uploads are restricted to image types with size and pixel limits; `/uploads/banner/` and `/uploads/image/` have application-level Referer hot-link protection.
- The admin path is fixed at `/admin`. To reduce scanning noise, add an IP allow-list or extra Basic Auth for `/admin` in Nginx.
- Security headers (CSP, …) are emitted by the app — **do not add a second CSP in Nginx** (multiple CSPs are intersected by browsers and unexpectedly block assets).

---

## 12. Common Tasks Cheat Sheet

| Task | How |
|------|-----|
| Change site name / logo / background / disable comments | Admin "Site Settings" → save |
| Forgot the password, mail works | Recover at `/admin/forgot` |
| Forgot the password, no mail | `flask create-admin` to add an account, or edit the `admin` row with a database client (password must be a Werkzeug hash) |
| Locked out by failed logins | Wait 5 minutes, or clear the matching `login_attempt` rows |
| Site returns 503 "maintenance" everywhere | Sign in at `/admin/login?next=/admin/migrate` → run the migration (see [§9.3](#93-recovering-in-manual-mode)) |
| Upgrade the application | Back up → replace code/image → (manual mode) run the migration → watch `/healthz` |
| Move to a new domain | Update `BLOG_TRUSTED_HOSTS` / `BLOG_CANONICAL_URL`, keep `BLOG_SECRET_KEY` → restart |
| Comment spam | Disable comments (Site Settings) → clean up in moderation → rate-limit in Nginx if needed |
| Hide an article temporarily | "Withdraw" it in the article list, or save it as a draft |
| Red "database version is higher than the program version" | You deployed old code: upgrade the code, do not touch the database |

---

## 13. Related Documentation

| Document | Content |
|----------|---------|
| [Deployment](DEPLOYMENT.md) | Quick start, bare-metal/Docker deployment, environment variables, upgrading & migrations (§2.8) |
| [FAQ](FAQ.md) | Install, runtime and upgrade errors |
| [Changelog](CHANGELOG.md) | Features and fixes per release |
| [Project Architecture](ARCHITECTURE.md) | Codebase structure and module layout (for development) |
| [Contributing](../CONTRIBUTING.md) | Development, testing and release process |

中文版：[管理员手册](管理员手册.md)。


