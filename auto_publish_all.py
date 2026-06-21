#!/usr/bin/env python3
"""
🤖 Notion → 多平台全自动发布脚本 v2

采用 mdnice 渲染引擎：Notion blocks → Markdown → markdown-it + highlight.js → CSS Inlining

一条命令完成:
  1. 从 Notion 数据库扫描「待发布」文章
  2. 拉取文章内容，下载图片并上传到目标平台
  3. 转为 Markdown → mdnice 主题渲染 → 平台兼容 HTML
  4. 同时推送到微信公众号 + 知乎
  5. 更新 Notion 发布状态

用法:
  python auto_publish_all.py                          # 全自动发布
  python auto_publish_all.py --dry-run                # 预览模式
  python auto_publish_all.py --page-id <id>           # 发布单篇
  python auto_publish_all.py --theme purple           # 使用姹紫主题
  python auto_publish_all.py --skip-wechat             # 仅知乎
  python auto_publish_all.py --skip-zhihu              # 仅微信
  python auto_publish_all.py --no-publish              # 仅草稿

首次使用前:
  1. 复制 .env.example 为 .env，填入所有密钥
  2. npm install                                      # 安装渲染引擎依赖
  3. python auto_publish_all.py --dry-run             # 先预览
  4. python auto_publish_all.py                       # 正式运行
"""

import os
import sys
import time
from pathlib import Path

os.chdir(Path(__file__).parent)

from dotenv import load_dotenv
load_dotenv()

from src.notion_client import NotionClient
from src.wechat_client import WeChatClient
from src.zhihu_client import ZhihuClient
from src.publisher import PublisherV2, convert_json_to_markdown
from src.renderer_bridge import render_markdown
from src.utils import load_config, logger


