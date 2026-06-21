#!/usr/bin/env python3
"""
Notion 文章导出工具

用法:
  python notion_export.py fetch <page_id>          拉取 Notion 页面 → Markdown
  python notion_export.py export <page_id>         拉取 + 保存 Markdown 文件

完整发布流程请用: python mdnice_publish.py <notion-url>
"""

import json
import re
import sys
from pathlib import Path

import click

# 技能目录（notion-publisher/）
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.notion_client import NotionClient
from src.notion2md import convert_json_to_markdown
from src.utils import load_config, logger


@click.group()
@click.option("--config", "-c", "config_path", default=None, help="配置文件路径")
@click.pass_context
def cli(ctx, config_path):
    """Notion 文章导出工具"""
    ctx.ensure_object(dict)
    cfg_path = config_path or str(ROOT / "config.yaml")
    config = load_config(cfg_path)
    ctx.obj["config"] = config

    notion_key = config.get("notion", {}).get("api_key", "")
    if not notion_key or "your-" in str(notion_key):
        click.echo("❌ 请先配置 Notion API Key", err=True)
        sys.exit(1)
    ctx.obj["notion"] = NotionClient(api_key=notion_key)


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


@cli.command()
@click.argument("page_id")
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.pass_context
def fetch(ctx, page_id, output):
    """拉取 Notion 页面，保存为 Markdown"""
    notion = ctx.obj["notion"]
    page, blocks, title = _fetch_page_data(notion, page_id)
    click.echo(f"\n📄 页面: {title}  |  {len(blocks)} blocks")

    safe = re.sub(r"[^\w一-鿿]", "_", title)[:30]
    out_dir = ROOT / "mds" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    md = convert_json_to_markdown({"blocks": blocks})
    out = output or str(out_dir / "article.md")
    with open(out, "w") as f:
        f.write(md)
    click.echo(f"✅ Markdown → {out}  ({len(md):,} 字符)")


@cli.command()
@click.argument("page_id")
@click.option("-o", "--output", default=None, help="输出文件路径")
@click.pass_context
def export(ctx, page_id, output):
    """拉取 Notion 页面，导出 Markdown 到 mds/ 目录"""
    notion = ctx.obj["notion"]
    page, blocks, title = _fetch_page_data(notion, page_id)
    click.echo(f"\n📄 页面: {title}  |  {len(blocks)} blocks")

    safe = re.sub(r"[^\w一-鿿]", "_", title)[:30]
    out_dir = ROOT / "mds" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    md = convert_json_to_markdown({"blocks": blocks})
    out = output or str(out_dir / "article.md")
    with open(out, "w") as f:
        f.write(md)
    click.echo(f"✅ Markdown → {out}  ({len(md):,} 字符)")
    click.echo(f"\n💡 下一步: python scripts/mdnice_publish.py --md-file {out} \"{title}\"")


if __name__ == "__main__":
    cli()
