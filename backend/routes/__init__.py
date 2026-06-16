"""路由蓝图注册"""
from flask import Blueprint

auth_bp = Blueprint("auth", __name__)
fund_bp = Blueprint("fund", __name__)
analysis_bp = Blueprint("analysis", __name__)
portfolio_bp = Blueprint("portfolio", __name__)
ai_bp = Blueprint("ai", __name__)

# 尝试导入已存在的蓝图模块
try:
    from . import auth
except ImportError:
    pass
