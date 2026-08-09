# Blog System Deployment Documentation

Version: v1.0
Overview: This blog is built on Flask framework 3.1. Features include comment & like, article categories, banner carousel, with a Markdown code editor. All assets are loaded locally. Supports both SQLite and MySQL databases.

## 1. Requirements

| Component | Version | Description |
|-----------|---------|-------------|
| Python | 3.9+ (3.11 recommended) | Runtime |
| MySQL | 5.7+ / 8.0+ (optional) | Production database; SQLite can be used for dev/test instead |
| pip | latest | Python package manager |
| Docker | 20.10+ (optional) | Containerized deployment, no env setup needed |
| Docker Compose | v2+ (optional) | Multi-container orchestration |

> **SQLite mode**: No database installation required, works out of the box, suitable for dev/test and small deployments.
> **Docker mode**: See section 4.7, one command brings up web + db + nginx.

## 2. Project Structure

```
flaskProject/
├── run.py                         # Development entry
├── wsgi.py                        # WSGI deployment entry
├── uwsgi.ini                      # uWSGI config (bare-metal Linux)
├── Dockerfile                     # Docker image build
├── docker-compose.yml             # Multi-container orchestration (web + db + nginx)
├── .dockerignore                  # Docker build ignore
├── .env.example                   # Flask env vars template (bare-metal)
├── .env.docker.example            # Docker Compose vars template
├── config.py                      # Config (secret key / db type / debug)
├── requirements.txt               # Python dependencies
├── data/                          # SQLite database directory (auto-created)
├── nginx/
│   └── nginx.conf                 # Nginx reverse proxy config (for Docker)
├── MySQL/
│   └── init.sql                   # MySQL schema init script
├── app/
│   ├── __init__.py                # Flask factory + error handling + global context
│   ├── db.py                      # Unified database layer (auto-switch MySQL / SQLite)
│   ├── extensions.py              # Shared DB queries + brute-force protection
│   ├── blog/                      # Blog module
│   ├── admin/                     # Admin module
│   ├── banner/                    # Banner carousel module
│   └── comment/                   # Comment & like module
├── templates/                     # Jinja2 templates
│   ├── base.html                  # Common layout
│   ├── blog/                      # Blog pages
│   ├── admin/                     # Admin pages
│   └── banner/                    # Banner management
└── static/
    ├── favicon.ico
    ├── banner/                    # Uploaded banner images
    └── lib/                       # Local third-party libs (no internet required)
```

## 3. Local Static Assets

All JS/CSS files are localized in `static/lib/`. **No CDN is required after deployment**, fully usable on intranets.

| File | Size | Purpose |
|------|------|---------|
| `bootstrap.min.css` | 228 KB | Bootstrap 5.3 CSS framework |
| `bootstrap.bundle.min.js` | 79 KB | Bootstrap JS (nav/collapse/carousel) |
| `bootstrap-icons.css` | 94 KB | Bootstrap icon library |
| `easymde.min.js` | 320 KB | Markdown rich-text editor |
| `easymde.min.css` | 13 KB | Editor styles |
| `marked.min.js` | 39 KB | Markdown → HTML conversion |
| `prism.min.js` | 19 KB | Code syntax highlighting |
| `prism-tomorrow.min.css` | 6 KB | Dark code theme |
| `prism-autoloader.min.js` | 6 KB | On-demand language highlighting |

> All `<link>` and `<script>` tags in pages reference local files via `url_for('static', ...)` — zero external links.

## 4. Deployment Steps

### 4.1 Get the Code

```bash
# Copy project directory to the server
scp -r flaskProject/ user@server:/opt/
cd /opt/flaskProject
```

