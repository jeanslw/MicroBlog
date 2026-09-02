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

# 3. Start
python run.py
# Visit http://127.0.0.1:5000, admin at http://127.0.0.1:5000/admin/login
```

### 1.2 Docker One-Command Start (recommended for production)

```bash
# 1. Prepare variables
cp .env.docker.example .env.docker
# Edit .env.docker: set BLOG_SECRET_KEY / MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / BLOG_INIT_ADMIN_PWD

# 2. Start (web + db + nginx)
docker compose --env-file .env.docker --profile full up -d

# 3. Access
# Home:  http://localhost/
# Admin: http://localhost/admin/login
```

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
| `BLOG_SECRET_KEY` | (random) | Session/CSRF secret; **recommended to set explicitly in production** |
| `BLOG_ENV` | `development` | Set to `production` to enable Secure Cookie |
| `BLOG_DEBUG` | `False` | Debug mode (keep False in production) |
| `BLOG_DB_TYPE` | `sqlite` | `sqlite` or `mysql` |
| `BLOG_MYSQL_HOST` / `BLOG_MYSQL_USER` / `BLOG_MYSQL_PWD` / `BLOG_MYSQL_DB` | - | MySQL connection info |
| `BLOG_SQLITE_PATH` | `data/blog.db` | SQLite file path |
| `BLOG_PAGE_SIZE` | `6` | Articles per page |
| `BLOG_STATIC_MAX_AGE` | `0` | Static file cache seconds |
| `BLOG_INIT_ADMIN_USER` | `admin` | Admin username created on first startup |
| `BLOG_INIT_ADMIN_PWD` | (none) | Admin password created on first startup; **if not set, no initial admin is created** |

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

No extra config needed. Set `BLOG_DB_TYPE=sqlite` and `BLOG_INIT_ADMIN_PWD`; on first startup the schema is created in `data/` and the admin account is created automatically.

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
# Option 1: gunicorn (Linux)
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application

# Option 2: uWSGI (Linux)
uwsgi --ini uwsgi.ini

# Option 3: waitress (cross-platform, works on Windows)
pip install waitress
waitress-serve --port=5000 wsgi:application
```

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

Required variables in `.env.docker`:

| Variable | Description | Example |
|----------|-------------|---------|
| `BLOG_SECRET_KEY` | Flask Session/CSRF secret | generated via `python -c "import secrets;print(secrets.token_hex(32))"` |
| `MYSQL_ROOT_PASSWORD` | MySQL root password | strong password |
| `MYSQL_PASSWORD` | MySQL app user password | strong password |
| `BLOG_DB_TYPE` | Database type | `mysql` or `sqlite` |
| `BLOG_INIT_ADMIN_PWD` | Initial admin password | strong password |

#### 2.6.3 Startup Modes

**A. Full mode (web + db + nginx, recommended for production)**

```bash
docker compose --env-file .env.docker --profile full up -d
```
- Access: `http://localhost` (via nginx, port 80)
- Direct Flask: `http://localhost:5000`

**B. web + db only (no nginx, for internal/debug)**

```bash
docker compose --env-file .env.docker --profile mysql up -d
```
- Access: `http://localhost:5000`

**C. web only (single SQLite container, simplest)**

```bash
# Edit .env.docker to set BLOG_DB_TYPE=sqlite
docker compose --env-file .env.docker up -d web --no-deps
```

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

#### 2.6.5 Common Operations

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

#### 2.6.6 First-Deployment Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Container status | `docker compose --env-file .env.docker --profile full ps` | 3 `Up`, web/db show `(healthy)` |
| Web log | `docker compose logs web \| tail -30` | No `ERROR`/`Traceback` |
| Home access | `curl -I http://localhost/` | `HTTP/1.1 200` |
| Admin page | `curl -I http://localhost/admin/login` | `HTTP/1.1 200` |
| Admin account | `docker exec -i flask-blog-db mysql -uroot -p<PASSWORD> flask_blog -e "SELECT count(*) FROM admin"` | `count(*) >= 1` |
| Firewall | `sudo ufw status` | 5000/3306 DENY |

#### 2.6.7 Reverse Proxy Domain & HTTPS

Change `server_name _;` in `nginx/nginx.conf` to your domain, mount certificates, and switch to 443:

```nginx
server {
    listen 443 ssl http2;
    server_name blog.example.com;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
}
```

In production **only expose 80/443**; do NOT expose 5000 (Flask) or 3306 (MySQL) to the public internet.

---

Related: [README](../README.md) · [FAQ](FAQ.md) · [Project Architecture](ARCHITECTURE.md)
