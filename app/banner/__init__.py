from flask import Blueprint

banner_bp = Blueprint("banner", __name__)

from . import routes