### 4.2 Install Python Dependencies

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt
```

`requirements.txt` contents (only direct dependencies listed; rest are resolved automatically by pip):

| Dependency | Version | Purpose |
|------------|---------|---------|
| Flask | 3.1.3 | Web framework |
| PyMySQL | 1.2.0 | MySQL driver |
| gunicorn | 23.0.0 | WSGI server (Docker / Linux production) |
| python-dotenv | 1.2.1 | Loads `.env` (optional; app still works without it) |

> uWSGI users can `pip install uwsgi` separately; config file [uwsgi.ini](uwsgi.ini) is provided.

### 4.3 Configuration (via Environment Variables)

All configuration is injected via environment variables — **`config.py` does not need editing**. Common variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BLOG_SECRET_KEY` | (none) | Session/CSRF secret; **must be set in production**, otherwise startup fails |
| `BLOG_ENV` | (none) | When set to `production`, enables Secure Cookie and enforces SECRET_KEY |
| `BLOG_DEBUG` | `False` | Debug mode (keep False in production to avoid Werkzeug debugger exposure) |
| `BLOG_DB_TYPE` | `sqlite` | `sqlite` or `mysql` |
| `BLOG_MYSQL_HOST` / `BLOG_MYSQL_USER` / `BLOG_MYSQL_PWD` / `BLOG_MYSQL_DB` | - | MySQL connection info |
| `BLOG_SQLITE_PATH` | `data/blog.db` | SQLite file path |
| `BLOG_PAGE_SIZE` | `6` | Articles per page |
| `BLOG_STATIC_MAX_AGE` | `0` | Static file cache seconds |
| `BLOG_INIT_ADMIN_USER` | `admin` | Admin username created on first SQLite schema init |
| `BLOG_INIT_ADMIN_PWD` | (none) | Admin password created on first SQLite schema init; **if not set, no initial admin is created** |

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

1. Install MySQL:

```bash
# Ubuntu/Debian
sudo apt install mysql-server

# CentOS/RHEL
sudo yum install mysql-server
```

2. Create the database:

```sql
CREATE DATABASE flask_blog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

3. Edit `config.py`: set `DB_TYPE = "mysql"` and fill in correct DB credentials.

4. Create tables and seed data (see SQL script in section 4.4 below), or import directly:

```bash
mysql -u root -p flask_blog < MySQL/init.sql
```

### 4.4 Manual Schema Init SQL (for MySQL users)

If MySQL was not initialized via the auto-import script, **just use [`MySQL/init.sql`](MySQL/init.sql)** (already validated with STRICT_TRANS_TABLES strict mode, includes indexes, charset, and field length):

```bash
mysql -uroot -p < MySQL/init.sql
```

> ⚠️ **MySQL strict mode is recommended in production** (enabled by default) to avoid silent data truncation:
> ```sql
> -- View current sql_mode
> SELECT @@sql_mode;
> -- Recommended (my.cnf / my.ini)
> [mysqld]
> sql_mode = STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION
> ```

**Key field lengths** (correctly set in init.sql; do not shrink when creating tables manually):

| Field | Length | Reason |
|-------|--------|--------|
| `admin.password` | VARCHAR(255) | Werkzeug 3.x pbkdf2:sha256:600000 hash is ~102 chars; 256 leaves room for future scrypt/argon2 |
| `banner.img_path` | VARCHAR(500) | Upload path includes UUID + secure_filename, can be long |
| `article.content` | MEDIUMTEXT | Article body can be long; TEXT is only 64KB, MEDIUMTEXT is 16MB |
| `article.title` | VARCHAR(500) | Long-title compatibility |

**Initialize the admin account** (init.sql does NOT insert plaintext password; must be done manually):

```bash
# 1. Generate password hash
python -c "from werkzeug.security import generate_password_hash as g; print(g('your-strong-password'))"
# Or in Docker:
# docker exec -it flask-blog-web python -c "from werkzeug.security import generate_password_hash as g; print(g('your-strong-password'))"

# 2. INSERT into database
mysql -uroot -p flask_blog -e "INSERT INTO admin (username, password) VALUES ('admin', '<hash-from-step-above>')"
```

### 4.5 Start the Service

**For dev/test:**

```bash
python run.py
# Listens on http://127.0.0.1:5000
```

**Recommended production options:**

```bash
# Option 1: uWSGI (Linux)
pip install uwsgi
uwsgi --ini uwsgi.ini

# Option 2: gunicorn (Linux)
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application

