"""WSGI 入口。

- gunicorn / uWSGI：`gunicorn wsgi:application`
- Vercel Python 运行时（零配置 Flask 检测）：以 `app` 为首选实例名，
  这里用别名指向同一对象，避免两处各自 create_app() 造成重复初始化
  （会重复建表/建管理员、重复连接数据库）。
"""

from app import create_app

application = create_app()
app = application
