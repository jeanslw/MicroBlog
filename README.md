# Blog System Deployment Documentation

Version: v1.3.3

Built with Flask 3.1, it features article publishing and management, Markdown uploads, code highlighting, image uploads, comments and likes, article categories, a banner carousel, and bilingual support (Chinese/English). 
The UI rocks a glassmorphism transparent style with awesome dynamic backgrounds (aurora / starry sky / flowing light / bubbles / classic). There's a floating color palette button at the bottom right to switch styles with one click, and your choice is saved in localStorage. 
All static resources are loaded locally, it supports SQLite and MySQL, and comes with 219 automated tests built in.

<p align="center">
  <a href="https://github.com/jeanslw/MicroBlog/releases/tag/v1.3.3"><img src="https://img.shields.io/github/v/release/jeanslw/MicroBlog?style=flat-square&label=Release" alt="Release"></a>
  <a href="https://github.com/jeanslw/MicroBlog"><img src="https://img.shields.io/github/last-commit/jeanslw/MicroBlog?style=flat-square&label=Last%20Commit" alt="Last Commit"></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.10+-777BB4?logo=python&logoColor=white" alt="Language"></a>
  <a href="https://flask.palletsprojects.com"><img src="https://img.shields.io/badge/Flask-3.1.0+-777BB4?logo=Flask&logoColor=white" alt="framework"></a>
  <a href="https://github.com/jeanslw/MicroBlog/blob/main/LICENSE"><img src="https://img.shields.io/github/license/jeanslw/MicroBlog?style=flat-square" alt="License"></a>
  <a href="https://hub.docker.com/r/jeanslw/microblog/tags"><img src="https://img.shields.io/docker/v/jeanslw/microblog/latest?label=version&logo=docker" alt="docker"></a>
</p>

> **[Chinese](README_ZH-CN.md)**

![Overview](MyBlog.png)

![Overview](MyBlog_Admin_Panel.png)

---

## 1. Features

| Module | Features |
|--------|----------|
| Article Management | Markdown editor / Markdown article upload, code highlighting (Prism), draft/publish status management |
| Comment Interaction | Article comments, replies, IP spam-like prevention |
| Category Navigation | Article category classification, sidebar category filtering |
| RSS Subscription | RSS 2.0 / Atom subscription |
| Search Function | Full-site article search functionality |
| Banner Carousel | Backend banner management, image upload & sorting |
| Internationalization | Chinese/English auto-switching, follows browser language, dropdown manual switch |
| UI Theme | Glassmorphism transparent UI, 12 built-in 1920x1080 HD background images, one-click switch via floating palette; custom background can be uploaded or set by URL in the admin panel; choice remembered in localStorage |
| Security | CSRF protection, HTML sanitization against XSS (nh3), login brute-force protection, secure sessions, image decompression bomb protection |
| Database | SQLAlchemy ORM, seamless SQLite/MySQL switching |
| Testing | pytest 219 tests covering auth/blog/comments/security/i18n |

## 2. Requirements

| Component | Version | Description |
|-----------|---------|-------------|
| Python | 3.9+ (3.11 recommended) | Runtime |
| MySQL | 5.7+ / 8.0+ (optional) | Production database; SQLite can be used for dev/test instead |
| pip | latest | Python package manager |
| Docker | 20.10+ (optional) | Containerized deployment, no env setup needed |
| Docker Compose | v2+ (optional) | Multi-container orchestration |

