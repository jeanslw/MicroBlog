# Deployment Guide

Covers everything needed to run MicroBlog — from a 3-step bare-metal quick start to full Docker Compose production deployment. For features and overview, see the [README](../README.md).

## 1. Quick Deployment

### 1.1 Bare-Metal Quick Start (SQLite, 3 steps)

```bash
# 1. Install dependencies
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
export BLOG_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export BLOG_INIT_ADMIN_PWD='your-strong-password'

# 3. Start (dev server)
python run.py
# Visit http://127.0.0.1:5000, admin at http://127.0.0.1:5000/admin/login
```

> For production use a WSGI server: gunicorn on Linux/WSL2, waitress on Windows — see [2.5 Start the Service](#25-start-the-service).
> The app starts fine without `BLOG_INIT_ADMIN_PWD`; the first visit to `/admin/login` redirects to the `/admin/setup` wizard to create the admin.

### 1.2 Docker One-Command Start (recommended for production)

Just copy the config template and set the two MySQL passwords — everything else works with defaults:

```bash
# 1. Prepare variables
cp .env.docker.example .env.docker
# Edit .env.docker: only MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD must be changed
# (BLOG_SECRET_KEY and BLOG_INIT_ADMIN_PWD can stay empty:
#  the former has a built-in test default, the latter is replaced by the setup wizard)

# 2. Start (web + db + nginx)
docker compose --env-file .env.docker --profile full up -d

# 3. Access
# Home:    http://localhost/
# Admin:   http://localhost/admin/login (redirects to /admin/setup when no admin exists)
# Health:  http://localhost/healthz
```

> Just want the fastest trial without MySQL: `docker compose up -d web` (SQLite, zero config, no .env.docker needed) and open `http://127.0.0.1:5000`.

## 2. Detailed Deployment

### 2.1 Get the Code

```bash
git clone https://github.com/jeanslw/MicroBlog.git /opt/MicroBlog
cd /opt/MicroBlog
```

### 2.2 Install Python Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
```

### 2.3 Configuration (via Environment Variables)

All configuration is injected via environment variables — **`config.py` does not need editing**. Common variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BLOG_SECRET_KEY` | (random) | Session/CSRF secret; **mandatory in production — the app refuses to start without it** |
| `BLOG_ENV` | `development` | In `production`, Secure Cookie is enabled by default (override with `BLOG_COOKIE_SECURE`) |
| `BLOG_DEBUG` | `False` | Debug mode (keep False in production) |
| `BLOG_COOKIE_SECURE` | dev `false` / prod `true` | Whether the session cookie is HTTPS-only; **set `false` for plain-HTTP debugging / the bundled nginx**, set back to `true` once HTTPS is enabled |
| `BLOG_CANONICAL_URL` | (none) | Fixed external site URL (e.g. `https://blog.example.com`) used in password-reset emails/RSS/sitemap; prevents Host header injection |
| `BLOG_TRUSTED_HOSTS` | (none, no check) | Host allowlist, comma-separated; requests with non-listed Host get 400. Set to the real domain in production |
| `BLOG_PROXY_XFOR` / `BLOG_PROXY_XPROTO` / `BLOG_PROXY_XHOST` | `0` / `0` / `0` | Behind a reverse proxy set the first two to `1` (real IP/proto); keep `XHOST` at `0` because nginx forwards the Host header |
| `BLOG_DB_TYPE` | `sqlite` | `sqlite` or `mysql`; when set to `mysql` with missing connection fields the app refuses to start (no silent fallback) |
| `BLOG_MYSQL_HOST` / `BLOG_MYSQL_USER` / `BLOG_MYSQL_PWD` / `BLOG_MYSQL_DB` | - | MySQL connection info |
| `BLOG_SQLITE_PATH` | `data/blog.db` | SQLite file path |
| `BLOG_PAGE_SIZE` | `6` | Articles per page |
| `BLOG_STATIC_MAX_AGE` | `0` | Static file cache seconds (compose template defaults to 43200) |
| `BLOG_INIT_ADMIN_USER` | `admin` | Admin username created on first startup |
| `BLOG_INIT_ADMIN_PWD` | (none) | Auto-created admin password, takes effect only once when the admin table is empty; **leave empty and create the admin via the `/admin/setup` wizard on first visit** |

Linux example:

```bash
export BLOG_ENV=production
export BLOG_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export BLOG_DB_TYPE=sqlite
export BLOG_INIT_ADMIN_USER=admin
export BLOG_INIT_ADMIN_PWD='your-strong-password'
```

Windows PowerShell example:

```powershell
$env:BLOG_ENV = "production"
$env:BLOG_SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | % {[char]$_})
$env:BLOG_DB_TYPE = "sqlite"
$env:BLOG_INIT_ADMIN_PWD = "your-strong-password"
```

#### Option A: SQLite (recommended for dev/test)

No extra config needed — just set `BLOG_DB_TYPE=sqlite`. On first startup the schema is created in `data/`; create the admin via `BLOG_INIT_ADMIN_PWD` or leave it empty and use the `/admin/setup` wizard (make sure `data/` is writable).

#### Option B: MySQL (recommended for production)

1. Install MySQL and create the database:

```sql
CREATE DATABASE flask_blog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. Set environment variables:

```bash
export BLOG_DB_TYPE=mysql
export BLOG_MYSQL_HOST=localhost
export BLOG_MYSQL_USER=root
export BLOG_MYSQL_PWD='your-mysql-password'
export BLOG_MYSQL_DB=flask_blog
export BLOG_INIT_ADMIN_PWD='your-admin-password'
```

3. Import schema (optional, app auto-creates tables on startup):

```bash
mysql -u root -p flask_blog < MySQL/init.sql
```

### 2.4 Manual Schema Init SQL (for MySQL users)

Use [`MySQL/init.sql`](../MySQL/init.sql) directly (validated with STRICT_TRANS_TABLES strict mode, includes indexes, charset, and field lengths):

```bash
mysql -uroot -p < MySQL/init.sql
```

> ⚠️ **MySQL strict mode is recommended in production** to avoid silent data truncation.

**Key field lengths** (correctly set in init.sql; do not shrink when creating tables manually):

| Field | Length | Reason |
|-------|--------|--------|
| `admin.password` | VARCHAR(255) | Werkzeug 3.x pbkdf2:sha256:600000 hash ~102 chars |
| `banner.img_path` | VARCHAR(500) | Upload path includes UUID + secure_filename |
| `article.content` | MEDIUMTEXT | Article body; TEXT is only 64KB, MEDIUMTEXT is 16MB |
| `article.title` | VARCHAR(500) | Long-title compatibility |

### 2.5 Start the Service

**For dev/test:**

```bash
python run.py
# Listens on http://127.0.0.1:5000
```

**Production options:**

```bash
# Option 1: gunicorn (Linux / WSL2, bundled in the Docker image;
# all workers share the same BLOG_SECRET_KEY)
# Bind to loopback when nginx runs on the same host; use 0.0.0.0 only for direct exposure
gunicorn -w 4 -b 127.0.0.1:5000 --access-logfile - --error-logfile - "app:create_app()"
# The prebuilt WSGI entry point also works: gunicorn -w 4 -b 127.0.0.1:5000 wsgi:application

# Option 2: uWSGI (Linux)
uwsgi --ini uwsgi.ini

# Option 3: waitress (cross-platform, for production/testing on Windows; already in requirements.txt)
waitress-serve --listen=127.0.0.1:5000 wsgi:application
```

> **Behind nginx or another reverse proxy**: set `BLOG_PROXY_XFOR=1`, `BLOG_PROXY_XPROTO=1` (keep `BLOG_PROXY_XHOST=0`)
> and make sure the proxy forwards the `Host` and `X-Forwarded-*` headers (you can reuse [nginx/nginx.conf](../nginx/nginx.conf)).
> Plain-HTTP testing also requires `BLOG_COOKIE_SECURE=false`, otherwise the session cookie is never sent back after login.
> In MySQL mode the app waits for the database to become ready on startup (probes every 3s, up to 90s) — no extra sleep script needed.

### 2.6 Docker Compose Deployment (recommended for production)

#### 2.6.1 Server Preparation (first deployment)

```bash
# Install Docker + Compose plugin
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # passwordless docker, requires relogin
```

#### 2.6.2 Prepare the Variables File

```bash
cp .env.docker.example .env.docker
vim .env.docker
```

Variables in `.env.docker` fall into three groups (**only the two MySQL passwords are required to start**):

| Group | Variable | Description |
|-------|----------|-------------|
| **Required** | `MYSQL_ROOT_PASSWORD` | MySQL root password — set a strong one |
| **Required** | `MYSQL_PASSWORD` | Password for the `blog` app user — set a strong one (the app connection picks it up automatically) |
| Recommended for public | `BLOG_SECRET_KEY` | Empty = built-in test default key (public, insecure); generate one with `python -c "import secrets;print(secrets.token_hex(32))"` before going public |
| Recommended for public | `BLOG_CANONICAL_URL` / `BLOG_TRUSTED_HOSTS` | Your real domain; prevents Host header injection |
| Optional | `BLOG_DB_TYPE` | Defaults to `mysql`; set `sqlite` to run without the db service |
| Optional | `BLOG_INIT_ADMIN_PWD` | Empty = create the admin via the `/admin/setup` wizard; a password auto-creates it on first boot (once only) |
| Optional | `BLOG_COOKIE_SECURE` | Defaults to `false` (bundled nginx is plain HTTP); set `true` after enabling HTTPS |
| Optional | `WEB_PORT` | Host-side port for direct web access, default `5000`, bound to `127.0.0.1` only |

> `BLOG_PROXY_XFOR/XPROTO/XHOST` already have correct compose defaults (1/1/0) — no change needed.

#### 2.6.3 Startup Modes

**A. Full mode (web + db + nginx, recommended for production)**

```bash
docker compose --env-file .env.docker --profile full up -d
```
- Access: `http://localhost` (via nginx, port 80)
- Direct Flask (host loopback only): `http://127.0.0.1:5000`

**B. web + db only (no nginx, for internal/debug/external proxy)**

```bash
docker compose --env-file .env.docker --profile mysql up -d
```
- Access: `http://127.0.0.1:5000` (bound to the host loopback only; add your own proxy or change the compose port mapping to expose it)

**C. web only (single SQLite container, simplest, zero config)**

```bash
# No .env.docker and no --no-deps needed (the db dependency is ignored
# automatically when its profile is not enabled; requires Compose v2.20+)
docker compose up -d web
```
- Access: `http://127.0.0.1:5000`; the database file lives in `./data/blog.db` on the host
- Note: compose implicitly reads a root-level `.env`. If it contains `BLOG_DB_TYPE=mysql`, pass `--env-file` pointing to a file containing only `BLOG_DB_TYPE=sqlite`

#### 2.6.4 Container Architecture

```
┌──────────────────────────────────────────────────┐
│  Host                                            │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
│  │  nginx   │──▶│   web    │──▶│     db      │  │
│  │  :80     │   │  :5000   │   │  :3306      │  │
│  └──────────┘   └──────────┘   └─────────────┘  │
│       │              │                │          │
│       │              │                ▼          │
│       │              │          ┌──────────┐     │
│       │              │          │  volume  │     │
│       │              │          │ mysql-db │     │
│       │              │          └──────────┘     │
│       │              ▼                            │
│       │         ┌──────────┐                      │
│       │         │ ./data   │ (SQLite persistence)│
│       │         │ ./static │ (uploads persistence)│
│       │         └──────────┘                      │
│       ▼                                            │
│   ./static (served directly by nginx)             │
└──────────────────────────────────────────────────┘
```

#### 2.6.5 Health Checks, Startup Order & Directory Permissions

The orchestration includes these guarantees out of the box — no custom wait scripts required:

| Mechanism | Behavior |
|-----------|----------|
| `/healthz` probe | The web container health check calls `GET /healthz`; the app runs `SELECT 1` and returns 200 on success or 503 if the database fails. This path is exempt from the Host allowlist |
| db health check | MySQL container uses `mysqladmin ping` and auto-imports [MySQL/init.sql](../MySQL/init.sql) on first boot |
| Startup order | web `depends_on` db being healthy (ignored automatically in SQLite mode); nginx only routes traffic once web is healthy |
| App-level wait | On startup the web app waits until MySQL accepts connections (probe every 3s, up to 90s) before creating tables/initializing — no skipped initialization due to slow MySQL first boot |
| Mount permissions | The container entrypoint [docker-entrypoint.sh](../docker-entrypoint.sh) fixes ownership of `./data`, `./static/banner`, `./static/uploads`, and `./backups`, then drops privileges — the root-owned bind-mount problem on native Linux Docker is handled automatically |

Verify the probe manually:

```bash
curl http://localhost/healthz        # via nginx, expect {"status":"ok"}
curl http://127.0.0.1:5000/healthz   # direct to web
```

#### 2.6.6 Common Operations

```bash
# View logs
docker compose logs -f web
docker compose logs -f db

# Restart a service
docker compose restart web

# Stop and clean up (keep volumes)
docker compose down

# Stop and delete data volumes (DANGER! wipes database)
docker compose down -v

# Rebuild image (after code changes)
docker compose build web
docker compose --env-file .env.docker --profile full up -d
```

#### 2.6.7 First-Deployment Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Container status | `docker compose --env-file .env.docker --profile full ps` | 3 `Up`, web/db show `(healthy)` |
| Web log | `docker compose logs web \| tail -30` | No `ERROR`/`Traceback` |
| Health probe | `curl http://localhost/healthz` | `{"status":"ok"}` |
| Home access | `curl -I http://localhost/` | `HTTP/1.1 200` |
| Admin page | `curl -I http://localhost/admin/login` | `HTTP/1.1 200` (a 302 redirect to `/admin/setup` is also fine when no admin exists) |
| Admin account | After creating the admin via `/admin/setup` in the browser: `docker exec -i flask-blog-db mysql -uroot -p<PASSWORD> flask_blog -e "SELECT count(*) FROM admin"` | `count(*) >= 1` (0 before setup is expected) |
| Firewall | `sudo ufw status` | Only 80/443 allowed; 5000/3306 not exposed publicly |

#### 2.6.8 Reverse Proxy Domain & HTTPS

Change `server_name _;` in `nginx/nginx.conf` to your domain, mount certificates, and switch to 443:

```nginx
server {
    listen 443 ssl http2;
    server_name blog.example.com;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
}
```

Also set `BLOG_COOKIE_SECURE=true` in `.env.docker` and recreate web (`BLOG_PROXY_XPROTO=1` is already enabled by compose, so the app correctly detects HTTPS).

In production **only expose 80/443**; do NOT expose 5000 (Flask) or 3306 (MySQL) to the public internet (the current compose already binds 5000 to loopback and does not publish 3306).

---

Related: [README](../README.md) · [FAQ](FAQ.md) · [Project Architecture](ARCHITECTURE.md)
