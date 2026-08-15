from flask import Blueprint

blog_bp = Blueprint("blog", __name__)

from . import routes  # noqa: E402, F401  # 底部导入用于注册路由，避免循环导入
