#!/usr/bin/env python3
"""
Notion → mdnice → 微信公众号 全自动发布

流程:
  1. 从 Notion 拉取页面 → 导出 Markdown
  2. 图片下载到本地 + 上传微信 CDN
  3. mdnice.com: 新建文章 → 粘贴 Markdown → 渲染 → 提取 HTML
  4. 微信 Draft API: 直接创建草稿（保留全部格式 + 图片）

前置条件:
  - Notion API Key (config.yaml / .env)
  - mdnice 登录 Cookie（首次自动扫码，Cookie 持久化）
  - 微信公众平台 AppID/AppSecret（config.yaml / .env）

用法:
  # 方式一：直接贴 Notion 链接
  python scripts/mdnice_publish.py https://www.notion.so/sunkx109/Title-1af24043556480cfad2dc64212758475

  # 方式二：标题 + page_id
  python scripts/mdnice_publish.py "文章标题" <notion-page-id>

  # 跳过 mdnice 渲染，直接发布已有 Markdown 文件
  python scripts/mdnice_publish.py --md-file article.md "文章标题"

  # 仅渲染，不发布
  python scripts/mdnice_publish.py --dry-run "文章标题" <notion-page-id>
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# 技能目录（notion-publisher/）
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def get_markdown_and_images(page_id: str) -> tuple[str, str, list[tuple[str, str]]]:
    """从 Notion 拉取页面，导出 Markdown，同时下载所有图片到本地。
    返回 (markdown, title, [(original_url, local_path), ...])
    """
    from src.notion_client import NotionClient
    from src.utils import load_config

    config = load_config(str(ROOT / "config.yaml"))
    notion = NotionClient(api_key=config["notion"]["api_key"])

    page = notion.get_page(page_id)
    blocks = notion.get_page_blocks(page_id)
    for b in blocks:
        if b.get("has_children"):
            try:
                b["_children"] = notion.get_block_children(b["id"])
            except Exception:
                pass

    title = ""
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            title = "".join(t.get("plain_text", "") for t in p.get("title", []))
            break
    title = title or page_id[:8]

    from src.notion2md import convert_json_to_markdown

    md = convert_json_to_markdown({"blocks": blocks})

    # 提取所有图片 URL
    def extract_images(blist):
        result = []
        for b in blist:
            if b.get("type") == "image":
                url = (
                    b.get("image", {}).get("file", {}).get("url")
                    or b.get("image", {}).get("external", {}).get("url")
                )
                if url:
                    result.append(url)
            if b.get("_children"):
                result.extend(extract_images(b["_children"]))
        return result

    image_urls = extract_images(blocks)

    # 下载图片到本地 mds/<title>/images/
    safe_title = re.sub(r"[^\w一-鿿]", "_", title)[:30]
    article_dir = ROOT / "mds" / safe_title
    img_dir = article_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 保存 Markdown 到 mds/<title>/article.md
    md_path = article_dir / "article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"   📄 Markdown → {md_path}")

    image_pairs = []
    local_rel_paths = []  # 相对于 article.md 的图片路径
    for i, url in enumerate(image_urls):
        try:
            resp = requests.get(url, timeout=30)
            ext = ".png"
            ct = resp.headers.get("content-type", "")
            if "jpeg" in ct or "jpg" in ct:
                ext = ".jpg"
            elif "gif" in ct:
                ext = ".gif"
            local_path = str(img_dir / f"img_{i:02d}{ext}")
            with open(local_path, "wb") as f:
                f.write(resp.content)
            image_pairs.append((url, local_path))
            local_rel_paths.append(f"images/img_{i:02d}{ext}")
            print(f"   📥 图片 {i}: {len(resp.content):,} bytes → {local_path}")
        except Exception as e:
            print(f"   ⚠️  图片 {i} 下载失败: {e}")
            local_rel_paths.append("")  # 占位，保持索引一致

    # 在 Markdown 中用相对路径替换 Notion 图片 URL → 保存
    md_for_file = md
    for i, (url, _) in enumerate(image_pairs):
        rel = local_rel_paths[i]
        if not rel:
            continue
        pattern = rf"!\[([^\]]*)\]\({re.escape(url)}\)"
        if re.search(pattern, md_for_file):
            md_for_file = re.sub(pattern, rf"![\1]({rel})", md_for_file)
        else:
            md_for_file = md_for_file.replace(url, rel)

    # 保存 Markdown 到 mds/<title>/article.md（含相对路径图片）
    md_path = article_dir / "article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_for_file)
    print(f"   📄 Markdown → {md_path}")

    return md, title, image_pairs


def replace_images_with_placeholders(
    markdown: str, image_pairs: list[tuple[str, str]]
) -> str:
    """将 Markdown 中的 Notion 图片 URL 替换为占位文本 [📷 图N]，
    供 mdnice 渲染（mdnice 无法访问本地相对路径）。
    导出的 article.md 用的是相对路径，与此无关。
    """
    for i, (url, local_path) in enumerate(image_pairs):
        placeholder = f"[📷 图{i}]"
        # 匹配 Markdown 图片语法: ![caption](url)
        pattern = rf"!\[[^\]]*\]\({re.escape(url)}\)"
        if re.search(pattern, markdown):
            markdown = re.sub(pattern, placeholder, markdown)
        else:
            markdown = markdown.replace(url, placeholder)
    return markdown


def get_markdown(page_id: str) -> tuple[str, str]:
    """从 Notion 拉取页面并导出 Markdown。返回 (markdown, title)。
    兼容旧接口，无图片下载功能。
    """
    md, title, _ = get_markdown_and_images(page_id)
    return md, title


# ═══════════════════════════════════════════════════════════════
# 登录辅助
# ═══════════════════════════════════════════════════════════════

QR_DIR = ROOT / "login_img"
QR_DIR.mkdir(exist_ok=True)

LOGIN_URLS = {
    "wechat": {
        "url": "https://mp.weixin.qq.com/",
        "storage": str(ROOT / "wechat_storage.json"),
        "qr_file": str(QR_DIR / "wechat_qr.png"),
        "success_check": "/cgi-bin/home",
    },
    "mdnice": {
        "url": "https://editor.mdnice.com/",
        "storage": str(ROOT / "mdnice_storage.json"),
        "qr_file": str(QR_DIR / "mdnice_qr.png"),
        "success_check": None,
        "success_text": "微信扫码登录",
    },
}


async def login(platform: str):
    """登录指定平台：展示二维码 → 等待扫码 → 自动刷新过期二维码 → 循环直到成功"""
    cfg = LOGIN_URLS[platform]
    if os.path.exists(cfg["storage"]):
        print(f"✅ {cfg['storage']} 已存在，使用已保存的登录状态。")
        print(f"   如需重新登录，请先删除此文件。")
        return

    print(f"\n{'='*60}")
    print(f"🔐 需要登录 {platform.upper()}")
    print(f"{'='*60}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080}, locale="zh-CN"
        )
        page = await context.new_page()

        round_num = 0
        while True:
            round_num += 1
            if round_num > 1:
                print(f"\n🔄 二维码可能已过期，刷新页面获取新二维码...")
                await page.reload(wait_until="networkidle")
                await asyncio.sleep(3)
            else:
                await page.goto(cfg["url"], wait_until="networkidle", timeout=60000)
                await asyncio.sleep(5)

            # 保存截图（含二维码）
            await page.screenshot(path=cfg["qr_file"], full_page=True)
            print(f"\n📱 二维码已保存: {cfg['qr_file']}")
            print(f"   👆 请用微信扫描截图中的二维码")
            print(f"⏳ 等待扫码中...（每 10 秒检测一次，二维码过期会自动刷新）")

            # 轮询检测登录状态
            for attempt in range(12):  # 每轮最多等 120 秒
                await asyncio.sleep(10)

                # 检查是否已登录
                logged_in = False
                try:
                    if cfg["success_check"]:
                        logged_in = cfg["success_check"] in page.url
                    else:
                        body = await page.evaluate("() => document.body.innerText")
                        logged_in = cfg["success_text"] not in body
                except Exception:
                    pass

                if logged_in:
                    print(f"\n✅ 扫码成功！登录 {platform}")
                    await asyncio.sleep(3)
                    await context.storage_state(path=cfg["storage"])
                    print(f"💾 Cookie 已保存: {cfg['storage']}")
                    await browser.close()
                    return

                elapsed = (attempt + 1) * 10
                print(f"   ⏱️  已等待 {elapsed}s，尚未扫码...")

        await browser.close()


# ═══════════════════════════════════════════════════════════════
# 微信编辑器图片插入
# ═══════════════════════════════════════════════════════════════


async def _find_image_input_selector(page_wx) -> str:
    """找到微信编辑器中图片上传用的 <input type=file> 的 selector。"""
    result = await page_wx.evaluate("""() => {
        const inputs = document.querySelectorAll('input[type="file"]');
        for (const inp of inputs) {
            const accept = (inp.accept || '').toLowerCase();
            if (accept.includes('image') || accept.includes('png') || accept.includes('jpg')) {
                // 返回唯一定位符
                if (inp.id) return '#' + inp.id;
                if (inp.name) return 'input[name="' + inp.name + '"]';
                const cls = (inp.className || '').trim();
                if (cls) return 'input.' + cls.split(' ').join('.');
                return 'input[type="file"]';
            }
        }
        return '';
    }""")
    return result


async def insert_images_to_wechat_editor(page_wx, image_pairs: list[tuple[str, str]]):
    """在微信编辑器中按序插入本地图片，替换 [📷 图N] 占位符。

    流程：选中占位文本 → Backspace 删除 → 上传图片到 file input → 编辑器自动插入
    """

    # —— 先找图片文件 input ——
    img_input_sel = await _find_image_input_selector(page_wx)
    if not img_input_sel:
        print("   ❌ 未找到微信编辑器的图片上传 input，跳过图片插入")
        print("   💡 图片已保存到 images/ 目录，可在草稿箱手动插入")
        return
    print(f"   🔍 图片上传 input: {img_input_sel}")

    img_input = page_wx.locator(img_input_sel)

    for i, (notion_url, local_path) in enumerate(image_pairs):
        if not os.path.exists(local_path):
            print(f"   ⚠️  图片文件不存在: {local_path}")
            continue

        placeholder = f"[📷 图{i}]"
        print(f"   🖼️  处理 {placeholder}...")

        # 1. 在 ProseMirror 编辑器中找到占位符并选中
        found = await page_wx.evaluate(
            """(ph) => {
                const editors = document.querySelectorAll('.ProseMirror[contenteditable="true"]');
                const e = editors[1] || editors[0];
                if (!e) return false;

                const text = e.textContent || '';
                const idx = text.indexOf(ph);
                if (idx === -1) return false;

                const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
                let currentPos = 0;
                let targetNode = null, targetOffset = 0;
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    const nodeText = node.textContent || '';
                    if (currentPos + nodeText.length > idx && !targetNode) {
                        targetNode = node;
                        targetOffset = idx - currentPos;
                        break;
                    }
                    currentPos += nodeText.length;
                }
                if (!targetNode) return false;

                const range = document.createRange();
                range.setStart(targetNode, targetOffset);
                range.setEnd(targetNode, targetOffset + ph.length);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);

                targetNode.parentElement?.scrollIntoView({block: 'center'});
                return true;
            }""",
            placeholder,
        )

        if not found:
            print(f"      ⚠️  占位符未找到，跳过")
            continue

        await asyncio.sleep(0.3)

        # 2. 删除占位符文本
        await page_wx.keyboard.press("Backspace")
        await asyncio.sleep(0.2)

        # 3. 直接通过 file input 上传图片（编辑器会自动在光标位置插入）
        try:
            await img_input.set_input_files(local_path)
        except Exception as e:
            print(f"      ⚠️  上传失败: {e}")
            # 恢复占位符
            await page_wx.keyboard.press("Control+z")
            await asyncio.sleep(0.3)
            continue

        # 4. 等待上传完成
        await asyncio.sleep(3)
        img_count = await page_wx.evaluate(
            '() => document.querySelectorAll(\'.ProseMirror[contenteditable="true"]\')[1]?.querySelectorAll("img").length || 0'
        )
        print(f"      ✅ 已插入 (当前共 {img_count} 张)")


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════


async def publish(title: str, page_id: str = None, md_file: str = None, dry_run: bool = False):
    """完整发布流程"""
    wechat_storage = str(ROOT / "wechat_storage.json")
    mdnice_storage = str(ROOT / "mdnice_storage.json")

    # 自动检测并登录（login 会循环等待直到成功）
    for platform in ["wechat", "mdnice"]:
        storage = str(ROOT / f"{platform}_storage.json")
        if not os.path.exists(storage):
            await login(platform)
            print(f"\n✅ {platform} 登录完成，继续发布...\n")

    # ── 获取 Markdown ──
    image_local_paths = []  # [(notion_url, local_path), ...]
    if md_file:
        with open(md_file, "r") as f:
            markdown = f.read()
        print(f"📄 Markdown 文件: {md_file} ({len(markdown):,} 字符)")
    elif page_id:
        markdown, auto_title, image_local_paths = get_markdown_and_images(page_id)
        title = title or auto_title
        # 上传图片到微信 CDN，Markdown 中用图片占位文本替代
        markdown = replace_images_with_placeholders(markdown, image_local_paths)
        print(f"📥 Notion 导出: {len(markdown):,} 字符, {len(image_local_paths)} 张图片已保存")
    else:
        print("❌ 请指定 --page-id 或 --md-file")
        return

    if not title:
        print("❌ 请提供文章标题")
        return

    print(f"📝 标题: {title[:64]}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])

        # ═══ Step 1: mdnice 渲染 ═══
        print("\n" + "─" * 50)
        print("1/3  mdnice 渲染...")
        ctx = await browser.new_context(
            storage_state=mdnice_storage,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page = await ctx.new_page()
        await page.goto("https://editor.mdnice.com/", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)

        # 关闭版本更新弹窗
        await page.evaluate(
            """() => document.querySelectorAll("button").forEach(
                b => { if (b.textContent.includes("确")) b.click(); }
            )"""
        )
        await asyncio.sleep(2)

        # 新建文章
        await page.locator(".add-btn").click()
        await asyncio.sleep(2)
        await page.locator('.ant-modal input[placeholder="请输入标题"]').fill(title[:64])
        await asyncio.sleep(1)
        await page.locator('.ant-modal button:has-text("新 增")').click()
        await asyncio.sleep(3)

        # 激活编辑器 + 粘贴 Markdown
        await page.mouse.click(400, 400)
        await asyncio.sleep(2)
        await page.evaluate(
            "(md) => { document.querySelector('.CodeMirror').CodeMirror.setValue(md); }",
            markdown,
        )

        # 等待渲染
        for _ in range(30):
            await asyncio.sleep(2)
            nice_len = await page.evaluate(
                '() => document.querySelector("#nice")?.innerHTML?.length || 0'
            )
            if nice_len > 10000:
                break

        rendered_len = await page.evaluate(
            '() => document.querySelector("#nice")?.innerHTML?.length || 0'
        )
        print(f"   ✅ 渲染完成: {rendered_len:,} 字符")

        # 点击「复制到微信公众号」
        await page.locator(".nice-btn-wechat").click()
        await asyncio.sleep(2)
        print("   ✅ 已复制到剪贴板")

        if dry_run:
            print("\n🔍 Dry run — 不发布到微信")
            await page.close()
            await ctx.close()
            await browser.close()
            return

        await page.close()
        await ctx.close()

        # ═══ Step 2: 微信粘贴 ═══
        print("\n" + "─" * 50)
        print("2/3  微信粘贴...")
        ctx_wx = await browser.new_context(
            storage_state=wechat_storage,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        page_wx = await ctx_wx.new_page()

        # 登录 + 获取 token
        await page_wx.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        token_match = re.search(r"token=(\d+)", page_wx.url)
        if not token_match:
            print("❌ 微信 Cookie 过期，请重新登录: python mdnice_publish.py --login-wechat")
            return
        token = token_match.group(1)

        # 新建文章
        draft_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg"
            f"?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&lang=zh_CN&token={token}"
        )
        await page_wx.goto(draft_url, wait_until="networkidle")
        await asyncio.sleep(5)

        # 设置标题（第一个 ProseMirror）
        await page_wx.evaluate(
            """(t) => {
                const e = document.querySelectorAll('.ProseMirror[contenteditable="true"]')[0];
                e.focus(); e.textContent = t;
                e.dispatchEvent(new Event("input", {bubbles: true}));
            }""",
            title[:64],
        )
        await asyncio.sleep(1)

        # Ctrl+V 粘贴（mdnice 已把内容复制到剪贴板）
        body_editor = page_wx.locator('.ProseMirror[contenteditable="true"]').nth(1)
        await body_editor.click()
        await asyncio.sleep(1)
        await page_wx.keyboard.press("Control+v")
        await asyncio.sleep(5)

        # 验证粘贴
        verify = await page_wx.evaluate(
            """() => {
                const e = document.querySelectorAll('.ProseMirror[contenteditable="true"]')[1];
                return {
                    chars: e.textContent.length,
                    pre: !!e.querySelector("pre"),
                    img: e.querySelectorAll("img").length,
                };
            }"""
        )
        print(f"   粘贴: {verify['chars']:,} 字符, 代码块={verify['pre']}, 图片={verify['img']}")

        # ═══ Step 2.5: 插入图片 ═══
        if image_local_paths:
            print(f"\n   📷 插入 {len(image_local_paths)} 张图片...")
            await insert_images_to_wechat_editor(page_wx, image_local_paths)

        # ═══ Step 3: 保存 ═══
        print("\n" + "─" * 50)
        print("3/3  保存草稿...")

        await page_wx.evaluate(
            """() => {
                const b = Array.from(document.querySelectorAll("button"))
                    .find(x => x.textContent.includes("保存为草稿"));
                if (b) b.click();
            }"""
        )

        for i in range(25):
            await asyncio.sleep(4)
            # 处理合规检测弹窗
            await page_wx.evaluate(
                """() => {
                    document.querySelectorAll("button").forEach(b => {
                        const t = b.textContent;
                        if (/(仍要保存|确定|我知道了|继续|关闭)/.test(t)) b.click();
                    });
                }"""
            )
            if "appmsgid" in page_wx.url:
                did = re.search(r"appmsgid=(\d+)", page_wx.url)
                if did:
                    print(f"\n✅ 草稿已保存!")
                    print(f"   draft_id: {did.group(1)}")
                    print(f"   登录 mp.weixin.qq.com → 草稿箱 查看")
                    break
        else:
            print("\n⚠️  保存超时，但内容已粘贴到编辑器")
            print("   请在浏览器中手动点击「保存为草稿」")

        await ctx_wx.close()
        await browser.close()

    print("\n" + "=" * 50)
    print("🎉 完成!")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Notion → mdnice → 微信公众号 全自动发布",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/mdnice_publish.py https://app.notion.com/p/Title-1af24043556480cfad2dc64212758475
  python scripts/mdnice_publish.py "文章标题" 1af24043556480cfad2dc64212758475
  python scripts/mdnice_publish.py --md-file article.md "标题"
  python scripts/mdnice_publish.py --dry-run https://app.notion.com/p/...
        """,
    )
    parser.add_argument(
        "url_or_title", nargs="?", default="",
        help="Notion 页面链接（自动提取标题 + page_id）或文章标题",
    )
    parser.add_argument(
        "page_id", nargs="?", default=None,
        help="Notion 页面 ID（如果第一个参数是标题而非链接）",
    )
    parser.add_argument("--md-file", default=None, help="直接使用已有 Markdown 文件")
    parser.add_argument("--dry-run", action="store_true", help="仅 mdnice 渲染，不发布到微信")
    parser.add_argument("--login-wechat", action="store_true", help="登录微信公众平台")
    parser.add_argument("--login-mdnice", action="store_true", help="登录 mdnice")
    args = parser.parse_args()

    # 登录模式
    if args.login_wechat:
        asyncio.run(login("wechat"))
        return
    if args.login_mdnice:
        asyncio.run(login("mdnice"))
        return

    # 发布模式：解析 URL 或 title+page_id
    title = ""
    page_id = args.page_id
    md_file = args.md_file
    dry_run = args.dry_run

    if args.url_or_title:
        # 判断是 Notion URL 还是标题
        url_match = re.search(
            r"https?://(?:www\.)?notion\.so/[^/]*[?/](?:p/)?[^?]*?[?/]?([a-f0-9]{32})",
            args.url_or_title,
        )
        if not url_match:
            # 也匹配 app.notion.com/p/ 格式
            url_match = re.search(
                r"https?://app\.notion\.com/p/[^?]*-([a-f0-9]{32})",
                args.url_or_title,
            )
        if url_match:
            # 是 Notion 链接 → 提取 page_id，标题留空自动获取
            page_id = url_match.group(1)
            print(f"🔗 从链接提取 page_id: {page_id}")
        elif not page_id:
            # 不是链接，当作标题
            title = args.url_or_title

    asyncio.run(publish(
        title=title,
        page_id=page_id,
        md_file=md_file,
        dry_run=dry_run,
    ))


if __name__ == "__main__":
    main()
