#!/usr/bin/env python3
"""
Notion → mdnice → 微信公众号 全自动发布

流程:
  1. 从 Notion 拉取页面 → 导出 Markdown
  2. 图片并发下载到本地
  3. mdnice.com: 新建文章 → 粘贴 Markdown → 等待真实渲染 → 复制到微信
  4. 微信后台: 粘贴 → 插入图片 → 保存草稿

前置条件:
  - 项目根目录 .env (NOTION_API_KEY 等)
  - mdnice 登录 Cookie（首次自动扫码，Cookie 持久化）
  - 微信公众平台 Cookie（首次自动扫码，Cookie 持久化）

用法:
  python scripts/mdnice_publish.py https://app.notion.com/p/Title-1af2...
  python scripts/mdnice_publish.py "文章标题" <notion-page-id>
  python scripts/mdnice_publish.py --md-file article.md "标题"
  python scripts/mdnice_publish.py --dry-run "标题" <page-id>
"""

import argparse
import asyncio
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# ═══ 路径: 区分 skill 目录 vs 项目根 ═══
# 脚本位置: <PROJ_ROOT>/notion-publisher/scripts/mdnice_publish.py
SKILL_DIR = Path(__file__).parent.parent          # notion-publisher/
PROJ_ROOT = SKILL_DIR.parent                       # notion-to-wechat/ (项目根)
sys.path.insert(0, str(SKILL_DIR))

# ═══ 输出目录都在项目根 ═══
MDS_DIR = PROJ_ROOT / "mds"
QR_DIR = PROJ_ROOT / "login_img"
MDS_DIR.mkdir(exist_ok=True)
QR_DIR.mkdir(exist_ok=True)

WECHAT_STORAGE = str(PROJ_ROOT / "wechat_storage.json")
MDNICE_STORAGE = str(PROJ_ROOT / "mdnice_storage.json")


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def now():
    return time.strftime("%H:%M:%S")

def log(msg: str):
    print(f"[{now()}] {msg}", flush=True)


async def wait_for(page, condition_desc: str, check_fn, timeout: float = 10.0, interval: float = 0.3):
    """主动轮询等待条件满足，实时输出进度"""
    start = time.time()
    last_msg = 0
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            log(f"   ⚠️  等待超时 ({timeout}s): {condition_desc}")
            return None
        try:
            result = await check_fn()
            if result:
                if elapsed > 0.5:
                    log(f"   ✅ {condition_desc} (耗时 {elapsed:.1f}s)")
                return result
        except Exception:
            pass
        if elapsed - last_msg > 3:
            log(f"   ⏳ {condition_desc} ({elapsed:.0f}s/{timeout}s)")
            last_msg = elapsed
        await asyncio.sleep(interval)


async def wait_for_selector(page, selector: str, timeout: float = 10.0):
    async def check():
        try:
            return await page.locator(selector).first.is_visible()
        except Exception:
            return False
    return await wait_for(page, f"可见 [{selector}]", check, timeout, interval=0.2)


# ═══════════════════════════════════════════════════════════════
# Notion 导出 — 图片并发下载
# ═══════════════════════════════════════════════════════════════

def _download_single_image(args: tuple) -> tuple[int, str | None, str | None, int]:
    """下载单张图片（线程池用）"""
    i, url, img_dir = args
    try:
        resp = requests.get(url, timeout=15)
        ext = ".png"
        ct = resp.headers.get("content-type", "")
        if "jpeg" in ct or "jpg" in ct:
            ext = ".jpg"
        elif "gif" in ct:
            ext = ".gif"
        elif "webp" in ct:
            ext = ".webp"
        local_path = str(img_dir / f"img_{i:02d}{ext}")
        with open(local_path, "wb") as f:
            f.write(resp.content)
        return (i, url, local_path, len(resp.content))
    except Exception as e:
        return (i, url, None, 0)


