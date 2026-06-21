#!/usr/bin/env python3
"""
依赖检测与自动安装脚本

检查并安装 mdnice_publish.py 所需的全部依赖：
- Node.js (MathJax SVG 渲染引擎)
- npm 包 (markdown-it, highlight.js, mathjax-full 等)
- Python 包 (playwright, requests 等)
- Chromium 浏览器 (Playwright 驱动)
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_command(cmd: str) -> bool:
    """检查命令是否可用"""
    return shutil.which(cmd) is not None


def run(cmd: list[str], description: str, cwd: str = None) -> bool:
    """运行命令并打印状态"""
    print(f"  🔧 {description}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            print(f"  ✅ {description} — 完成")
            return True
        else:
            print(f"  ⚠️  {description} — 失败: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  {description} — 超时")
        return False
    except Exception as e:
        print(f"  ⚠️  {description} — 异常: {e}")
        return False


def check_node() -> bool:
    """检查 Node.js 是否已安装"""
    if check_command("node"):
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        print(f"  ✅ Node.js {result.stdout.strip()}")
        return True
    else:
        print("  ❌ Node.js 未安装")
        print("     请安装: https://nodejs.org/ 或 sudo apt install nodejs")
        return False


def check_npm_deps(project_dir: str) -> bool:
    """检查 npm 依赖是否已安装"""
    node_modules = Path(project_dir) / "node_modules"
    if not node_modules.exists():
        print("  ⚠️  node_modules 不存在，正在安装...")
        return run(
            ["npm", "install"],
            "npm install",
            cwd=project_dir,
        )
    else:
        print("  ✅ node_modules 已存在")
        return True


def check_playwright() -> bool:
    """检查 Playwright Python 包"""
    try:
        import importlib
        importlib.import_module("playwright")
        print("  ✅ playwright (Python) 已安装")
        return True
    except ImportError:
        print("  ⚠️  playwright 未安装，正在安装...")
        return run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            "pip install playwright",
        )


def check_chromium() -> bool:
    """检查 Chromium 浏览器是否已安装"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print("  ✅ Chromium 浏览器已安装")
        return True
    except Exception:
        print("  ⚠️  Chromium 未安装，正在安装...")
        return run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            "playwright install chromium",
        )


def check_python_deps(project_dir: str) -> bool:
    """检查 Python 依赖 (requirements.txt)"""
    req_path = Path(project_dir) / "requirements.txt"
    if not req_path.exists():
        print("  ⚠️  requirements.txt 不存在")
        return True  # 不阻塞

    missing = []
    with open(req_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg_name = line.split(">=")[0].split("==")[0].strip()
            try:
                __import__(pkg_name.replace("-", "_"))
            except ImportError:
                missing.append(pkg_name)

    if missing:
        print(f"  ⚠️  缺少 Python 包: {', '.join(missing)}")
        return run(
            [sys.executable, "-m", "pip", "install", "-r", req_path],
            "pip install -r requirements.txt",
        )
    else:
        print("  ✅ Python 依赖已就绪")
        return True


def check_config(project_dir: str) -> bool:
    """检查项目根目录 .env 是否已配置"""
    proj_root = Path(project_dir).resolve()
    env_path = proj_root / ".env"
    env_example = proj_root / ".env.example"

    if not env_path.exists():
        print("  ⚠️  .env 不存在")
        if env_example.exists():
            print(f"     提示: cp {env_example} .env  然后填入密钥")
        return True  # 不阻塞，首次运行会报明确错误

    with open(env_path) as f:
        content = f.read()

    issues = []
    if "NOTION_API_KEY=ntn_xxxxxxxx" in content or "NOTION_API_KEY=your-" in content:
        issues.append("Notion API Key 未配置")
    if "WECHAT_APP_ID=wxXXXXXXXXXXXXXXX" in content or "WECHAT_APP_ID=your-" in content:
        issues.append("微信 App ID 未配置")

    if issues:
        print(f"  ⚠️  密钥未填写: {', '.join(issues)}")
        print(f"     编辑 {env_path} 填入真实密钥")
    else:
        print("  ✅ .env 密钥已配置")

    return True


def main():
    project_dir = os.environ.get(
        "NOTION_PROJECT_DIR",
        str(Path(__file__).resolve().parent.parent),
    )

    print("=" * 55)
    print("📦 依赖检测 — Notion Publisher Skill")
    print("=" * 55)

    results = {}

    # 1. Node.js
    print("\n[1/5] Node.js")
    results["node"] = check_node()

    # 2. npm 依赖
    print("\n[2/5] npm 依赖 (markdown-it, highlight.js, KaTeX...)")
    results["npm"] = check_npm_deps(project_dir) if results["node"] else False

    # 3. Python 依赖
    print("\n[3/5] Python 依赖 (requests, click, pyyaml...)")
    results["python"] = check_python_deps(project_dir)

    # 4. Playwright
    print("\n[4/5] Playwright + Chromium")
    results["playwright"] = check_playwright()
    results["chromium"] = check_chromium() if results["playwright"] else False

    # 5. 配置
    print("\n[5/5] 配置文件")
    results["config"] = check_config(project_dir)

    # 汇总
    print("\n" + "=" * 55)
    all_ok = all(results.values())
    if all_ok:
        print("✅ 全部依赖已就绪！可以开始发布了。")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"⚠️  以下组件未就绪: {', '.join(failed)}")
        print("   请修复以上问题后重试。")

    print("=" * 55)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
