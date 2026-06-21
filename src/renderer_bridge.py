"""Python 到 Node.js mdnice 渲染器的桥接模块

通过子进程调用 src/renderer.js，传入 Markdown → 输出内联样式 HTML。
"""

import os
import subprocess
from pathlib import Path

from .utils import logger

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RENDERER_SCRIPT = _PROJECT_ROOT / "src" / "renderer.js"


def _check_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def render_markdown(markdown: str, platform: str = "wechat") -> str:
    """将 Markdown 渲染为目标平台的 HTML（单一 mdnice 主题）

    Args:
        markdown: Markdown 文本
        platform: 目标平台 (wechat | zhihu | generic)

    Returns:
        渲染后的 HTML 字符串
    """
    if not _check_node():
        raise RuntimeError(
            "Node.js 不可用。请安装 Node.js（https://nodejs.org）后重试。\n"
            "安装后还需要运行: cd notion-to-wechat && npm install"
        )

    if not _RENDERER_SCRIPT.exists():
        raise RuntimeError(f"渲染脚本不存在: {_RENDERER_SCRIPT}")

    node_modules = _PROJECT_ROOT / "node_modules"
    if not node_modules.exists():
        raise RuntimeError("Node 依赖未安装。请运行: cd notion-to-wechat && npm install")

    try:
        proc = subprocess.run(
            ["node", str(_RENDERER_SCRIPT), "--platform", platform],
            input=markdown,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_PROJECT_ROOT),
        )

        if proc.returncode != 0:
            logger.error(f"渲染器报错:\n{proc.stderr}")
            raise RuntimeError(f"渲染失败: {proc.stderr[:200]}")

        return proc.stdout

    except subprocess.TimeoutExpired:
        raise RuntimeError("渲染超时（30s）")
    except FileNotFoundError:
        raise RuntimeError("Node.js 不可用，请安装 Node.js")
    except Exception as e:
        raise RuntimeError(f"渲染异常: {e}")


def render_markdown_file(input_file: str, platform: str = "wechat", output_file: str = None) -> str:
    """从文件读取 Markdown 并渲染"""
    with open(input_file, "r", encoding="utf-8") as f:
        markdown = f.read()

    html = render_markdown(markdown, platform=platform)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"HTML 已保存到: {output_file}")

    return html
