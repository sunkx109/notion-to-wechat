"""Notion Blocks → 标准 Markdown 转换器

转换后可通过 mdnice 渲染引擎生成微信公众号/知乎等平台的富文本。

Notion block 类型参考: https://developers.notion.com/reference/block
"""

from typing import Optional

from .utils import logger


def _rich_text_to_md(rich_text_list: list[dict]) -> str:
    """将 Notion rich_text 数组转为 Markdown 行内文本

    处理: bold, italic, strikethrough, code, link, equation
    """
    if not rich_text_list:
        return ""

    parts = []
    for rt in rich_text_list:
        text = rt.get("plain_text", "")

        # 公式
        if rt.get("type") == "equation":
            parts.append(f"${text}$")
            continue

        annotations = rt.get("annotations", {})
        href = rt.get("href") or ""
        if not href:
            text_obj = rt.get("text")
            if text_obj and isinstance(text_obj, dict):
                link_obj = text_obj.get("link")
                if link_obj and isinstance(link_obj, dict):
                    href = link_obj.get("url", "")

        # Markdown 转义 (*, _, [, ], `, ~ 等)
        text = _escape_md(text)

        # 一层层包裹格式
        if annotations.get("code"):
            text = f"`{text}`"
        elif annotations.get("bold") and annotations.get("italic"):
            text = f"***{text}***"
        elif annotations.get("bold"):
            text = f"**{text}**"
        elif annotations.get("italic"):
            text = f"*{text}*"

        if annotations.get("strikethrough"):
            text = f"~~{text}~~"

        # 链接
        if href and not annotations.get("code"):
            text = f"[{text}]({href})"

        parts.append(text)

    return "".join(parts)


def _escape_md(text: str) -> str:
    """转义 Markdown 行内特殊字符

    只转义真正会在行内触发格式的字符:
    - `  → 代码 span
    - *  → 粗体/斜体
    - ~  → 删除线
    - \\ → 反斜杠自身

    不转义 [ ] _：
    - [text](url) 才是链接，单独的 [ ] 是普通文本
    - _ 只在 word 边界才触发 italic，变量名中的 _ 安全
    """
    escape_chars = ["\\", "`", "*", "~"]
    for ch in escape_chars:
        text = text.replace(ch, "\\" + ch)
    return text


def _notion_file_url(file_obj: dict) -> Optional[str]:
    """从 Notion file 对象中提取可下载的 URL"""
    ftype = file_obj.get("type", "")
    if ftype == "file":
        return file_obj["file"].get("url")
    elif ftype == "external":
        return file_obj["external"].get("url")
    return None


def _extract_table_rows(block: dict) -> Optional[list[dict]]:
    """从 table block 中提取子行"""
    children = block.get("_children", [])
    rows = [b for b in children if b.get("type") == "table_row"]
    return rows if rows else None


def _block_to_table_md(block: dict, has_header: bool) -> Optional[str]:
    """将 table block 转为 Markdown 表格"""
    rows = _extract_table_rows(block)
    if not rows:
        return None

    lines = []
    for i, row in enumerate(rows):
        cells = row.get("table_row", {}).get("cells", [])
        cell_texts = [" " + _rich_text_to_md(cell).strip() + " " for cell in cells]
        lines.append("|" + "|".join(cell_texts) + "|")
        # 表头分隔线
        if i == 0 and has_header:
            lines.append("|" + "|".join([" --- " for _ in cells]) + "|")

    return "\n".join(lines)