# Option 3: waitress (cross-platform, works on Windows)
pip install waitress
waitress-serve --port=5000 wsgi:application
```

**Nginx reverse proxy (optional):**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 10m;  # allow banner uploads

    location /static {
        alias /opt/flaskProject/static;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 4.6 Install Fonts (optional)

If code blocks in pages are not using a monospace font, install Fira Code:

```bash
# Ubuntu
sudo apt install fonts-firacode
# Or manually download and place in the system fonts directory
```

### 4.7 Docker Compose Deployment (recommended for production)

Suitable for users who don't want to manually configure Python/MySQL/Nginx — one command brings up the full stack.

#### 4.7.0 Server Preparation (required on first deployment)

```bash
# 1. Install Docker + Compose plugin (skip if already installed)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # passwordless docker, requires relogin

# 2. Clone the project
git clone <your-repo-url> /opt/flaskProject
cd /opt/flaskProject

# 3. Verify Docker
docker --version               # expect 20.10+
docker compose version         # expect v2+
```

#### 4.7.1 Prepare the Variables File

```bash
cp .env.docker.example .env.docker
vim .env.docker
```

Required variables in `.env.docker` (**must be set**):

| Variable | Description | Example |
|----------|-------------|---------|
| `BLOG_SECRET_KEY` | Flask Session/CSRF secret | generated via `python -c "import secrets;print(secrets.token_hex(32))"` |
| `MYSQL_ROOT_PASSWORD` | MySQL root password | strong password |
| `MYSQL_PASSWORD` | MySQL app user password | strong password |
| `BLOG_DB_TYPE` | Database type | `mysql` or `sqlite` |
| `BLOG_INIT_ADMIN_PWD` | Initial admin password (only on first SQLite schema init) | strong password |

#### 4.7.2 Startup Modes

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

#### 4.7.2.1 Verify Deployment

After startup, confirm services are healthy:

```bash
# 1. Container status (expect three Up, web/db showing (healthy))
docker compose --env-file .env.docker --profile full ps

# 2. Health check
curl -I http://localhost/                 # via nginx, expect 200
curl -I http://localhost:5000/            # direct Flask, expect 200

# 3. View startup logs (no ERROR = OK)
docker compose --env-file .env.docker logs web | tail -20
docker compose --env-file .env.docker logs db  | tail -20

# 4. Browser access
# Home:     http://<server-ip>/
# Admin:    http://<server-ip>/admin/login
```

#### 4.7.3 Container Architecture

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

#### 4.7.4 Common Operations

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

#### 4.7.5 First-time MySQL Initialization

- On first container startup `MySQL/init.sql` is executed automatically (includes strict mode, charset, indexes)
- Admin account is **auto-created**: set `BLOG_INIT_ADMIN_PWD` in `.env.docker`; on first startup the web container creates the `admin` account
- To change the admin username, set `BLOG_INIT_ADMIN_USER` (default `admin`)

```bash
# Verify admin was created
docker exec -i flask-blog-db mysql -uroot -p<ROOT_PASSWORD> flask_blog -e \
  "SELECT id, username FROM admin;"
```

> If `BLOG_INIT_ADMIN_PWD` is not set, no admin is created. Set it and restart the web container to auto-create:
> ```bash
> docker compose restart web
> ```

#### 4.7.6 Upgrading the Image

```bash
git pull
docker compose build web
docker compose --env-file .env.docker --profile full up -d
```

#### 4.7.7 Reverse Proxy Domain & HTTPS

Change `server_name _;` in `nginx/nginx.conf` to your domain, mount certificates, and switch to 443 listening. For example:

```nginx
server {
    listen 443 ssl http2;
    server_name blog.example.com;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    # ... rest same as nginx.conf
}
```

Mount certificates: in `docker-compose.yml`, add to the nginx service `volumes`:
```yaml
- /etc/letsencrypt:/etc/nginx/certs:ro
```

#### 4.7.8 Firewall & Ports

In production **only expose 80/443**; do NOT expose 5000 (Flask) or 3306 (MySQL) to the public internet:

```bash
# Ubuntu UFW example
sudo ufw allow 22/tcp       # SSH
sudo ufw allow 80/tcp       # HTTP
sudo ufw allow 443/tcp      # HTTPS
sudo ufw deny 5000/tcp      # Flask direct (internal only)
sudo ufw deny 3306/tcp      # MySQL (internal only)
sudo ufw enable
```

If you don't need to connect to the DB from the host for debugging, comment out `ports: - "3306:3306"` in the `db` service of `docker-compose.yml` to avoid exposing it entirely.

#### 4.7.9 First-Deployment Checklist

After deployment, verify each item:

| Check | Command | Expected |
|-------|---------|----------|
| Container status | `docker compose --env-file .env.docker --profile full ps` | 3 `Up`, web/db show `(healthy)` |
| Web log | `docker compose logs web \| tail -30` | No `ERROR`/`Traceback` |
| DB log | `docker compose logs db \| tail -30` | Shows `ready for connections` |
| Home access | `curl -I http://localhost/` | `HTTP/1.1 200` |
| Admin page | `curl -I http://localhost/admin/login` | `HTTP/1.1 200` |
| Admin account | `docker exec -i flask-blog-db mysql -uroot -p<PASSWORD> flask_blog -e "SELECT count(*) FROM admin"` | `count(*) >= 1` |
| Static asset | `curl -I http://localhost/static/favicon.ico` | `HTTP/1.1 200` |
| Firewall | `sudo ufw status` | 5000/3306 DENY |

