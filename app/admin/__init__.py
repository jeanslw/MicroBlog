from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

from . import routes  # noqa: E402, F401  # 底部导入用于注册路由，避免循环导入
