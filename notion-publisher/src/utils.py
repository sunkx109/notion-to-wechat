"""工具函数：日志、配置加载、图片处理"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# 项目根目录: notion-publisher/src/utils.py → notion-publisher/ → 项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 优先从项目根目录加载 .env，不存在则 fallback
ENV_FILE = PROJECT_ROOT / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()  # 兜底：当前工作目录

# 配置 logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("notion2wx")


def load_config(config_path: str = None) -> dict:
    """加载配置：可选 config.yaml 作基底，环境变量优先覆盖。

    优先级: 环境变量 > config.yaml > 内置默认值
    如果 config.yaml 不存在，直接从环境变量构建配置（config_path 传 None）。
    """
    config = {"notion": {}, "wechat": {}}

    # 1. 尝试加载 YAML 配置文件（可选）
    yaml_path = Path(config_path) if config_path else None
    if yaml_path and yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            if loaded:
                config.update(loaded)

    # 2. 环境变量覆盖
    env_overrides = {
        "notion": {"api_key": "NOTION_API_KEY", "database_id": "NOTION_DATABASE_ID"},
        "wechat": {"app_id": "WECHAT_APP_ID", "app_secret": "WECHAT_APP_SECRET"},
    }

    for section, keys in env_overrides.items():
        config.setdefault(section, {})
        for key, env_var in keys.items():
            env_value = os.getenv(env_var)
            if env_value:
                config[section][key] = env_value

    # 3. 检查必要配置
    if not config.get("notion", {}).get("api_key"):
        logger.error(
            "❌ 未配置 NOTION_API_KEY。\n"
            "   请在项目根目录创建 .env 文件:\n"
            f"   cp .env.example .env   # 然后填入你的密钥\n"
            f"   详见: {PROJECT_ROOT}/.env.example"
        )
        sys.exit(1)

    return config


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除非法字符"""
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, "_")
    return filename.strip()[:200]


def ensure_dir(dir_path: str) -> Path:
    """确保目录存在"""
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path