def get_markdown_and_images(page_id: str) -> tuple[str, str, list[tuple[str, str]]]:
    """从 Notion 拉取页面 → 导出 Markdown → 并发下载图片"""
    from src.notion_client import NotionClient
    from src.utils import load_config

    log(f"📥 从 Notion 拉取页面: {page_id}")

    config = load_config(str(SKILL_DIR / "config.yaml"))
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
    log(f"   标题: {title[:64]}")

    from src.notion2md import convert_json_to_markdown

    md = convert_json_to_markdown({"blocks": blocks})
    log(f"   Markdown: {len(md):,} 字符, {len(blocks)} blocks")

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
    log(f"   图片: {len(image_urls)} 张")

    safe_title = re.sub(r"[^\w一-鿿]", "_", title)[:30]
    article_dir = MDS_DIR / safe_title
    img_dir = article_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # ── 并发下载图片 ──
    image_pairs = []
    local_rel_paths = [""] * max(len(image_urls), 1)

    if image_urls:
        t0 = time.time()
        tasks = [(i, url, img_dir) for i, url in enumerate(image_urls)]
        with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool:
            futures = {pool.submit(_download_single_image, t): t for t in tasks}
            for future in as_completed(futures):
                i, url, local_path, size = future.result()
                if local_path:
                    image_pairs.append((url, local_path))
                    local_rel_paths[i] = f"images/img_{i:02d}{os.path.splitext(local_path)[1]}"
                    log(f"   📥 图片 {i}: {size:,} bytes")
                else:
                    log(f"   ⚠️  图片 {i} 下载失败")

        # 按原始顺序排序
        image_pairs.sort(key=lambda x: image_urls.index(x[0]))
        log(f"   下载完成: {time.time()-t0:.1f}s ({len(tasks)} 张并发)")

    # 替换 Markdown 中的图片引用为本地相对路径
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

    md_path = article_dir / "article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_for_file)
    log(f"   📄 已保存: {md_path}")

    return md, title, image_pairs


def replace_images_with_placeholders(markdown: str, image_pairs: list) -> str:
    """Markdown 图片 → [📷 图N] 占位符（mdnice 复制到微信时用）"""
    for i, (url, _) in enumerate(image_pairs):
        placeholder = f"[📷 图{i}]"
        pattern = rf"!\[[^\]]*\]\({re.escape(url)}\)"
        if re.search(pattern, markdown):
            markdown = re.sub(pattern, placeholder, markdown)
        else:
            markdown = markdown.replace(url, placeholder)
    return markdown


# ═══════════════════════════════════════════════════════════════
# 登录
# ═══════════════════════════════════════════════════════════════

LOGIN_URLS = {
    "wechat": {
        "url": "https://mp.weixin.qq.com/",
        "storage": WECHAT_STORAGE,
        "qr_file": str(QR_DIR / "wechat_qr.png"),
        "success_check": "/cgi-bin/home",
    },
    "mdnice": {
        "url": "https://editor.mdnice.com/",
        "storage": MDNICE_STORAGE,
        "qr_file": str(QR_DIR / "mdnice_qr.png"),
        "success_check": None,
        "success_text": "微信扫码登录",
    },
}


