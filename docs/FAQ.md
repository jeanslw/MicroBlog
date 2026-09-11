# Frequently Asked Questions (FAQ)

Troubleshooting and answers for common issues. For setup steps, see the [Deployment Guide](DEPLOYMENT.md).

**Q: Page styles broken?**
Confirm all 9 files in `static/lib/` exist (see the static-asset table in the [README dependencies section](../README.md#4-dependencies)).

**Q: Database connection failed (MySQL)?**
- Confirm MySQL service is running
- Confirm `BLOG_MYSQL_*` environment variables are correct
- Confirm `BLOG_DB_TYPE=mysql`
- Confirm database `flask_blog` exists

**Q: Database connection failed (SQLite)?**
- Confirm `BLOG_DB_TYPE=sqlite`
- Confirm `data/` directory exists and is writable
- Delete `data/blog.db` and restart to reset the database

**Q: How to switch databases?**
Change `BLOG_DB_TYPE` environment variable (`mysql` or `sqlite`); code adapts automatically.

**Q: Admin login says password is wrong?**
Passwords are stored as `generate_password_hash` hashes — **plaintext passwords cannot log in**. Note that `BLOG_INIT_ADMIN_PWD` only takes effect once when the admin table is empty (first initialization); it does **not** change the password of an existing admin. To reset a password, use a Python shell:
```python
from werkzeug.security import generate_password_hash
from app.models import Admin
from app.extensions import db

# Execute within app context
admin = db.session.query(Admin).filter_by(username="admin").first()
admin.password = generate_password_hash("new-password")
db.session.commit()
```
For a brand-new deployment with an empty admin table, you can also visit `/admin/setup` in the browser and use the setup wizard.

**Q: Login fails behind nginx / keeps redirecting back to the login page?**
The most common cause: production mode sets `SESSION_COOKIE_SECURE=true` by default, and browsers never send a Secure cookie back over **plain HTTP**, so the session is lost. Check in order:
1. The bundled compose nginx serves HTTP (port 80) only — make sure `BLOG_COOKIE_SECURE=false` is set in `.env.docker` and recreate web; set it back to `true` after enabling HTTPS (443)
2. Make sure the proxy forwards the `Host` and `X-Forwarded-*` headers, and set `BLOG_PROXY_XFOR=1`, `BLOG_PROXY_XPROTO=1` (compose already provides these defaults)
3. In multi-worker / multi-instance deployments every process must share the same `BLOG_SECRET_KEY`, otherwise sessions cannot be verified across workers
The ready-made [nginx/nginx.conf](../nginx/nginx.conf) can be used as-is.

**Q: Requests return 400 with "Invalid Host header" / "Host 'xxx' is not trusted."?**
The app enforces a Host allowlist to prevent Host header injection. Add the hostname/domain you access it with (including port, e.g. `blog.example.com`) to the `BLOG_TRUSTED_HOSTS` environment variable (comma-separated) and restart; leave it empty to disable the check. The health-check path `/healthz` is exempt from the allowlist, so container probes are unaffected.

**Q: The web container stays unhealthy, or `/healthz` returns 503?**
`/healthz` runs `SELECT 1` against the database; a 503 means the app process is fine but the database is unreachable:
- Compose deployment: check `docker compose logs web` and `docker compose logs db`. During MySQL first-boot initialization the app retries every 3s for up to 90s; if it still fails after that, verify the `BLOG_MYSQL_*` credentials match the db container
- Direct MySQL deployment: confirm the database is running, the account has access to `flask_blog`, `BLOG_DB_TYPE=mysql` is set, and all required fields are present (the app refuses to start rather than silently falling back when fields are missing)

**Q: Permission denied when uploading images or writing SQLite in the container?**
On native Linux Docker, bind-mounted directories are owned by root by default, while the container runs as a non-root user. The image entrypoint [docker-entrypoint.sh](../docker-entrypoint.sh) automatically fixes ownership of `data/`, `static/banner`, `static/uploads`, and `backups/` at startup — rebuild with the latest image. If you customize the image, do not bypass this entrypoint.

**Q: How to apply code changes?**
- Bare-metal: restart the service (`gunicorn` / `python run.py`)
- Docker: `docker compose build web && docker compose --env-file .env.docker --profile full up -d`
- Clear browser cache after template changes

**Q: `docker compose` startup fails with a missing-variable / interpolation error?**
The current compose provides test defaults for the secret key and passwords, so after `cp .env.docker.example .env.docker` you **only need to set `MYSQL_ROOT_PASSWORD` and `MYSQL_PASSWORD`** to start (and SQLite mode `docker compose up -d web` doesn't even need that file). If errors persist, note:
- `docker compose` implicitly reads the root-level `.env`; leftover vars such as `BLOG_DB_TYPE=mysql` in it affect SQLite mode — pass `--env-file` explicitly to override
- The health-based dependency conditions require Docker Compose **v2.20+**; upgrade older versions (the app-level 90s MySQL wait still works as a fallback)

**Q: First startup is slow?**
MySQL initial setup takes 30–60s. Orchestration waits for the `db` container to become `healthy` before starting `web`, and web also probes the database on startup (every 3s, up to 90s) before creating tables. This is expected. Watch progress with `docker compose logs -f db` and `docker compose logs -f web`.

**Q: gunicorn fails to start on Windows?**
gunicorn relies on Unix `fork` and doesn't support Windows. For local runs on Windows use waitress, which is already included in requirements.txt:
```powershell
waitress-serve --listen=127.0.0.1:5000 wsgi:application
```
On Linux / WSL2 / inside Docker keep using gunicorn: `gunicorn -w 4 -b 127.0.0.1:5000 "app:create_app()"`.

**Q: Language switch not working?**
Confirm `.mo` compiled files exist in `translations/`. If `.po` files were modified, run `pybabel compile -d translations` to recompile.

---

Related: [README](../README.md) · [Deployment Guide](DEPLOYMENT.md) · [Project Architecture](ARCHITECTURE.md)
