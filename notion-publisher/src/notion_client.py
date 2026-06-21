"""Notion API 封装

参考文档: https://developers.notion.com/reference/

使用 Notion API v1，直接通过 requests 调用 HTTP 接口。
"""

from typing import Optional

import requests

from .utils import logger


class NotionClient:
    """Notion API 客户端"""

    BASE_URL = "https://api.notion.com/v1"
    API_VERSION = "2022-06-28"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.post(url, headers=self._headers, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.patch(url, headers=self._headers, json=body or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ==================== 页面操作 ====================

    def get_page(self, page_id: str) -> dict:
        """获取页面元数据（标题、属性等）"""
        return self._get(f"/pages/{page_id}")

    def get_page_title(self, page_id: str) -> str:
        """提取页面标题"""
        page = self.get_page(page_id)
        # 标题在 properties 中，不同数据库结构不同
        properties = page.get("properties", {})
        for prop in properties.values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                return "".join(t.get("plain_text", "") for t in title_parts)
        # 回退：用 icon 或 page_id
        return page_id

    def get_page_blocks(self, page_id: str, page_size: int = 100) -> list[dict]:
        """获取页面的所有 blocks（含分页）"""
        all_blocks = []
        start_cursor = None

        while True:
            params = {"page_size": page_size}
            if start_cursor:
                params["start_cursor"] = start_cursor

            data = self._get(f"/blocks/{page_id}/children", params=params)
            blocks = data.get("results", [])
            all_blocks.extend(blocks)

            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        logger.info(f"页面 {page_id[:8]}... 共获取 {len(all_blocks)} 个 blocks")
        return all_blocks

    def get_block_children(self, block_id: str) -> list[dict]:
        """获取 block 的子 blocks（如 toggle、column 内的内容）"""
        all_blocks = []
        start_cursor = None

        while True:
            params = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor

            data = self._get(f"/blocks/{block_id}/children", params=params)
            all_blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        return all_blocks

    # ==================== 数据库操作 ====================

    def query_database(
        self,
        database_id: str,
        filter_obj: dict = None,
        sorts: list = None,
        page_size: int = 100,
    ) -> list[dict]:
        """查询数据库，返回所有匹配页面"""
        all_pages = []
        start_cursor = None

        body = {}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        while True:
            payload = {**body, "page_size": page_size}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            data = self._post(f"/databases/{database_id}/query", payload)
            pages = data.get("results", [])
            all_pages.extend(pages)

            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")

        logger.info(f"数据库查询到 {len(all_pages)} 个页面")
        return all_pages

    def update_page_property(self, page_id: str, property_name: str, value: dict) -> dict:
        """更新页面的某个属性（如将状态改为"已发布"）

        Args:
            page_id: 页面 ID
            property_name: 属性名
            value: 属性值，如 {"status": {"name": "已发布"}}
        """
        body = {"properties": {property_name: value}}
        return self._patch(f"/pages/{page_id}", body)

    def update_page_status(self, page_id: str, status_field: str, status_value: str) -> dict:
        """便捷方法：更新页面的状态属性"""
        return self.update_page_property(
            page_id,
            status_field,
            {"status": {"name": status_value}},
        )

    # ==================== 搜索 ====================

    def search(self, query: str) -> list[dict]:
        """搜索页面或数据库"""
        body = {
            "query": query,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        data = self._post("/search", body)
        return data.get("results", [])
