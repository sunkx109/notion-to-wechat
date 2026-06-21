#!/usr/bin/env python3
"""Notion → 多平台 自动发布工具 v2 (mdnice 渲染引擎)

支持: 微信公众号, 知乎

用法:
  python main.py fetch <page_id>         拉取 Notion 页面
  python main.py preview <page_id>       预览渲染效果（先看再发）
  python main.py convert <input.md>      将 Markdown 转换为 HTML 预览
  python main.py publish <page_id>       一键发布到微信
  python main.py publish-zhihu <page-id> 一键发布到知乎
  python main.py publish-all <page-id>   同时发布到微信 + 知乎
  python main.py list-drafts            查看微信草稿
  python main.py publish-draft <id>     发布指定微信草稿
  python main.py zhihu-login            验证知乎 Cookie
  python main.py auto                    自动扫描数据库并发布
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from src.notion_client import NotionClient
from src.wechat_client import WeChatClient
from src.zhihu_client import ZhihuClient
from src.converter import _notion_file_url
from src.renderer_bridge import render_markdown
from src.publisher import PublisherV2, fetch_page_to_json, convert_json_to_markdown
from src.utils import load_config, logger


@click.group()
@click.option("--config", "-c", "config_path", default="config.yaml", help="配置文件路径")
@click.pass_context
def cli(ctx, config_path):
    """Notion → 多平台 自动发布工具 v2 (mdnice 渲染)"""
    ctx.ensure_object(dict)
    config = load_config(config_path)
    ctx.obj["config"] = config

    notion_key = config.get("notion", {}).get("api_key", "")
    if not notion_key or "your-" in str(notion_key):
        click.echo("❌ 请先配置 Notion API Key", err=True)
        sys.exit(1)
    ctx.obj["notion"] = NotionClient(api_key=notion_key)

    ctx.obj["wechat"] = None
    wc = config.get("wechat", {})
    if wc.get("app_id") and "your-" not in str(wc.get("app_id")):
        try:
            ctx.obj["wechat"] = WeChatClient(app_id=wc["app_id"], app_secret=wc.get("app_secret", ""))
        except Exception as e:
            click.echo(f"⚠️  微信初始化失败: {e}", err=True)

    ctx.obj["zhihu"] = None
    zc = config.get("zhihu", {})
    if zc.get("cookie_string") and "your-" not in str(zc.get("cookie_string")):
        try:
            ctx.obj["zhihu"] = ZhihuClient(cookie_string=zc["cookie_string"])
        except Exception as e:
            click.echo(f"⚠️  知乎初始化失败: {e}", err=True)

    ctx.obj["publisher"] = PublisherV2(
        notion_client=ctx.obj["notion"],
        config=config,
        wechat_client=ctx.obj.get("wechat"),
        zhihu_client=ctx.obj.get("zhihu"),
    )


def _fetch_page_data(notion, page_id):
    page = notion.get_page(page_id)
    blocks = notion.get_page_blocks(page_id)
    for block in blocks:
        if block.get("has_children"):
            try:
                block["_children"] = notion.get_block_children(block["id"])
            except Exception:
                pass
    title = ""
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in p.get("title", []))
            break
    return page, blocks, title or page_id[:8]


# ═══════════════════════════════════════════
# 命令
# ═══════════════════════════════════════════

@cli.command()
@click.argument("page_id")
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.option("--format", "-f", "fmt", type=click.Choice(["json", "md"]), default="json")
@click.pass_context
def fetch(ctx, page_id, output, fmt):
    """拉取 Notion 页面"""
    notion = ctx.obj["notion"]
    page, blocks, title = _fetch_page_data(notion, page_id)
    click.echo(f"\n📄 页面: {title}")
    if fmt == "md":
        md = convert_json_to_markdown({"blocks": blocks})
        out = output or f"page_{page_id[:8]}.md"
        with open(out, "w") as f: f.write(md)
        click.echo(f"✅ Markdown → {out}")
    else:
        out = output or f"page_{page_id[:8]}.json"
        with open(out, "w") as f: json.dump({"page": page, "blocks": blocks}, f, ensure_ascii=False, indent=2)
        click.echo(f"✅ JSON → {out}")


@cli.command()
@click.argument("input_file")
@click.option("-o", "--output", default=None, help="输出 HTML 文件路径")
@click.option("--platform", default="wechat", type=click.Choice(["wechat", "zhihu", "generic"]))
@click.pass_context
def convert(ctx, input_file, output, platform):
    """将 Markdown/JSON 转换为 HTML 预览"""
    with open(input_file, "r") as f:
        content = f.read()
    if input_file.endswith(".json"):
        md = convert_json_to_markdown(json.loads(content))
    else:
        md = content

    click.echo(f"📝 渲染中 (平台: {platform})...")
    html = render_markdown(md, platform=platform)
    if output:
        with open(output, "w") as f: f.write(html)
        click.echo(f"✅ HTML → {output} ({len(html):,} 字符)")
    else:
        click.echo("\n" + "=" * 60)
        click.echo(html[:5000])
        if len(html) > 5000:
            click.echo(f"\n... (共 {len(html):,} 字符，用 -o 保存)")


@cli.command()
@click.argument("page_id")
@click.option("-o", "--output", default=None, help="输出文件前缀（默认用标题）")
@click.option("--open", "open_browser", is_flag=True, help="在浏览器中打开 HTML 预览")
@click.pass_context
def export(ctx, page_id, output, open_browser):
    """导出 Notion 文章: 生成 Markdown + HTML 预览文件

    Markdown → 可粘贴到 mdnice.com 获得完美主题
    HTML    → 可在浏览器打开后复制粘贴到微信公众号
    """
    import webbrowser, re
    from datetime import datetime

    notion = ctx.obj["notion"]
    click.echo(f"\n📥 拉取 Notion 页面...")
    page = notion.get_page(page_id)
    blocks = notion.get_page_blocks(page_id)
    for b in blocks:
        if b.get("has_children"):
            try: b["_children"] = notion.get_block_children(b["id"])
            except: pass

    title = ""
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in p.get("title", [])); break
    title = title or page_id[:8]
    safe = re.sub(r"[^\w一-鿿]", "_", title)[:30]

    prefix = output or f"export_{safe}"

    # 1. 导出 Markdown
    md = convert_json_to_markdown({"blocks": blocks})
    md_path = f"{prefix}.md"
    with open(md_path, "w") as f: f.write(md)
    click.echo(f"  📝 Markdown → {md_path} ({len(md):,} 字符)")

    # 2. 渲染 HTML
    html = render_markdown(md, platform="wechat")
    html_path = f"{prefix}.html"
    with open(html_path, "w") as f: f.write(html)
    click.echo(f"  🎨 HTML    → {html_path} ({len(html):,} 字符)")

    # 3. 输出用法
    click.echo(f"\n{'─' * 50}")
    click.echo(f"📋 两种发布方式:")
    click.echo(f"")
    click.echo(f"  方式A — mdnice 完美主题:")
    click.echo(f"    1. 打开 {md_path}")
    click.echo(f"    2. 全选复制 → 粘贴到 mdnice.com")
    click.echo(f"    3. 在 mdnice 选择主题 → 点「复制」")
    click.echo(f"    4. 粘贴到微信公众号编辑器")
    click.echo(f"")
    click.echo(f"  方式B — 浏览器直接复制:")
    click.echo(f"    1. 打开 {html_path}")
    click.echo(f"    2. 浏览器中 Ctrl+A 全选 → Ctrl+C 复制")
    click.echo(f"    3. 粘贴到微信公众号编辑器")
    click.echo(f"{'─' * 50}")

    if open_browser:
        webbrowser.open(f"file://{Path(html_path).resolve()}")


@cli.command()
@click.argument("page_id")
@click.option("-o", "--output", default=None, help="输出 HTML 文件路径")
@click.option("--open", "open_browser", is_flag=True, help="在浏览器中打开预览")
@click.option("--publish", "then_publish", is_flag=True, help="预览确认后直接发布")
@click.pass_context
def preview(ctx, page_id, output, open_browser, then_publish):
    """预览渲染效果 — 拉取 Notion → 渲染 → 保存本地 HTML"""
    import webbrowser

    notion = ctx.obj["notion"]
    click.echo(f"\n🔍 预览模式")
    click.echo("─" * 40)

    click.echo("  📥 拉取 Notion 页面...")
    page = notion.get_page(page_id)
    blocks = notion.get_page_blocks(page_id)
    for block in blocks:
        if block.get("has_children"):
            try: block["_children"] = notion.get_block_children(block["id"])
            except Exception: pass

    title = ""
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in p.get("title", [])); break
    if not title: title = page_id[:8]

    click.echo(f"  📄 标题: {title}  |  Blocks: {len(blocks)}")

    md = convert_json_to_markdown({"blocks": blocks})
    click.echo(f"  📝 Markdown: {len(md)} 字符")

    click.echo(f"  🎨 渲染中...")
    html = render_markdown(md, platform="wechat")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w一-鿿]", "_", title)[:30]
    out = output or f"preview_{safe}_{ts}.html"
    with open(out, "w") as f: f.write(html)
    click.echo(f"  💾 已保存: {out} ({len(html):,} 字符)")

    plain = re.sub(r"<[^>]+>", "", html).strip()
    plain = re.sub(r"\s+", " ", plain)
    click.echo(f"\n{'─' * 40}\n📋 正文预览:\n{'─' * 40}")
    click.echo(plain[:500])
    if len(plain) > 500: click.echo(f"... (共 {len(plain):,} 字符)")

    click.echo(f"\n💡 浏览器查看: open {out}")
    if open_browser:
        webbrowser.open(f"file://{Path(out).resolve()}")

    if then_publish:
        if click.confirm("\n🚀 确认发布？"):
            result = ctx.obj["publisher"].publish_to_platforms(page_id)
            for plat in ["wechat", "zhihu"]:
                r = result.get(plat)
                if r: click.echo(f"  {plat}: {'✅' if r.get('success') else '❌'}")


@cli.command(name="publish")
@click.argument("page_id")
@click.option("--preview", "do_preview", is_flag=True, help="先预览再发布")
@click.pass_context
def publish_wx(ctx, page_id, do_preview):
    """发布到微信公众号"""
    publisher = ctx.obj["publisher"]
    if not ctx.obj.get("wechat"):
        click.echo("❌ 微信未配置", err=True); sys.exit(1)
    if do_preview:
        _preview_then_confirm(ctx, page_id, "微信")

    click.echo(f"\n🚀 发布到微信...")
    result = publisher.publish_to_platforms(page_id, platforms=["wechat"])
    wx = result.get("wechat", {})
    if wx.get("success"):
        click.echo(f"✅ 草稿: {wx['draft_media_id']}")
        if wx.get("published"): click.echo(f"   📤 已发布")
    else:
        click.echo(f"❌ {wx.get('error', '失败')}")


@cli.command(name="publish-zhihu")
@click.argument("page_id")
@click.option("--preview", "do_preview", is_flag=True, help="先预览再发布")
@click.pass_context
def publish_zh(ctx, page_id, do_preview):
    """发布到知乎"""
    publisher = ctx.obj["publisher"]
    if not ctx.obj.get("zhihu"):
        click.echo("❌ 知乎未配置", err=True); sys.exit(1)
    if do_preview:
        _preview_then_confirm(ctx, page_id, "知乎")

    click.echo(f"\n🚀 发布到知乎...")
    result = publisher.publish_to_platforms(page_id, platforms=["zhihu"])
    zh = result.get("zhihu", {})
    if zh.get("success"):
        click.echo(f"✅ {zh.get('url', zh['article_id'])}")
    else:
        click.echo(f"❌ {zh.get('error', '失败')}")


@cli.command(name="publish-all")
@click.argument("page_id")
@click.option("--preview", "do_preview", is_flag=True, help="先预览再发布")
@click.pass_context
def publish_all(ctx, page_id, do_preview):
    """同时发布到微信 + 知乎"""
    publisher = ctx.obj["publisher"]
    if do_preview:
        _preview_then_confirm(ctx, page_id, "微信+知乎")

    click.echo(f"\n🚀 多平台发布...")
    result = publisher.publish_to_platforms(page_id)
    for plat, label in [("wechat", "微信"), ("zhihu", "知乎")]:
        r = result.get(plat)
        if r: click.echo(f"  {label}: {'✅' if r.get('success') else '❌'}")
    click.echo("✅ 完成")


def _preview_then_confirm(ctx, page_id, platform_name):
    """辅助: 预览 HTML 并确认"""
    notion = ctx.obj["notion"]
    page, blocks, title = _fetch_page_data(notion, page_id)
    md = convert_json_to_markdown({"blocks": blocks})
    html = render_markdown(md, platform="wechat")
    out = f"preview_{re.sub(r'[^\w一-鿿]', '_', title)[:20]}_{datetime.now().strftime('%H%M%S')}.html"
    with open(out, "w") as f: f.write(html)
    plain = re.sub(r"<[^>]+>", "", html).strip()
    plain = re.sub(r"\s+", " ", plain)
    click.echo(f"\n📋 预览 ({platform_name}): {title}")
    click.echo(f"   正文: {plain[:300]}...")
    click.echo(f"   HTML: {out}  |  💡 open {out}")
    if not click.confirm(f"   确认发布到 {platform_name}？"):
        click.echo("   已取消"); ctx.exit(0)


@cli.command(name="zhihu-login")
@click.pass_context
def zhihu_login(ctx):
    """验证知乎 Cookie"""
    zhihu = ctx.obj.get("zhihu")
    if not zhihu:
        click.echo("❌ 知乎未配置", err=True); sys.exit(1)
    click.echo("🔍 验证知乎...")
    user = zhihu.check_login()
    if user.get("logged_in"):
        click.echo(f"✅ {user['name']} ({user.get('headline', '')})")
    else:
        click.echo(f"❌ {user.get('error', '?')}")
        click.echo("💡 登录知乎 → F12 → document.cookie → 粘贴到 ZHIHU_COOKIE")


@cli.command(name="list-drafts")
@click.option("--offset", default=0)
@click.option("--count", default=10)
@click.pass_context
def list_drafts(ctx, offset, count):
    """微信草稿列表"""
    wechat = ctx.obj.get("wechat")
    if not wechat: click.echo("❌ 微信未配置"); return
    drafts = wechat.list_drafts(offset=offset, count=count)
    if not drafts: click.echo("📭 草稿箱为空"); return
    click.echo(f"\n📋 微信草稿 ({len(drafts)} 条):")
    for item in drafts:
        news = item.get("content", {}).get("news_item", [{}])[0]
        click.echo(f"  [{item['media_id']}] {news.get('title', '无标题')}")


@cli.command(name="publish-draft")
@click.argument("media_id")
@click.pass_context
def publish_draft(ctx, media_id):
    """发布指定微信草稿"""
    wechat = ctx.obj.get("wechat")
    if not wechat: click.echo("❌ 微信未配置"); return
    pid = wechat.publish(media_id)
    click.echo(f"✅ {pid}" if pid else "❌ 失败")


@cli.command()
@click.option("--dry-run", is_flag=True, help="仅列出文章")
@click.option("--preview", "do_preview", is_flag=True, help="先预览第一篇")
@click.option("--skip-wechat", is_flag=True)
@click.option("--skip-zhihu", is_flag=True)
@click.pass_context
def auto(ctx, dry_run, do_preview, skip_wechat, skip_zhihu):
    """自动扫描数据库中的待发布文章并多平台发布"""
    publisher = ctx.obj["publisher"]
    config = ctx.obj["config"]
    db_id = config.get("notion", {}).get("database_id", "")
    notion = ctx.obj["notion"]
    if not db_id: click.echo("❌ 未配置 database_id"); sys.exit(1)

    fm = config.get("field_mapping", {})
    sf, pv = fm.get("status", "Status"), fm.get("pending", "待发布")
    click.echo(f"\n🔍 搜索: {sf} = {pv}")
    pages = notion.query_database(db_id, filter_obj={"property": sf, "status": {"equals": pv}})
    click.echo(f"📚 找到 {len(pages)} 篇:\n")
    for i, page in enumerate(pages):
        title = ""
        for p in page.get("properties", {}).values():
            if p.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in p.get("title", [])); break
        click.echo(f"  [{i+1}] {title or page['id'][:8]}")

    if dry_run: click.echo(f"\n🔍 Dry run"); return

    if do_preview and pages:
        first = pages[0]
        pid = first["id"]
        title = ""
        for p in first.get("properties", {}).values():
            if p.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in p.get("title", [])); break
        click.echo(f"\n📋 预览第一篇: {title}")
        page, blocks, _ = _fetch_page_data(notion, pid)
        md = convert_json_to_markdown({"blocks": blocks})
        html = render_markdown(md, platform="wechat")
        out = f"preview_{re.sub(r'[^\w一-鿿]', '_', title)[:20]}_{datetime.now().strftime('%H%M%S')}.html"
        with open(out, "w") as f: f.write(html)
        plain = re.sub(r"<[^>]+>", "", html).strip()
        plain = re.sub(r"\s+", " ", plain)
        click.echo(f"   正文: {plain[:300]}...")
        click.echo(f"   HTML: {out}  |  💡 open {out}")
        if not click.confirm(f"   确认发布全部 {len(pages)} 篇？"):
            click.echo("   已取消"); return

    if not do_preview:
        if not click.confirm(f"\n⚠️  发布 {len(pages)} 篇？"):
            click.echo("已取消"); return

    platforms = []
    if not skip_wechat and ctx.obj.get("wechat"): platforms.append("wechat")
    if not skip_zhihu and ctx.obj.get("zhihu"): platforms.append("zhihu")

    for i, page in enumerate(pages):
        click.echo(f"\n[{i+1}/{len(pages)}] 处理中...")
        publisher.publish_to_platforms(page["id"], platforms=platforms)
        if i < len(pages) - 1: time.sleep(2)
    click.echo(f"\n✅ 完成")


if __name__ == "__main__":
    cli()
