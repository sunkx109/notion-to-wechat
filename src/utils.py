"""工具函数：日志、配置加载、图片处理"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 配置 logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("notion2wx")


def load_config(config_path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件，并用环境变量替换敏感值"""
    path = Path(config_path)
    if not path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 环境变量覆盖
    env_overrides = {
        "notion": {"api_key": "NOTION_API_KEY", "database_id": "NOTION_DATABASE_ID"},
        "wechat": {"app_id": "WECHAT_APP_ID", "app_secret": "WECHAT_APP_SECRET"},
        "zhihu": {"cookie_string": "ZHIHU_COOKIE"},
    }

    for section, keys in env_overrides.items():
        if section not in config:
            config[section] = {}
        for key, env_var in keys.items():
            env_value = os.getenv(env_var)
            if env_value:
                config[section][key] = env_value

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