class NotionToMarkdown:
    """将 Notion blocks 转换为标准 Markdown 文本"""

    def __init__(self, image_handler: callable = None):
        """
        Args:
            image_handler: 可选回调，处理图片 URL。
                          签名为 (notion_url: str) -> str，
                          返回处理后的 URL（如上传到图床后的 URL）。
        """
        self._image_handler = image_handler

    def convert(self, blocks: list[dict]) -> str:
        """转换 blocks 列表为 Markdown 字符串"""
        lines = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            btype = block.get("type", "")

            # 列表需要合并处理
            if btype in ("bulleted_list_item", "numbered_list_item"):
                md, consumed = self._convert_list_block(blocks, i, btype)
                lines.append(md)
                i += consumed
                continue

            result = self._convert_block(block)
            if result is not None:
                lines.append(result)
            i += 1

        # 清理多余空行
        return self._cleanup("\n\n".join(lines))

    def _convert_block(self, block: dict) -> Optional[str]:
        """转换单个 block"""
        btype = block.get("type", "")
        handler = getattr(self, f"_handle_{btype}", None)
        if handler:
            return self._strip_none(handler(block))
        # 未支持的类型
        logger.debug(f"notion2md: 未支持的类型 {btype}")
        return self._fallback(block)

    def _strip_none(self, value: Optional[str]) -> Optional[str]:
        """返回 None 或去首尾空白的字符串"""
        return value.strip() if value else None

    # ─── 处理函数 ───

    def _handle_paragraph(self, block: dict) -> str:
        text = _rich_text_to_md(block.get("paragraph", {}).get("rich_text", []))
        return text if text else ""

    def _handle_heading_1(self, block: dict) -> str:
        return "# " + _rich_text_to_md(block.get("heading_1", {}).get("rich_text", []))

    def _handle_heading_2(self, block: dict) -> str:
        return "## " + _rich_text_to_md(block.get("heading_2", {}).get("rich_text", []))

    def _handle_heading_3(self, block: dict) -> str:
        return "### " + _rich_text_to_md(block.get("heading_3", {}).get("rich_text", []))

    def _handle_quote(self, block: dict) -> str:
        text = _rich_text_to_md(block.get("quote", {}).get("rich_text", []))
        return "\n".join("> " + line for line in text.split("\n")) if text else "> "

    def _handle_callout(self, block: dict) -> str:
        callout = block.get("callout", {})
        icon = callout.get("icon", {})
        emoji = icon.get("emoji", "") if icon.get("type") == "emoji" else "💡"
        text = _rich_text_to_md(callout.get("rich_text", []))
        # 不再额外包裹 **，因为 rich_text 中的 bold/italic 已经处理了格式
        return f"> {emoji} {text}" if text else f"> {emoji}"

    def _handle_divider(self, block: dict) -> str:
        return "---"

    def _handle_code(self, block: dict) -> str:
        code = block.get("code", {})
        lang = code.get("language", "") or ""
        rich_text = code.get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich_text)
        return f"```{lang}\n{text}\n```"

    def _handle_image(self, block: dict) -> str:
        image = block.get("image", {})
        url = _notion_file_url(image)
        cap = _rich_text_to_md(image.get("caption", []))

        if self._image_handler and url:
            url = self._image_handler(url)

        if url:
            return f"![{cap}]({url})"
        return f"[图片: {cap or '无标题'}]"

    def _handle_table(self, block: dict) -> str:
        table_obj = block.get("table", {})
        has_header = table_obj.get("has_column_header", False)
        md = _block_to_table_md(block, has_header)
        if md:
            return md
        # 没有子行数据时，返回简单占位
        return "<!-- table -->"

    def _handle_table_row(self, block: dict) -> str:
        # 由 _handle_table 处理，这里不应被单独调用
        return ""

    def _handle_to_do(self, block: dict) -> str:
        to_do = block.get("to_do", {})
        checked = to_do.get("checked", False)
        text = _rich_text_to_md(to_do.get("rich_text", []))
        checkbox = "x" if checked else " "
        return f"- [{checkbox}] {text}"

    def _handle_bookmark(self, block: dict) -> str:
        bookmark = block.get("bookmark", {})
        url = bookmark.get("url", "")
        cap = _rich_text_to_md(bookmark.get("caption", []))
        title = cap or url
        return f"[🔖 {title}]({url})" if url else ""

    def _handle_link_preview(self, block: dict) -> str:
        return self._handle_bookmark(block)

    def _handle_toggle(self, block: dict) -> str:
        toggle = block.get("toggle", {})
        summary = _rich_text_to_md(toggle.get("rich_text", [])) or "展开"

        children_md = ""
        children = block.get("_children", [])
        if children:
            children_md = self.convert(children)

        if children_md.strip():
            return f"<details>\n<summary><b>{summary}</b></summary>\n\n{children_md}\n\n</details>"
        return f"> ▶ **{summary}**"

    def _handle_file(self, block: dict) -> str:
        file_obj = block.get("file", {})
        url = _notion_file_url(file_obj)
        cap = _rich_text_to_md(file_obj.get("caption", []))
        name = cap or (url.split("/")[-1].split("?")[0] if url else "文件")
        return f"[📎 {name}]({url})" if url else f"📎 {name}"

    def _handle_video(self, block: dict) -> str:
        video = block.get("video", {})
        url = _notion_file_url(video)
        cap = _rich_text_to_md(video.get("caption", []))
        if url:
            return f"[🎬 {cap or '视频'}]({url})"
        return f"🎬 {cap or '[视频]'}"

    def _handle_embed(self, block: dict) -> str:
        embed = block.get("embed", {})
        url = embed.get("url", "")
        return f"[📌 {url}]({url})" if url else ""

    def _handle_equation(self, block: dict) -> str:
        expr = block.get("equation", {}).get("expression", "")
        return f"$$\n{expr}\n$$"

    def _handle_synced_block(self, block: dict) -> str:
        children = block.get("_children", [])
        if children:
            return self.convert(children)
        return ""

    def _handle_column_list(self, block: dict) -> str:
        children = block.get("_children", [])
        if children:
            return self.convert(children)
        return ""

    def _handle_column(self, block: dict) -> str:
        children = block.get("_children", [])
        if children:
            return self.convert(children)
        return ""

    def _fallback(self, block: dict) -> str:
        """未支持的类型，尝试提取文本"""
        btype = block.get("type", "unknown")
        content = block.get(btype, {})
        rich_text = content.get("rich_text", [])
        if rich_text:
            return _rich_text_to_md(rich_text)
        return f"<!-- unsupported: {btype} -->"

    # ─── 列表合并处理 ───

    def _convert_list_block(self, blocks: list[dict], start: int, item_type: str) -> tuple[str, int]:
        """将连续的同类列表项合并为 Markdown 列表"""
        items = []
        i = start
        while i < len(blocks) and blocks[i].get("type") == item_type:
            item_md = self._convert_single_list_item(blocks[i], item_type)
            items.append(item_md)
            i += 1

        return "\n".join(items), i - start

    def _convert_single_list_item(self, block: dict, item_type: str) -> str:
        """转换单个列表项，处理嵌套子列表"""
        content = block.get(item_type, {})
        rich_text = content.get("rich_text", [])

        if item_type == "bulleted_list_item":
            prefix = "-"
        else:  # numbered_list_item
            prefix = "1."

        text = _rich_text_to_md(rich_text) or " "
        line = f"{prefix} {text}"

        # 处理嵌套子 blocks
        children = block.get("_children", [])
        if children:
            child_lines = []
            for child in children:
                child_type = child.get("type", "")
                if child_type in ("bulleted_list_item", "numbered_list_item"):
                    child_md = self._convert_single_list_item(child, child_type)
                    child_lines.append(f"    {child_md}")
                elif child_type == "to_do":
                    to_do = child.get("to_do", {})
                    checked = "x" if to_do.get("checked") else " "
                    ctext = _rich_text_to_md(to_do.get("rich_text", []))
                    child_lines.append(f"    - [{checked}] {ctext}")
                elif child_type == "paragraph":
                    ptext = _rich_text_to_md(child.get("paragraph", {}).get("rich_text", []))
                    if ptext:
                        child_lines.append(f"    {ptext}")
            if child_lines:
                line += "\n" + "\n".join(child_lines)

        return line

    # ─── 清理 ───

    @staticmethod
    def _cleanup(md: str) -> str:
        """清理 Markdown 文本中的多余空行"""
        # 去掉超过 2 个的连续空行
        import re
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip()
