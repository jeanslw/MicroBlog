# Project Architecture

Directory and module layout of the MicroBlog codebase, including entry points, Flask app factory modules, templates and static assets.

```
MicroBlog/
├── run.py                         # Development entry
├── wsgi.py                        # WSGI deployment entry
├── uwsgi.ini                      # uWSGI config (bare-metal Linux)
├── Dockerfile                     # Docker image build
├── docker-compose.yml             # Multi-container orchestration (web + db + nginx)
├── .dockerignore
├── .env.example                   # Bare-metal env vars template
├── .env.docker.example            # Docker Compose vars template
├── config.py                      # Config (secret key / db type / debug / i18n)
├── requirements.txt               # Python dependencies
├── pytest.ini                     # pytest configuration
├── messages.pot                   # Babel translation template
├── data/                          # SQLite database directory (auto-created)
├── nginx/
│   └── nginx.conf                 # Nginx reverse proxy config (for Docker)
├── MySQL/
│   └── init.sql                   # MySQL schema init script
├── translations/                  # i18n translation files
│   ├── en/LC_MESSAGES/            # English (.po source + .mo compiled)
│   └── zh_CN/LC_MESSAGES/         # Chinese
├── app/
│   ├── __init__.py                # Flask app factory + error handling + global context
│   ├── database.py                # DB initialization + admin/site config auto-creation
│   ├── extensions.py              # db / login_manager / csrf / logging / brute-force protection
│   ├── models.py                  # SQLAlchemy models (Admin/Article/Comment etc.)
│   ├── forms.py                   # Flask-WTF form classes (article/category/login/upload etc.)
│   ├── utils.py                   # HTML sanitization, text extraction, image processing, path utils
│   ├── blog/                      # Blog module (browse/publish/edit/delete)
│   │   ├── routes.py              # Routes
│   │   └── queries.py             # ORM query layer
│   ├── admin/                     # Admin module (login/password/site settings/image upload)
│   ├── banner/                    # Banner module (manage/upload)
│   │   ├── routes.py
│   │   └── queries.py
│   ├── comment/                   # Comment & like module
│   └── main/                      # General routes (language switch/robots.txt)
├── templates/                     # Jinja2 templates
│   ├── base.html                  # Common layout (navbar/footer/background layer/theme switcher/i18n dropdown)
│   ├── error.html                 # Generic error page (404/500 etc.)
│   ├── blog/                      # Index/detail/edit/drafts
│   ├── admin/                     # Login/password/site settings
│   └── banner/                    # Banner management
└── static/
    ├── favicon.ico
    ├── banner/                    # Uploaded banner images (.gitkeep placeholder)
    ├── uploads/                   # Uploaded article images (.gitkeep placeholder)
    ├── css/
    │   └── themes.css             # Background library + glassmorphism UI + style switcher
    ├── js/
    │   └── theme-switcher.js      # Background style switching (localStorage persistence)
    ├── backgrounds/               # Built-in background image library (12 HD images)
    └── lib/                       # Local third-party libs (9 files, listed in the README dependency table)
```

For how to run and configure the application, see the [README](../README.md) and the [Deployment Guide](DEPLOYMENT.md).

---

Related: [README](../README.md) · [Deployment Guide](DEPLOYMENT.md) · [FAQ](FAQ.md)
