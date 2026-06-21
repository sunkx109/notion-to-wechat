"""Notion Block → 微信富文本 HTML 转换器

Notion block 类型参考:
https://developers.notion.com/reference/block

微信富文本支持的 HTML 标签子集:
h1-h6, p, strong, em, a, img, ul, ol, li, blockquote,
pre, code, hr, table, div, span, section, br
不支持的: class/id, style (部分支持), script, iframe
"""

import re
import tempfile
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .wechat_client import WeChatClient

from .utils import logger

# Notion 颜色名 → 十六进制
NOTION_COLORS = {
    "default": "#333333",
    "gray": "#787774",
    "brown": "#9F6B53",
    "orange": "#D9730D",
    "yellow": "#CB912F",
    "green": "#448361",
    "blue": "#337EA9",
    "purple": "#9065B0",
    "pink": "#C14D8A",
    "red": "#D44C47",
    "gray_background": "#F1F1EF",
    "brown_background": "#F3EEEE",
    "orange_background": "#F8ECDF",
    "yellow_background": "#FAF3DD",
    "green_background": "#EDF3EC",
    "blue_background": "#E7F3F8",
    "purple_background": "#F3F0F8",
    "pink_background": "#F9EEF3",
    "red_background": "#FDEBEC",
}


def _notion_file_url(file_obj: dict) -> Optional[str]:
    """从 Notion file 对象中提取可下载的 URL"""
    if not file_obj:
        return None
    ftype = file_obj.get("type", "")
    url = None
    if ftype == "file":
        url = file_obj["file"].get("url")
    elif ftype == "external":
        url = file_obj["external"].get("url")

    if not url:
        return None

    # 处理相对路径 (如 ../doc/image%207.png)
    if url.startswith("../") or url.startswith("./"):
        # Notion 的图片托管在文件存储域名下，相对路径需要补全
        # 通常签名过期后的原始 URL 也会带 aws 域名
        from urllib.parse import urljoin
        url = urljoin("https://www.notion.so/", url)

    return url


