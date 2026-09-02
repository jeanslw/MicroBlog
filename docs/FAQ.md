# Frequently Asked Questions (FAQ)

Troubleshooting and answers for common issues. For setup steps, see the [Deployment Guide](DEPLOYMENT.md).

**Q: Page styles broken?**
Confirm all 9 files in `static/lib/` exist (see the static-asset table in the [README dependencies section](../README.md#3-dependencies)).

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
Passwords are stored as `generate_password_hash` hashes — **plaintext passwords cannot log in**. Reset `BLOG_INIT_ADMIN_PWD` and restart, or in a Python shell:
```python
from werkzeug.security import generate_password_hash
from app.models import Admin
from app.extensions import db

# Execute within app context
admin = db.session.query(Admin).filter_by(username="admin").first()
admin.password = generate_password_hash("new-password")
db.session.commit()
```

**Q: How to apply code changes?**
- Bare-metal: restart the service (`gunicorn` / `python run.py`)
- Docker: `docker compose build web && docker compose --env-file .env.docker --profile full up -d`
- Clear browser cache after template changes

**Q: `docker compose` startup fails with `must be set in .env.docker`?**
`.env.docker` was not created or required vars are missing. Run `cp .env.docker.example .env.docker`, then fill in required variables.

**Q: First startup is slow?**
MySQL initial setup takes 30–60s; `web` only starts after `db` becomes `healthy`. Use `docker compose logs -f db` to watch progress.

**Q: Language switch not working?**
Confirm `.mo` compiled files exist in `translations/`. If `.po` files were modified, run `pybabel compile -d translations` to recompile.

---

Related: [README](../README.md) · [Deployment Guide](DEPLOYMENT.md) · [Project Architecture](ARCHITECTURE.md)
