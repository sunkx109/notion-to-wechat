"""发布编排器 v2：Notion → Markdown → mdnice 渲染 → 多平台发布"""

import re
from pathlib import Path
from typing import Optional

from .converter import _notion_file_url, _download_image
from .notion_client import NotionClient
from .notion2md import NotionToMarkdown
from .renderer_bridge import render_markdown
from .wechat_client import WeChatClient
from .zhihu_client import ZhihuClient
from .utils import logger


class PublisherV2:
    """编排 Notion → Markdown → mdnice 渲染 → 微信/知乎 发布的完整流程"""

    def __init__(
        self,
        notion_client: NotionClient,
        config: dict,
        wechat_client: WeChatClient = None,
        zhihu_client: ZhihuClient = None,
    ):
        self.notion = notion_client
        self.wechat = wechat_client
        self.zhihu = zhihu_client
        self.config = config
        self.field_map = config.get("field_mapping", {})
        self.publish_opts = config.get("publish", {})

    # ==================== 单篇发布到多个平台 ====================

    def publish_to_platforms(
        self,
        page_id: str,
        platforms: list[str] = None,
    ) -> dict:
        """发布单篇到指定平台

        Args:
            page_id: Notion 页面 ID
            platforms: 发布平台列表，如 ["wechat", "zhihu"]，默认取 config

        Returns:
            {"title": str, "wechat": {...}, "zhihu": {...}}
        """
        if platforms is None:
            platforms = []
            if self.wechat:
                platforms.append("wechat")
            if self.zhihu:
                platforms.append("zhihu")

        logger.info(f"===== 处理页面: {page_id}, 平台: {platforms} =====")

        # 1. 拉取页面
        page = self.notion.get_page(page_id)
        blocks = self.notion.get_page_blocks(page_id)
        self._fetch_all_children(blocks)

        title = self._extract_title(page)
        cover_url = _notion_file_url(page.get("cover") or {})

        # 2. 处理图片：下载 → 上传到目标平台 → 获取平台 URL
        image_map = self._process_images(blocks, platforms)

        # 3. Notion blocks → Markdown（把图片 URL 替换为平台 URL）
        md = self._blocks_to_markdown(blocks, title, image_map, "wechat" if "wechat" in platforms else (platforms[0] if platforms else "generic"))

        # 4. 准备封面图（各平台上传）
        cover_images = {}
        if cover_url:
            cover_images = self._process_cover_image(cover_url, platforms)

        result = {"title": title}

        # 5. 发布到微信
        if "wechat" in platforms and self.wechat:
            result["wechat"] = self._publish_to_wechat(
                title, md, cover_images.get("wechat", "")
            )

        # 6. 发布到知乎
        if "zhihu" in platforms and self.zhihu:
            # 知乎用单独的 Markdown（可能包含知乎图片 URL）
            zh_md = self._blocks_to_markdown(blocks, title, image_map, "zhihu")
            result["zhihu"] = self._publish_to_zhihu(
                title, zh_md, cover_images.get("zhihu", "")
            )

        # 7. 更新 Notion 状态
        if self.publish_opts.get("update_notion_status", True):
            self._update_notion_status(page, page_id)

        logger.info(f"✅ 页面处理完成: {title}")
        return result

    # ==================== 自动批量发布 ====================

    def auto_publish(
        self,
        platforms: list[str] = None,
    ) -> list[dict]:
        """自动扫描数据库中「待发布」的文章并发布"""
        db_id = self.config.get("notion", {}).get("database_id", "")
        if not db_id:
            logger.error("未配置 database_id")
            return [{"success": False, "error": "未配置 database_id"}]

        status_field = self.field_map.get("status", "Status")
        pending_value = self.field_map.get("pending", "待发布")

        filter_obj = {"property": status_field, "status": {"equals": pending_value}}
        pages = self.notion.query_database(db_id, filter_obj=filter_obj)

        logger.info(f"找到 {len(pages)} 篇待发布文章")
        results = []
        for page in pages:
            result = self.publish_to_platforms(page["id"], platforms=platforms)
            results.append(result)
        return results

    # ==================== 内部方法 ====================

    def _fetch_all_children(self, blocks: list[dict]):
        """递归拉取所有子 blocks"""
        for block in blocks:
            if block.get("has_children"):
                try:
                    children = self.notion.get_block_children(block["id"])
                    block["_children"] = children
                    self._fetch_all_children(children)
                except Exception as e:
                    logger.warning(f"拉取子 blocks 失败: {e}")

    def _extract_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                return title.strip() if title.strip() else "无标题"
        return page.get("id", "无标题")[:8]

    def _process_images(
        self, blocks: list[dict], platforms: list[str]
    ) -> dict[str, dict[str, str]]:
        """处理文章内图片：下载 Notion 图片 → 上传到各平台 → 返回 URL 映射

        Returns:
            {notion_url: {"wechat": wechat_url, "zhihu": zhihu_url}}
        """
        image_map = {}  # notion_url → {platform: uploaded_url}

        def _collect_images(blks):
            for b in blks:
                btype = b.get("type", "")
                if btype == "image":
                    url = _notion_file_url(b.get("image", {}))
                    if url and url not in image_map:
                        image_map[url] = {}
                # 递归子 blocks
                for child in b.get("_children", []):
                    _collect_images([child])

        _collect_images(blocks)

        if not image_map:
            return image_map

        logger.info(f"处理 {len(image_map)} 张图片...")

        for notion_url in image_map:
            tmp_path = _download_image(notion_url)
            if not tmp_path:
                continue

            # 上传到微信
            if "wechat" in platforms and self.wechat:
                try:
                    wx_url = self.wechat.upload_content_image(tmp_path)
                    image_map[notion_url]["wechat"] = wx_url
                    logger.info(f"  图片 → 微信: {wx_url[:50]}...")
                except Exception as e:
                    logger.warning(f"  图片上传微信失败: {e}")

            # 上传到知乎
            if "zhihu" in platforms and self.zhihu:
                try:
                    zh_url = self.zhihu.upload_image(tmp_path)
                    if zh_url:
                        image_map[notion_url]["zhihu"] = zh_url
                        logger.info(f"  图片 → 知乎: {zh_url[:50]}...")
                except Exception as e:
                    logger.warning(f"  图片上传知乎失败: {e}")

            # 清理临时文件
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

        return image_map

    def _process_cover_image(
        self, cover_url: str, platforms: list[str]
    ) -> dict[str, str]:
        """处理封面图上传，返回 {platform: url_or_media_id}"""
        result = {}
        tmp_path = _download_image(cover_url)
        if not tmp_path:
            return result

        if "wechat" in platforms and self.wechat:
            try:
                material = self.wechat.upload_material(tmp_path, "image")
                result["wechat"] = material.get("media_id", "")
            except Exception as e:
                logger.warning(f"封面图上传微信失败: {e}")

        if "zhihu" in platforms and self.zhihu:
            try:
                zh_url = self.zhihu.upload_image(tmp_path)
                if zh_url:
                    result["zhihu"] = zh_url
            except Exception as e:
                logger.warning(f"封面图上传知乎失败: {e}")

        try:
            Path(tmp_path).unlink()
        except Exception:
            pass

        return result

    def _upload_placeholder_thumb(self) -> str:
        """生成并上传占位封面图"""
        import base64, tempfile

        # 300x200 浅灰 PNG — 合法的 base64 编码 PNG 文件
        # 这是一个有效的灰色方块 PNG，避免手工生成 PNG 的兼容性问题
        PLACEHOLDER_B64 = (
            "iVBORw0KGgoAAAANSUhEUgAAASwAAADIAQMAAABqVbr3AAAAA1BMVEUAAACnej3aAAAAAXRS"
            "TlMAQObYZgAAAAFiS0dEAIgFHUgAAAAJcEhZcwAACxMAAAsTAQCanBgAAAAHdElNRQfmChQQ"
            "GQwJGS5pAAAANklEQVR42u3BMQEAAADCIPunNsVeYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "AAAAAAAAAAAAAFwHakAAAXDBCpAAAAAASUVORK5CYII="
        )

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(base64.b64decode(PLACEHOLDER_B64))
                tmp_path = f.name

            result = self.wechat.upload_material(tmp_path, "image")
            Path(tmp_path).unlink(missing_ok=True)
            media_id = result.get("media_id", "")
            if media_id:
                logger.info(f"占位封面已上传: {media_id}")
            return media_id
        except Exception as e:
            logger.warning(f"占位封面上传失败: {e}")
            return ""


    def _blocks_to_markdown(
        self,
        blocks: list[dict],
        title: str,
        image_map: dict,
        platform: str,
    ) -> str:
        """将 blocks 转为 Markdown，替换图片 URL 为目标平台 URL"""

        def _image_handler(notion_url: str) -> str:
            mapped = image_map.get(notion_url, {})
            plat_url = mapped.get(platform) or mapped.get("wechat") or mapped.get("zhihu")
            return plat_url or notion_url

        converter = NotionToMarkdown(image_handler=_image_handler)
        md = converter.convert(blocks)

        # 如果 Markdown 中没有标题（h1），在开头加上
        if not md.startswith("# "):
            md = f"# {title}\n\n{md}"

        return md

    def _publish_to_wechat(
        self, title: str, markdown: str, thumb_media_id: str
    ) -> dict:
        """发布到微信: Markdown → mdnice 渲染 → 微信草稿"""
        try:
            html = render_markdown(markdown, platform="wechat")

            # 如果没有封面图，生成一个占位图上传
            if not thumb_media_id:
                thumb_media_id = self._upload_placeholder_thumb()

            auto = self.publish_opts.get("auto_publish", False)
            draft_id = self.wechat.create_draft(
                title=title[:64],
                content=html,
                thumb_media_id=thumb_media_id,
            )

            result = {
                "success": True,
                "draft_media_id": draft_id,
                "published": False,
            }

            if auto:
                pid = self.wechat.publish(draft_id)
                if pid:
                    result["published"] = True
                    result["publish_id"] = pid

            return result

        except Exception as e:
            logger.error(f"微信发布失败: {e}")
            return {"success": False, "error": str(e)}

    def _publish_to_zhihu(
        self, title: str, markdown: str, title_image: str
    ) -> dict:
        """发布到知乎: Markdown → mdnice 渲染 → 知乎文章"""
        try:
            html = render_markdown(markdown, platform="zhihu")

            as_draft = self.publish_opts.get("zhihu_as_draft", True)
            zh_result = self.zhihu.create_article(
                title=title,
                content=html,
                title_image=title_image,
                is_draft=as_draft,
            )

            if zh_result.get("success"):
                return {
                    "success": True,
                    "article_id": zh_result["article_id"],
                    "url": zh_result.get("url", ""),
                }
            else:
                return {"success": False, "error": zh_result.get("error", "?")}

        except Exception as e:
            logger.error(f"知乎发布失败: {e}")
            return {"success": False, "error": str(e)}

    def _update_notion_status(self, page: dict, page_id: str):
        """更新 Notion 页面状态为「已发布」"""
        status_field = self.field_map.get("status", "Status")
        published_value = self.field_map.get("published", "已发布")

        props = page.get("properties", {})
        if status_field not in props or props[status_field].get("type") != "status":
            return

        try:
            self.notion.update_page_status(page_id, status_field, published_value)
            logger.info(f"Notion 状态 → 「{published_value}」")
        except Exception as e:
            logger.warning(f"更新 Notion 状态失败: {e}")


# ============================================================
# 兼容旧接口
# ============================================================

def fetch_page_to_json(notion_client: NotionClient, page_id: str, output_path: str = None) -> dict:
    """将 Notion 页面拉取为本地 JSON"""
    import json

    page = notion_client.get_page(page_id)
    blocks = notion_client.get_page_blocks(page_id)

    for block in blocks:
        if block.get("has_children"):
            try:
                block["_children"] = notion_client.get_block_children(block["id"])
            except Exception:
                pass

    result = {"page": page, "blocks": blocks}
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"页面已保存: {output_path}")

    return result


def convert_json_to_markdown(data: dict) -> str:
    """将 fetch_page_to_json 的结果转为 Markdown"""
    blocks = data.get("blocks", [])
    converter = NotionToMarkdown()
    return converter.convert(blocks)