def _download_image(url: str, timeout: int = 30) -> Optional[str]:
    """下载图片到临时文件，返回临时文件路径"""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        ext = "jpg"
        if "png" in content_type:
            ext = "png"
        elif "gif" in content_type:
            ext = "gif"
        elif "webp" in content_type:
            ext = "webp"

        fd, path = tempfile.mkstemp(suffix=f".{ext}")
        with open(fd, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        logger.warning(f"下载图片失败 {url[:60]}: {e}")
        return None


def rich_text_to_html(rich_text_list: list[dict]) -> str:
    """将 Notion 的 rich_text 数组转为 HTML 片段

    处理: bold, italic, strikethrough, underline, code, link, color, equation
    """
    if not rich_text_list:
        return ""

    parts = []
    for rt in rich_text_list:
        text = rt.get("plain_text", "")
        # HTML 转义
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if not text and rt.get("type") == "equation":
            text = rt.get("plain_text", "")

        annotations = rt.get("annotations", {})
        href = rt.get("href") or rt.get("text", {}).get("link", {}).get("url")

        # 应用格式
        if annotations.get("code"):
            text = f'<code style="font-family:monospace;background:#f0f0f0;padding:1px 4px;border-radius:3px;">{text}</code>'
        if annotations.get("bold"):
            text = f"<strong>{text}</strong>"
        if annotations.get("italic"):
            text = f"<em>{text}</em>"
        if annotations.get("strikethrough"):
            text = f'<span style="text-decoration:line-through;">{text}</span>'
        if annotations.get("underline"):
            text = f'<span style="text-decoration:underline;">{text}</span>'

        # 颜色
        color = annotations.get("color", "default")
        if color and color != "default":
            hex_color = NOTION_COLORS.get(color)
            if hex_color:
                if "background" in color:
                    text = f'<span style="background-color:{hex_color};">{text}</span>'
                else:
                    text = f'<span style="color:{hex_color};">{text}</span>'

        # 链接
        if href and not annotations.get("code"):
            text = f'<a href="{href}">{text}</a>'

        parts.append(text)

    return "".join(parts)


class NotionToWeChatConverter:
    """Notion blocks → 微信 HTML 转换器"""

    STYLE_BLOCK = """
    <style>
    h1 { font-size: 22px; font-weight: bold; margin: 20px 0 12px; }
    h2 { font-size: 20px; font-weight: bold; margin: 18px 0 10px; }
    h3 { font-size: 18px; font-weight: bold; margin: 16px 0 8px; }
    p { margin: 10px 0; line-height: 1.75; color: #333; font-size: 15px; }
    blockquote { border-left: 3px solid #1aad19; padding: 8px 15px; margin: 15px 0; background: #f8f8f8; color: #666; font-size: 14px; }
    pre { background: #282c34; color: #abb2bf; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 13px; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; margin: 12px 0; }
    code { font-family: "Courier New", monospace; }
    ul, ol { padding-left: 20px; margin: 10px 0; }
    li { margin: 4px 0; line-height: 1.75; }
    hr { border: none; border-top: 1px solid #eee; margin: 20px 0; }
    table { border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 14px; }
    table td, table th { border: 1px solid #ddd; padding: 8px; }
    table th { background: #f5f5f5; }
    img { max-width: 100%; height: auto; display: block; margin: 10px auto; border-radius: 4px; }
    a { color: #576b95; text-decoration: none; }
    .notion-callout { border-radius: 4px; padding: 15px; margin: 15px 0; display: flex; align-items: flex-start; background: #f8f8f8; }
    .notion-callout-emoji { margin-right: 10px; font-size: 20px; }
    .notion-bookmark { border: 1px solid #e0e0e0; border-radius: 5px; padding: 12px; margin: 12px 0; display: block; }
    .notion-bookmark a { font-weight: bold; font-size: 14px; }
    </style>
    """

    def __init__(self, wechat_client: Optional["WeChatClient"] = None):
        self._wx = wechat_client
        self._uploaded_images: dict[str, str] = {}  # notion_url → wechat_url

    def convert_blocks(self, blocks: list[dict], indent_level: int = 0) -> str:
        """转换 Notion blocks 列表为微信 HTML 字符串"""
        html_parts = []
        i = 0
        while i < len(blocks):
            block = blocks[i]

            # 处理列表项（需要将同类型连续项包裹在 ul/ol 中）
            btype = block.get("type", "")

            if btype == "bulleted_list_item":
                list_html, consumed = self._convert_list(blocks, i, "bulleted_list_item", "ul")
                html_parts.append(list_html)
                i += consumed
                continue

            if btype == "numbered_list_item":
                list_html, consumed = self._convert_list(blocks, i, "numbered_list_item", "ol")
                html_parts.append(list_html)
                i += consumed
                continue

            # 普通 block
            result = self._convert_block(block)
            if result:
                html_parts.append(result)
            i += 1

        return "\n".join(html_parts)

    def _convert_list(
        self,
        blocks: list[dict],
        start_idx: int,
        item_type: str,
        wrapper_tag: str,
    ) -> tuple[str, int]:
        """将连续的同类列表项包裹在 ul/ol 中，返回 (html, 消费的 block 数)"""
        items = []
        i = start_idx
        while i < len(blocks) and blocks[i].get("type") == item_type:
            item_html = self._convert_list_item(blocks[i], item_type)
            items.append(f"<li>{item_html}</li>")
            i += 1

        wrapped = f"<{wrapper_tag}>\n" + "\n".join(items) + f"\n</{wrapper_tag}>"
        return wrapped, i - start_idx

    def _convert_list_item(self, block: dict, item_type: str) -> str:
        """转换单个列表项的内容"""
        content = block.get(item_type, {})
        rich_text = content.get("rich_text", [])
        text_html = rich_text_to_html(rich_text)

        # 递归处理子 blocks
        btype = block.get("type", "")
        children_html = ""
        if block.get("has_children"):
            from .notion_client import NotionClient
            # 这里需要外部注入 notion_client 或子 blocks...
            # 实际使用时，子 blocks 由 publisher 预先拉取并传入
            pass

        return text_html or "&nbsp;"

    def _convert_block(self, block: dict) -> str:
        """转换单个 Notion block 为 HTML"""
        btype = block.get("type", "")

        handler = getattr(self, f"_handle_{btype}", None)
        if handler:
            return handler(block)

        # 默认：尝试提取文本
        logger.debug(f"未支持的类型: {btype}")
        return self._fallback_block(block)

    def _handle_paragraph(self, block: dict) -> str:
        rich_text = block.get("paragraph", {}).get("rich_text", [])
        if not rich_text:
            return "<p><br></p>"
        return f"<p>{rich_text_to_html(rich_text)}</p>"

    def _handle_heading_1(self, block: dict) -> str:
        rich_text = block.get("heading_1", {}).get("rich_text", [])
        return f"<h1>{rich_text_to_html(rich_text)}</h1>"

    def _handle_heading_2(self, block: dict) -> str:
        rich_text = block.get("heading_2", {}).get("rich_text", [])
        return f"<h2>{rich_text_to_html(rich_text)}</h2>"

    def _handle_heading_3(self, block: dict) -> str:
        rich_text = block.get("heading_3", {}).get("rich_text", [])
        return f"<h3>{rich_text_to_html(rich_text)}</h3>"

    def _handle_quote(self, block: dict) -> str:
        rich_text = block.get("quote", {}).get("rich_text", [])
        return f"<blockquote>{rich_text_to_html(rich_text)}</blockquote>"

    def _handle_divider(self, block: dict) -> str:
        return "<hr>"

    def _handle_image(self, block: dict) -> str:
        """处理图片：从 Notion 下载 → 上传微信 → 获取微信 URL"""
        image_obj = block.get("image", {})
        notion_url = _notion_file_url(image_obj)

        if not notion_url:
            cap = rich_text_to_html(image_obj.get("caption", []))
            return f"<p>[图片: {cap or '无法获取'}]</p>"

        # 如果已经上传过，用缓存
        if notion_url in self._uploaded_images:
            wx_url = self._uploaded_images[notion_url]
            logger.info(f"使用缓存的微信图片: {wx_url[:50]}...")
        elif self._wx:
            # 下载 + 上传
            tmp_path = _download_image(notion_url)
            if tmp_path:
                try:
                    wx_url = self._wx.upload_content_image(tmp_path)
                    self._uploaded_images[notion_url] = wx_url
                    logger.info(f"图片已上传到微信: {wx_url[:50]}...")
                except Exception as e:
                    logger.warning(f"上传图片到微信失败: {e}")
                    return f'<img src="{notion_url}" alt="图片">'
                finally:
                    # 清理临时文件
                    try:
                        Path(tmp_path).unlink()
                    except Exception:
                        pass
            else:
                # 下载失败，直接用原链接（可能会过期）
                logger.warning(f"图片下载失败，使用原链接: {notion_url[:60]}...")
                return f'<img src="{notion_url}" alt="图片">'
        else:
            # 没有 wechat client，使用原链接
            logger.info("未配置微信客户端，图片使用 Notion 原链接")
            return f'<img src="{notion_url}" alt="图片">'

        caption_html = rich_text_to_html(image_obj.get("caption", []))
        caption = f'<p style="text-align:center;color:#888;font-size:13px;">{caption_html}</p>' if caption_html else ""
        return f'<img src="{wx_url}" alt="图片">\n{caption}'

    def _handle_code(self, block: dict) -> str:
        code_obj = block.get("code", {})
        rich_text = code_obj.get("rich_text", [])
        language = code_obj.get("language", "")
        code_text = "".join(t.get("plain_text", "") for t in rich_text)
        # HTML 转义
        code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lang_label = f'<span style="color:#999;font-size:12px;">{language}</span>\n' if language else ""
        caption_html = rich_text_to_html(code_obj.get("caption", []))
        caption = f'<p style="text-align:center;color:#888;font-size:13px;">{caption_html}</p>' if caption_html else ""

        return f"<pre>{lang_label}{code_text}</pre>\n{caption}"

    def _handle_callout(self, block: dict) -> str:
        callout_obj = block.get("callout", {})
        icon = callout_obj.get("icon", {})
        emoji = ""
        if icon.get("type") == "emoji":
            emoji = icon.get("emoji", "")

        rich_text = callout_obj.get("rich_text", [])
        text = rich_text_to_html(rich_text)
        return (
            f'<div class="notion-callout">'
            f'<span class="notion-callout-emoji">{emoji}</span>'
            f'<span>{text}</span>'
            f"</div>"
        )

    def _handle_table(self, block: dict) -> str:
        """表格处理：简单的 <table> 标签。微信支持有限。"""
        table_obj = block.get("table", {})
        has_column_header = table_obj.get("has_column_header", False)
        has_row_header = table_obj.get("has_row_header", False)
        table_width = table_obj.get("table_width", 0)

        # 表格内容在子 blocks 中，这里仅返回占位或从 children 构建
        # publisher 负责拉取子 blocks 后再转换
        rows_html = ""
        if block.get("has_children"):
            rows_html = "<!-- 表格行需要从子 block 拉取 -->"
        return f"<table>{rows_html}</table>"

    def _handle_table_row(self, block: dict) -> str:
        """转换表格行"""
        row_obj = block.get("table_row", {})
        cells = row_obj.get("cells", [])
        cells_html = "".join(
            f"<td>{rich_text_to_html(cell)}</td>" for cell in cells
        )
        return f"<tr>{cells_html}</tr>"

    def _handle_bookmark(self, block: dict) -> str:
        bookmark = block.get("bookmark", {})
        url = bookmark.get("url", "")
        caption = rich_text_to_html(bookmark.get("caption", []))
        title = caption or url
        return (
            f'<div class="notion-bookmark">'
            f'<a href="{url}">🔗 {title}</a>'
            f"</div>"
        )

    def _handle_link_preview(self, block: dict) -> str:
        """link_preview 等同于 bookmark"""
        return self._handle_bookmark(block)

    def _handle_toggle(self, block: dict) -> str:
        """Toggle 块：展开内部内容"""
        toggle_obj = block.get("toggle", {})
        rich_text = toggle_obj.get("rich_text", [])
        summary = rich_text_to_html(rich_text) or "展开"

        children_html = ""
        # 子 blocks 由 publisher 预拉取后放到 children 字段
        children = block.get("_children", [])
        if children:
            children_html = f'<div style="padding-left:15px;">{self.convert_blocks(children)}</div>'

        return (
            f'<div style="margin:10px 0;">'
            f'<details><summary style="cursor:pointer;color:#576b95;">▶ {summary}</summary>'
            f"{children_html}"
            f"</details>"
            f"</div>"
        )

    def _handle_to_do(self, block: dict) -> str:
        to_do = block.get("to_do", {})
        checked = to_do.get("checked", False)
        rich_text = to_do.get("rich_text", [])
        checkbox = "☑" if checked else "☐"
        return f'<p>{checkbox} {rich_text_to_html(rich_text)}</p>'

    def _handle_video(self, block: dict) -> str:
        video = block.get("video", {})
        url = _notion_file_url(video) or ""
        caption = rich_text_to_html(video.get("caption", []))
        if url:
            return f'<p>📹 <a href="{url}">视频: {caption or url}</a></p>'
        return f"<p>📹 [视频] {caption}</p>"

    def _handle_file(self, block: dict) -> str:
        file_obj = block.get("file", {})
        url = _notion_file_url(file_obj) or ""
        caption = rich_text_to_html(file_obj.get("caption", []))
        name = caption or url.split("/")[-1].split("?")[0] or "文件"
        if url:
            return f'<p>📎 <a href="{url}">文件: {name}</a></p>'
        return f"<p>📎 [文件] {name}</p>"

    def _handle_embed(self, block: dict) -> str:
        embed = block.get("embed", {})
        url = embed.get("url", "")
        if url:
            return f'<p>📌 <a href="{url}">{url}</a></p>'
        return ""

    def _handle_equation(self, block: dict) -> str:
        """块级公式 - 微信不支持渲染，输出原文"""
        equation = block.get("equation", {})
        expression = equation.get("expression", "")
        return f'<p style="text-align:center;font-style:italic;color:#666;">[公式] {expression}</p>'

    def _handle_synced_block(self, block: dict) -> str:
        """Synced block - 当做普通容器处理"""
        children = block.get("_children", [])
        if children:
            return self.convert_blocks(children)
        return "<p><!-- synced block --></p>"

    def _handle_column_list(self, block: dict) -> str:
        """分栏容器"""
        children = block.get("_children", [])
        if children:
            return self.convert_blocks(children)
        return ""

    def _handle_column(self, block: dict) -> str:
        children = block.get("_children", [])
        if children:
            return self.convert_blocks(children)
        return ""

    def _fallback_block(self, block: dict) -> str:
        """未支持的 block 类型，尝试提取文本内容"""
        btype = block.get("type", "unknown")
        content = block.get(btype, {})
        rich_text = content.get("rich_text", [])
        if rich_text:
            return f"<p>{rich_text_to_html(rich_text)}</p>"
        return f"<p><!-- unsupported block: {btype} --></p>"

    def get_style_block(self) -> str:
        """返回微信富文本的内联样式块"""
        return self.STYLE_BLOCK