# ANSI 颜色
class C:
    G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[94m"
    C = "\033[96m"; D = "\033[2m"; X = "\033[0m"; BL = "\033[1m"


def banner():
    print(f"\n{C.C}{C.BL}╔══════════════════════════════════════════╗{C.X}")
    print(f"{C.C}{C.BL}║   🤖 Notion → 多平台自动发布 v2         ║{C.X}")
    print(f"{C.C}{C.BL}║   微信 + 知乎 · mdnice 渲染引擎          ║{C.X}")
    print(f"{C.C}{C.BL}╚══════════════════════════════════════════╝{C.X}\n")


def step(s, msg): print(f"  {C.B}[{s}]{C.X} {msg}")
def ok(msg):      print(f"  {C.G}✅ {msg}{C.X}")
def warn(msg):    print(f"  {C.Y}⚠️  {msg}{C.X}")
def err(msg):     print(f"  {C.R}❌ {msg}{C.X}")
def row(k, v):    print(f"  {C.D}{k}:{C.X} {v}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="🤖 Notion → 多平台全自动发布 v2")
    p.add_argument("--dry-run", action="store_true", help="仅预览")
    p.add_argument("--preview", action="store_true", help="发布前渲染第一篇预览并确认")
    p.add_argument("--page-id", type=str, default=None, help="发布指定页面")
    p.add_argument("--skip-wechat", action="store_true", help="跳过微信")
    p.add_argument("--skip-zhihu", action="store_true", help="跳过知乎")
    p.add_argument("--no-publish", action="store_true", help="仅创建草稿")
    
    p.add_argument("--config", "-c", type=str, default="config.yaml")
    args = p.parse_args()

    banner()
    config = load_config(args.config)

    if args.no_publish:
        config["publish"]["auto_publish"] = False
        config["publish"]["zhihu_as_draft"] = True

    # 初始化客户端
    step("1/5", "初始化客户端...")
    notion = NotionClient(api_key=config.get("notion", {}).get("api_key", ""))
    ok("Notion 已就绪")

    wechat = zhihu = None
    if not args.skip_wechat and config.get("platforms", {}).get("wechat", True):
        try:
            wc = config.get("wechat", {})
            wechat = WeChatClient(app_id=wc.get("app_id", ""), app_secret=wc.get("app_secret", ""))
            _ = wechat.access_token
            ok("微信已就绪")
        except Exception as e:
            warn(f"微信初始化失败: {e}")
    else:
        warn("微信已禁用")

    if not args.skip_zhihu and config.get("platforms", {}).get("zhihu", True):
        try:
            zc = config.get("zhihu", {})
            zhihu = ZhihuClient(cookie_string=zc.get("cookie_string", ""))
            u = zhihu.check_login()
            if u.get("logged_in"):
                ok(f"知乎已就绪 ({u.get('name', '?')})")
            else:
                warn(f"知乎登录失败: {u.get('error', '?')}")
        except Exception as e:
            warn(f"知乎初始化失败: {e}")
    else:
        warn("知乎已禁用")

    if not wechat and not zhihu:
        err("没有可用平台，请检查配置"); sys.exit(1)

    # 创建 PublisherV2
    publisher = PublisherV2(
        notion_client=notion,
        config=config,
        wechat_client=wechat,
        zhihu_client=zhihu,
    )

    step("2/5", "准备发布参数...")
    platforms = []
    if wechat: platforms.append("wechat")
    if zhihu: platforms.append("zhihu")
    
    row("平台", " + ".join(platforms))
    row("模式", "DRY RUN" if args.dry_run else ("草稿" if args.no_publish else "发布"))

    # ── 单页模式 ──
    if args.page_id:
        step("3/5", f"单页发布: {args.page_id}")
        if args.dry_run:
            row("结果", "预览模式，未实际发布")
            return
        result = publisher.publish_to_platforms(args.page_id, platforms=platforms)
        _print_result(result)
        return

    # ── 数据库模式 ──
    step("3/5", "扫描数据库...")
    db_id = config.get("notion", {}).get("database_id", "")
    if not db_id:
        err("未配置 database_id，请用 --page-id 指定单页")
        sys.exit(1)

    fm = config.get("field_mapping", {})
    sf = fm.get("status", "Status")
    pv = fm.get("pending", "待发布")
    row("数据库", db_id[:20] + "...")
    row("筛选", f"{sf} = {pv}")

    pages = notion.query_database(db_id, filter_obj={"property": sf, "status": {"equals": pv}})

    step("4/5", f"找到 {len(pages)} 篇待发布文章")
    if not pages:
        ok("✨ 没有待发布的文章！"); return

    for i, page in enumerate(pages):
        title = ""
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", [])); break
        print(f"  [{i+1}] {title or page['id'][:8]}")

    if args.dry_run:
        print(f"\n  {C.Y}🔍 DRY RUN — 未实际发布{C.X}")
        return

    # ── 预览模式：先渲染第一篇给用户确认 ──
    if args.preview and pages:
        import re
        from datetime import datetime
        first = pages[0]
        page_id = first["id"]
        title = ""
        for prop in first.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", [])); break
        title = title or page_id[:8]

        print(f"\n{C.BL}📋 预览第一篇文章: {title}{C.X}")

        # 拉取 + 转换 + 渲染
        page, blocks = first, notion.get_page_blocks(page_id)
        for block in blocks:
            if block.get("has_children"):
                try: block["_children"] = notion.get_block_children(block["id"])
                except Exception: pass

        md = convert_json_to_markdown({"blocks": blocks})
        html = render_markdown(md, platform="wechat")
        out = f"preview_{title[:20]}_{datetime.now().strftime('%H%M%S')}.html"
        with open(out, "w") as f:
            f.write(html)

        plain = re.sub(r"<[^>]+>", "", html).strip()
        plain = re.sub(r"\s+", " ", plain)
        print(f"   {C.D}正文: {plain[:300]}...{C.X}")
        print(f"   {C.D}HTML: {out} ({len(html):,} 字符){C.X}")
        print(f"   {C.D}💡 浏览器查看: open {out}{C.X}")

        resp = input(f"\n   {C.BL}确认发布全部 {len(pages)} 篇？[y/N] {C.X}")
        if resp.lower() not in ("y", "yes"):
            print(f"   {C.Y}已取消{C.X}"); return

    if not args.preview:
        resp = input(f"\n{C.BL}确认发布全部 {len(pages)} 篇？[y/N] {C.X}")
        if resp.lower() not in ("y", "yes"):
            print(f"{C.Y}已取消{C.X}"); return

    print(f"\n{C.BL}{'─'*50}{C.X}")
    print(f"{C.BL}🚀 开始逐篇发布...{C.X}")

    results = []
    for i, page in enumerate(pages):
        result = publisher.publish_to_platforms(page["id"], platforms=platforms)
        results.append(result)
        _print_result(result)
        if i < len(pages) - 1:
            time.sleep(2)

    # 汇总
    step("5/5", "发布完成")
    wx_ok = sum(1 for r in results if r.get("wechat") and r["wechat"]["success"])
    zh_ok = sum(1 for r in results if r.get("zhihu") and r["zhihu"]["success"])
    print(f"\n{C.BL}╔══════════════════════════════════════════╗{C.X}")
    print(f"{C.BL}║  📊 汇总: 微信 ✅{wx_ok}/{len(results)}  知乎 ✅{zh_ok}/{len(results)}         ║{C.X}")
    print(f"{C.BL}╚══════════════════════════════════════════╝{C.X}\n")


def _print_result(r):
    print(f"\n{C.BL}📝 {r.get('title', '?')}{C.X}")
    wx = r.get("wechat")
    if wx:
        if wx.get("success"):
            print(f"  微信: ✅ draft={wx.get('draft_media_id', '?')[:16]}", end="")
            if wx.get("published"): print(" 已发布", end="")
            print()
        else:
            print(f"  微信: ❌ {wx.get('error', '?')[:80]}")
    zh = r.get("zhihu")
    if zh:
        if zh.get("success"):
            print(f"  知乎: ✅ {zh.get('url', zh.get('article_id', '?'))[:60]}")
        else:
            print(f"  知乎: ❌ {zh.get('error', '?')[:80]}")


if __name__ == "__main__":
    main()