## 5. First Login

The admin account is **auto-created** by the system — no manual INSERT required:

1. Ensure `BLOG_INIT_ADMIN_PWD` is set in `.env` (or env vars)
2. After starting the service, visit `http://your-server/admin/login`
3. Log in with `admin` / the password you set
4. **Immediately change to a strong password on the "Change Password" page after login**

> If `BLOG_INIT_ADMIN_PWD` is not set, no admin is created and a warning appears in startup logs. Set it and restart the service to auto-create.

## 6. Directory Permissions

```bash
# Ensure upload directories are writable
mkdir -p static/banner
chmod 755 static/banner

# SQLite mode requires writable data/ (auto-created on first startup)
mkdir -p data
chmod 755 data
```

## 7. FAQ

**Q: Page styles broken?**
Confirm all 9 files in `static/lib/` exist (see list in section 3).

**Q: Database connection failed (MySQL)?**
- Confirm MySQL service is running
- Confirm DB credentials in `config.py` are correct
- Confirm `DB_TYPE = "mysql"`
- Confirm database `flask_blog` exists and schema is complete

**Q: Database connection failed (SQLite)?**
- Confirm `DB_TYPE = "sqlite"`
- Confirm `data/` directory exists and is writable
- Delete `data/blog.db` and restart to reset the database

**Q: How to switch databases?**
Just change `DB_TYPE` in `config.py` (`"mysql"` or `"sqlite"`); code adapts automatically — no business-logic changes needed.

**Q: Banner image doesn't show after upload?**
Confirm `static/banner/` exists and is writable.

**Q: Editor (EasyMDE) doesn't load?**
Confirm `static/lib/easymde.min.js` and `static/lib/marked.min.js` exist.

**Q: `docker compose` startup fails with `must be set in .env.docker`?**
`.env.docker` was not created or required vars are missing. Run `cp .env.docker.example .env.docker`, then fill in `BLOG_SECRET_KEY`, `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`.

**Q: Port 80/5000 is already in use after startup?**
Edit port mapping in `docker-compose.yml` (e.g. `"8080:80"`, `"5001:5000"`) and access via the new ports.

**Q: Web container keeps restarting?**
Run `docker compose logs web` to see why. Common causes: DB not yet healthy (wait 30s and restart), `BLOG_SECRET_KEY` not set.

**Q: First startup is slow?**
MySQL initial setup takes 30–60s; `web` only starts after `db` becomes `healthy`. This is normal. Use `docker compose logs -f db` to watch progress.

**Q: Admin login says password is wrong?**
The `admin.password` field must be a hash produced by `generate_password_hash` — **plaintext passwords cannot log in**. Regenerate the hash and run `UPDATE admin SET password='<hash>' WHERE username='admin'`.

**Q: `docker compose down -v` wiped all data?**
`-v` deletes named volumes (MySQL data). For routine stops, use `docker compose down` (without `-v`).

**Q: How to apply code changes?**
`docker compose build web && docker compose --env-file .env.docker --profile full up -d` rebuilds the web image and rolling-restarts.


## 8. For suggestions, open an issue on the GitHub repo, or email: jeanslw@qq.com