> **SQLite mode**: No database installation required, works out of the box.
> **Docker mode**: Copy the config template, fill in the database passwords, and one command brings up web + db + nginx — see [Section 3. Quick Start](#3-quick-start).

## 3. Quick Start

### 3.1 Docker Compose (recommended, works out of the box)

Just copy the config template and set the two database passwords — everything else works with defaults.

```bash
# 1) Prepare config
cp .env.docker.example .env.docker
#    Edit .env.docker and set at least:
#      MYSQL_ROOT_PASSWORD=your-strong-password
#      MYSQL_PASSWORD=your-strong-password

# 2) Bring up web + MySQL 8 + Nginx in one command
docker compose --env-file .env.docker --profile full up -d

# 3) Open in your browser
#    Site home   http://localhost
#    Admin entry http://localhost/admin/login
#    Direct test http://127.0.0.1:5000
```

Three orchestration profiles:

| Command | Services | Use case |
|---------|----------|----------|
| `docker compose up -d web` | web only (SQLite, **zero config, no passwords**) | Fastest trial |
| `docker compose --env-file .env.docker --profile mysql up -d` | web + MySQL | You already have an external reverse proxy |
| `docker compose --env-file .env.docker --profile full up -d` | web + MySQL + Nginx | Recommended full stack |

Built-in out-of-the-box guarantees:

- **Readiness orchestration**: a `/healthz` check (verifying both the process and the database) gates startup — web waits until MySQL finishes its first-time initialization, and Nginx only routes traffic after web is healthy. The app also retries the MySQL connection on startup as a fallback.
- **Auto schema & admin**: MySQL auto-imports [MySQL/init.sql](MySQL/init.sql) on first boot. If no initial admin password is configured, visit `/admin/setup` and follow the wizard — or set `BLOG_INIT_ADMIN_PWD` in `.env.docker` to auto-create one.
- **Login works over plain HTTP**: the bundled Nginx serves HTTP (port 80) only, so `BLOG_COOKIE_SECURE=false` by default; set it to `true` once you enable HTTPS.
- **Proxy headers preconfigured**: `BLOG_PROXY_XFOR=1`, `BLOG_PROXY_XPROTO=1`, `BLOG_PROXY_XHOST=0`.
- The default secret key and database passwords are for local testing only — **for any public deployment, change** `BLOG_SECRET_KEY`, `MYSQL_ROOT_PASSWORD`, and `MYSQL_PASSWORD`.
- Persistence: SQLite in `./data`, uploads in `./static`, MySQL in the named volume `flask-blog-mysql-data`.

Common operations:

```bash
docker compose --env-file .env.docker --profile full logs -f web       # follow logs
docker compose --env-file .env.docker --profile full down               # stop
docker compose --env-file .env.docker --profile full up -d --build      # rebuild after code changes
```

### 3.2 Running locally without Docker (development / debugging)

```bash
python -m venv venv
# Linux / WSL2:
source venv/bin/activate
# Windows:
venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env     # edit BLOG_SECRET_KEY, BLOG_DB_TYPE, DB credentials, etc.

# Linux / WSL2 (gunicorn, multiple workers)
gunicorn -w 4 -b 127.0.0.1:5000 --access-logfile - --error-logfile - "app:create_app()"

# Windows (gunicorn relies on fork and doesn't support Windows; use waitress)
waitress-serve --listen=127.0.0.1:5000 wsgi:application
```

Open `http://127.0.0.1:5000`. When running behind Nginx you can reuse [nginx/nginx.conf](nginx/nginx.conf) (it forwards the `Host` and `X-Forwarded-*` headers; set `BLOG_PROXY_XFOR=1` and `BLOG_PROXY_XPROTO=1` in `.env`, and `BLOG_COOKIE_SECURE=false` for plain-HTTP testing). For bare-metal and HTTPS setups see the [Deployment Guide](docs/DEPLOYMENT.md).

## 4. Dependencies

### 4.1 Python Dependencies (requirements.txt)

| Dependency | Version | Purpose |
|------------|---------|---------|
| Flask | 3.1.3 | Web framework |
| Flask-SQLAlchemy | 3.1.1 | ORM and database abstraction |
| Flask-Migrate | 4.0.7 | Database migrations (Alembic wrapper) |
| Flask-WTF | 1.2.1 | Form validation + CSRF protection |
| Flask-Login | 0.6.3 | Session and authentication management |
| Flask-Babel | 4.0.0 | Chinese/English internationalization (i18n) |
| WTForms | 3.2.1 | Form fields and validators |
| email-validator | 2.2.0 | Email field validation |
| PyMySQL | 1.2.0 | MySQL driver |
| cryptography | 43.0.1 | Cryptography library (PyMySQL dependency) |
| gunicorn | 23.0.0 | WSGI server (Docker / Linux production) |
| waitress | 3.0.2 | WSGI server for local runs on Windows (gunicorn doesn't support Windows) |
| python-dotenv | 1.2.1 | Loads `.env` files |
| Pillow | 10.4.0 | Image processing (resize/compress/format/protection) |
| nh3 | 0.2.18 | HTML sanitization (XSS prevention, Rust ammonia binding) |
| pytest | 8.3.3 | Testing framework |
| pytest-cov | 5.0.0 | Test coverage |

> uWSGI users can `pip install uwsgi` separately; config file [uwsgi.ini](uwsgi.ini) is provided.

### 4.2 Frontend Static Assets (static/lib/)

All JS/CSS files are localized. **No CDN is required after deployment**, fully usable on intranets.

| File | Size | Purpose |
|------|------|---------|
| `bootstrap.min.css` | 228 KB | Bootstrap 5.3 CSS framework |
| `bootstrap.bundle.min.js` | 79 KB | Bootstrap JS (nav/collapse/carousel) |
| `bootstrap-icons.css` | 94 KB | Bootstrap icon library |
| `font-awesome.min.css` | 31 KB | Font Awesome 4.7 icons (EasyMDE toolbar) |
| `easymde.min.js` | 320 KB | Markdown editor |
| `easymde.min.css` | 13 KB | Editor styles |
| `marked.min.js` | 39 KB | Markdown to HTML conversion (v15) |
| `prism.min.js` | 19 KB | Code syntax highlighting |
| `prism-tomorrow.min.css` | 1 KB | Dark code theme |
| `prism-autoloader.min.js` | 6 KB | On-demand language highlighting |

> All `<link>` and `<script>` tags reference local files via `url_for('static', ...)` — zero external links.
> Icon fonts live in `static/lib/fonts/` (bootstrap-icons plus fontawesome-webfont woff2/woff/ttf/svg/eot).
> EasyMDE is initialized with `autoDownloadFontAwesome: false` and Font Awesome is loaded locally, so no maxcdn request is injected at runtime.

## 5. Admin Login & Backend URLs

| Page | URL | Description |
|------|-----|-------------|
| Admin Login | `/admin/login` | Admin login entry point |
| Home | `/` | Article list page |
| New Article | `/article/new` | Login required (Markdown editor) |
| Drafts | `/drafts` | Login required, manage drafts |
| Site Settings | `/admin/site_setting` | Login required, change site name |
| Change Password | `/admin/change_pwd` | Login required |
| Banner Management | `/banner/list` | Login required, manage banners |
| Language Switch | `/set_lang/zh_CN` or `/set_lang/en` | Switch Chinese/English |

**First login (choose one):**

- Option 1 (recommended): leave the password unset. After starting the service, visit `http://your-server/admin/login` — when no admin exists you are redirected to the `/admin/setup` wizard to create the account in the browser.
- Option 2: set `BLOG_INIT_ADMIN_PWD` in `.env` / `.env.docker`; the admin is auto-created on first startup. Log in with `admin` / the password you set.

**Immediately change to a strong password on the "Change Password" page after logging in.**

> `BLOG_INIT_ADMIN_PWD` only takes effect once when the admin table is empty and never overwrites an existing account. When it is unset, the startup log shows an informational warning — this is expected.

## 6. Internationalization (i18n)

- Supports Chinese (zh_CN) and English (en)
- **Defaults to browser language**: first visit auto-selects based on browser `Accept-Language`
- **Manual switch**: dropdown in the navbar (right side); selection is saved to session and persists across visits
- Translation files are in the `translations/` directory, managed with Flask-Babel
- After modifying translations, recompile: `pybabel compile -d translations`

## 7. Testing

```bash
# Run all tests
pytest

# Run specific module tests
pytest tests/test_blog.py
pytest tests/test_i18n.py

# View coverage
pytest --cov=app
```

219 tests covering: authentication & brute-force protection, article CRUD, comments & likes, banner management, health checks & MySQL readiness waits, security (XSS sanitization/CSRF/host allowlist/path validation), i18n language switching, data models, and more.

## 8. Security Features

| Feature | Implementation |
|---------|---------------|
| CSRF Protection | Flask-WTF global CSRF, all POST forms auto-include token |
| XSS Prevention | nh3 whitelist HTML sanitization (raw content stored, sanitized on display) |
| Password Security | Werkzeug pbkdf2:sha256 hash storage |
| Brute-Force Protection | IP + username failure counting with lockout |
| Secure Sessions | HttpOnly + SameSite=Lax + Secure (production) |
| Upload Security | Type/size validation, UUID renaming, double-extension prevention, Pillow decompression bomb protection |
| Hotlink Protection | Nginx valid_referers for `/static/banner/` and `/static/uploads/` |
| Error Hiding | Production mode hides exception traces, returns generic error page |

## 9. Directory Permissions

```bash
# Ensure upload directories are writable
mkdir -p static/banner static/uploads
chmod 755 static/banner static/uploads

# SQLite mode requires writable data/ (auto-created on first startup)
mkdir -p data
chmod 755 data
```
## Related Documentation

| Document | Description |
|----------|-------------|
| [Deployment Guide](docs/DEPLOYMENT.md) | Quick start + full deployment (bare-metal, Docker Compose, HTTPS) |
| [FAQ](docs/FAQ.md) | Frequently asked questions & troubleshooting |
| [Project Architecture](docs/ARCHITECTURE.md) | Codebase structure, entry points & module layout |
| [Contributing Guide](CONTRIBUTING.md) | Bug reporting, code contribution workflow & commit conventions; release rules see [Version Management](CONTRIBUTING.md#5-version-management) |

## Contact
- Issues & PRs: [GitHub Issues](https://github.com/jeanslw/MicroBlog/issues)
- Email: jeanslw@qq.com