async def login(platform: str):
    """展示二维码 → 等待扫码 → 自动刷新 → Cookie 持久化"""
    cfg = LOGIN_URLS[platform]
    if os.path.exists(cfg["storage"]):
        log(f"✅ {cfg['storage']} 已存在，跳过登录")
        return

    log(f"\n{'='*50}")
    log(f"🔐 需要登录 {platform.upper()}")
    log(f"{'='*50}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        page = await context.new_page()

        for round_num in range(1, 99):
            if round_num > 1:
                log("🔄 刷新获取新二维码...")
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(1)
            else:
                await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

            await page.screenshot(path=cfg["qr_file"], full_page=True)
            log(f"📱 二维码: {cfg['qr_file']}")
            log(f"⏳ 等待扫码 (每 2s 检测)...")

            for _ in range(60):
                await asyncio.sleep(2)
                try:
                    if cfg["success_check"]:
                        logged_in = cfg["success_check"] in page.url
                    else:
                        body = await page.evaluate("() => document.body.innerText")
                        logged_in = cfg["success_text"] not in body
                    if logged_in:
                        log(f"✅ 扫码成功！")
                        await asyncio.sleep(1)
                        await context.storage_state(path=cfg["storage"])
                        log(f"💾 Cookie → {cfg['storage']}")
                        await browser.close()
                        return
                except Exception:
                    pass

            log("⏰ 本轮超时，自动刷新...")

        await browser.close()


# ═══════════════════════════════════════════════════════════════
# 微信编辑器图片插入
# ═══════════════════════════════════════════════════════════════

async def _find_image_input(page_wx) -> str:
    return await page_wx.evaluate("""() => {
        for (const inp of document.querySelectorAll('input[type="file"]')) {
            const a = (inp.accept || '').toLowerCase();
            if (a.includes('image') || a.includes('png') || a.includes('jpg')) {
                if (inp.id) return '#' + inp.id;
                if (inp.name) return 'input[name="' + inp.name + '"]';
                return 'input[type="file"]';
            }
        }
        return '';
    }""")


async def insert_images_to_wechat_editor(page_wx, image_pairs: list):
    """在微信编辑器里按序替换 [📷 图N] 占位符为本地图片"""
    sel = await _find_image_input(page_wx)
    if not sel:
        log("   ❌ 未找到图片上传 input，跳过")
        return

    log(f"   🔍 图片 input: {sel}")
    img_input = page_wx.locator(sel)
    total_imgs = 0

    for i, (_, local_path) in enumerate(image_pairs):
        if not os.path.exists(local_path):
            log(f"   ⚠️  文件不存在: {local_path}")
            continue

        placeholder = f"[📷 图{i}]"
        log(f"   🖼️  图{i}...")

        # 选中占位符
        found = await page_wx.evaluate(
            """(ph) => {
                const editors = document.querySelectorAll('.ProseMirror[contenteditable="true"]');
                const e = editors[1] || editors[0];
                if (!e) return false;
                const text = e.textContent || '';
                const idx = text.indexOf(ph);
                if (idx === -1) return false;
                const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
                let pos = 0, target = null, off = 0;
                while (walker.nextNode()) {
                    const n = walker.currentNode;
                    const nt = n.textContent || '';
                    if (pos + nt.length > idx && !target) { target = n; off = idx - pos; break; }
                    pos += nt.length;
                }
                if (!target) return false;
                const r = document.createRange();
                r.setStart(target, off); r.setEnd(target, off + ph.length);
                const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
                return true;
            }""", placeholder)

        if not found:
            log(f"      ⚠️  占位符未找到 (可能已被 mdnice 渲染合并)")
            continue

        await asyncio.sleep(0.1)
        await page_wx.keyboard.press("Backspace")
        await asyncio.sleep(0.1)

        try:
            await img_input.set_input_files(local_path)
        except Exception as e:
            log(f"      ⚠️  上传失败: {e}")
            await page_wx.keyboard.press("Control+z")
            await asyncio.sleep(0.1)
            continue

        # 等待图片出现在编辑器中
        ok = await wait_for(
            page_wx, f"图{i}插入",
            lambda: page_wx.evaluate(
                """() => {
                    const e = document.querySelectorAll('.ProseMirror[contenteditable="true"]')[1];
                    return e ? e.querySelectorAll('img').length : 0;
                }"""
            ),
            timeout=8.0, interval=0.3,
        )
        if ok:
            total_imgs = ok if isinstance(ok, int) else total_imgs + 1
            log(f"      ✅ 已插入")

    log(f"   编辑器内图片: {total_imgs} 张")


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

async def publish(title: str = "", page_id: str = None, md_file: str = None, dry_run: bool = False):
    overall_start = time.time()

    # ── 登录检查 ──
    for platform in ["wechat", "mdnice"]:
        storage = WECHAT_STORAGE if platform == "wechat" else MDNICE_STORAGE
        if not os.path.exists(storage):
            await login(platform)
            log(f"✅ {platform} 登录完成\n")

    # ── 获取 Markdown ──
    image_local_paths = []
    if md_file:
        with open(md_file, "r") as f:
            markdown = f.read()
        log(f"📄 本地 Markdown: {md_file} ({len(markdown):,} 字符)")
    elif page_id:
        markdown, auto_title, image_local_paths = get_markdown_and_images(page_id)
        title = title or auto_title
        markdown = replace_images_with_placeholders(markdown, image_local_paths)
        log(f"📥 Notion 导出完成: {len(markdown):,} 字符, {len(image_local_paths)} 张图片")
    else:
        log("❌ 请指定 page_id 或 --md-file")
        return

    if not title:
        log("❌ 请提供文章标题")
        return

    log(f"📝 标题: {title[:64]}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])

        # ═══════════════════════════════════════════
        # 1/3  mdnice 渲染
        # ═══════════════════════════════════════════
        log("\n" + "─" * 50)
        log("📝 1/3  mdnice 渲染...")

        ctx = await browser.new_context(
            storage_state=MDNICE_STORAGE,
            viewport={"width": 1920, "height": 1080}, locale="zh-CN",
        )
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await ctx.new_page()

        t0 = time.time()
        await page.goto("https://editor.mdnice.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        log(f"   页面加载: {time.time()-t0:.1f}s")

        await wait_for_selector(page, ".add-btn", timeout=8.0)

        # 关弹窗
        try:
            await page.evaluate(
                """() => document.querySelectorAll("button").forEach(
                    b => { if(/(确|知|关)/.test(b.textContent)) b.click(); })"""
            )
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # 新建文章
        t0 = time.time()
        await page.locator(".add-btn").first.click()
        await wait_for_selector(page, '.ant-modal input[placeholder="请输入标题"]', timeout=5.0)
        await page.locator('.ant-modal input[placeholder="请输入标题"]').fill(title[:64])
        await asyncio.sleep(0.2)
        await page.locator('.ant-modal button:has-text("新 增")').click()
        log(f"   新建文章: {time.time()-t0:.1f}s")
        await asyncio.sleep(0.3)

        # ── 关键: 记录渲染前的 #nice 长度，确保真的发生了渲染 ──
        baseline_len = await page.evaluate(
            '() => { const n = document.querySelector("#nice"); return n ? n.innerHTML.length : 0; }'
        )
        log(f"   渲染前 #nice 基线: {baseline_len} 字符")

        # ── 通过剪贴板粘贴 Markdown（模拟人工 Ctrl+V）──
        t0 = time.time()
        # 1. 将 markdown 写入系统剪贴板
        await page.evaluate(
            """(md) => navigator.clipboard.writeText(md)""",
            markdown,
        )
        # 2. 点击 CodeMirror 编辑区获取焦点
        cm_box = page.locator(".CodeMirror")
        await cm_box.click()
        await asyncio.sleep(0.2)
        # 3. Ctrl+A 全选 → Ctrl+V 粘贴（触发 mdnice 完整事件链）
        await page.keyboard.press("Control+a")
        await asyncio.sleep(0.1)
        await page.keyboard.press("Control+v")
        await asyncio.sleep(0.3)
        log(f"   粘贴 Markdown 到 CodeMirror: {time.time()-t0:.1f}s")

        # ── 等待 #nice 真正渲染: 长度必须 > 基线 + 500 字符 ──
        log("   等待 mdnice 真实渲染...")
        t0 = time.time()
        rendered_len = await wait_for(
            page,
            "mdnice 真实渲染完成",
            lambda: page.evaluate(
                f"""() => {{
                    const n = document.querySelector("#nice");
                    if (!n) return 0;
                    const len = n.innerHTML.length;
                    // 必须显著大于基线，且包含渲染产物（pre/code/img/math）
                    const hasRendered = n.querySelector('pre, code, img, .katex, .mathjax, svg, table');
                    return (len > {baseline_len} + 500 && hasRendered) ? len : 0;
                }}"""
            ),
            timeout=45.0,
            interval=0.5,
        )

        if rendered_len:
            log(f"   ✅ 渲染完成: {rendered_len:,} 字符 (耗时 {time.time()-t0:.1f}s)")
        else:
            fallback_len = await page.evaluate(
                '() => { const n = document.querySelector("#nice"); return n ? n.innerHTML.length : 0; }'
            )
            log(f"   ⚠️  渲染可能不完整: 当前 {fallback_len} 字符 (基线 {baseline_len})")

        # 等 mdnice 自动保存（渲染后需要 2-3s 将内容持久化到服务器）
        log("   等待 mdnice 自动保存...")
        await asyncio.sleep(3)
        log("   ✅ 自动保存完成")

        # 复制到微信公众号
        t0 = time.time()
        await page.locator(".nice-btn-wechat").first.click()
        await asyncio.sleep(0.5)
        log(f"   ✅ 复制到剪贴板 ({time.time()-t0:.1f}s)")

        if dry_run:
            log("\n🔍 Dry run — 不发布到微信")
            await page.close(); await ctx.close(); await browser.close()
            log(f"\n⏱️  总耗时: {time.time()-overall_start:.1f}s")
            return

        await page.close()
        await ctx.close()

        # ═══════════════════════════════════════════
        # 2/3  微信粘贴
        # ═══════════════════════════════════════════
        log("\n" + "─" * 50)
        log("📋 2/3  微信粘贴...")

        ctx_wx = await browser.new_context(
            storage_state=WECHAT_STORAGE,
            viewport={"width": 1920, "height": 1080}, locale="zh-CN",
        )
        page_wx = await ctx_wx.new_page()

        t0 = time.time()
        await page_wx.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(0.5)
        token_match = re.search(r"token=(\d+)", page_wx.url)
        if not token_match:
            log("❌ Cookie 过期: python scripts/mdnice_publish.py --login-wechat")
            return
        token = token_match.group(1)
        log(f"   微信后台: {time.time()-t0:.1f}s")

        draft_url = (
            f"https://mp.weixin.qq.com/cgi-bin/appmsg"
            f"?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&lang=zh_CN&token={token}"
        )
        await page_wx.goto(draft_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)
        log("   新建草稿页面就绪")

        # 标题
        await page_wx.evaluate(
            """(t) => {
                const e = document.querySelectorAll('.ProseMirror[contenteditable="true"]')[0];
                e.focus(); e.textContent = t;
                e.dispatchEvent(new Event("input", {bubbles: true}));
            }""", title[:64])
        await asyncio.sleep(0.2)

        # Ctrl+V
        t0 = time.time()
        body_editor = page_wx.locator('.ProseMirror[contenteditable="true"]').nth(1)
        await body_editor.click()
        await asyncio.sleep(0.2)
        await page_wx.keyboard.press("Control+v")

        verify = await wait_for(
            page_wx, "粘贴完成",
            lambda: page_wx.evaluate(
                """() => {
                    const e = document.querySelectorAll('.ProseMirror[contenteditable="true"]')[1];
                    return (e && e.textContent.length > 100) ? {
                        chars: e.textContent.length,
                        pre: !!e.querySelector("pre"),
                        img: e.querySelectorAll("img").length,
                    } : null;
                }"""
            ),
            timeout=15.0, interval=0.3,
        )
        if verify:
            log(f"   粘贴: {verify['chars']:,} 字符, pre={verify['pre']}, img={verify['img']} ({time.time()-t0:.1f}s)")
        else:
            log("   ⚠️  粘贴验证超时")

        # ═══ 插入图片 ═══
        if image_local_paths:
            log(f"\n   📷 插入 {len(image_local_paths)} 张本地图片...")
            t0 = time.time()
            await insert_images_to_wechat_editor(page_wx, image_local_paths)
            log(f"   图片插入耗时: {time.time()-t0:.1f}s")

        # ═══════════════════════════════════════════
        # 3/3  保存草稿
        # ═══════════════════════════════════════════
        log("\n" + "─" * 50)
        log("💾 3/3  保存草稿...")

        await page_wx.evaluate(
            """() => {
                const b = Array.from(document.querySelectorAll("button"))
                    .find(x => x.textContent.includes("保存为草稿"));
                if (b) b.click();
            }""")
        log("   已点击「保存为草稿」")

        saved = False
        for i in range(60):
            await asyncio.sleep(0.5)
            await page_wx.evaluate(
                """() => document.querySelectorAll("button").forEach(b => {
                    if(/(仍要保存|确定|我知道了|继续|关闭)/.test(b.textContent)) b.click();
                })""")
            if "appmsgid" in page_wx.url:
                did = re.search(r"appmsgid=(\d+)", page_wx.url)
                if did:
                    log(f"\n✅ 草稿已保存! draft_id: {did.group(1)}")
                    log(f"   登录 mp.weixin.qq.com → 草稿箱 查看")
                    saved = True
                    break
            if i > 0 and i % 10 == 0:
                log(f"   ⏳ 等待保存... ({i*0.5:.0f}s)")

        if not saved:
            log("\n⚠️  保存确认超时，请手动检查草稿箱")

        await ctx_wx.close()
        await browser.close()

    log(f"\n{'='*50}")
    log(f"🎉 完成! 总耗时: {time.time()-overall_start:.1f}s")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Notion → mdnice → 微信公众号 全自动发布")
    parser.add_argument("url_or_title", nargs="?", default="")
    parser.add_argument("page_id", nargs="?", default=None)
    parser.add_argument("--md-file", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--login-wechat", action="store_true")
    parser.add_argument("--login-mdnice", action="store_true")
    args = parser.parse_args()

    if args.login_wechat:
        asyncio.run(login("wechat")); return
    if args.login_mdnice:
        asyncio.run(login("mdnice")); return

    title = ""
    page_id = args.page_id
    md_file = args.md_file
    dry_run = args.dry_run

    if args.url_or_title:
        for pat in [
            r"https?://(?:www\.)?notion\.so/[^/]*[?/](?:p/)?[^?]*?[?/]?([a-f0-9]{32})",
            r"https?://app\.notion\.com/p/[^?]*-([a-f0-9]{32})",
        ]:
            m = re.search(pat, args.url_or_title)
            if m:
                page_id = m.group(1)
                log(f"🔗 page_id: {page_id}")
                break
        else:
            if not page_id:
                title = args.url_or_title

    asyncio.run(publish(title=title, page_id=page_id, md_file=md_file, dry_run=dry_run))


if __name__ == "__main__":
    main()
