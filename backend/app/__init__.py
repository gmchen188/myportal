"""
myPortal 后台包。

**在这里加载 .env** —— 各模块（db.py / auth.py / connectors/fortisiem.py）
都在**导入时**读环境变量，所以 .env 必须在它们之前加载。
放在 app/__init__.py 是因为 `import app.db` 会先执行这个文件。

`.env` 在 .gitignore 里，不入库；`.env.example` 是模板。
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
except ImportError:  # 没装 python-dotenv 也不该崩 —— 只是读不到 .env
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv is not None:
    # backend/.env —— 无论从哪个目录启动都用绝对路径
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
