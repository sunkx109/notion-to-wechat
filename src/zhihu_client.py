"""知乎文章发布客户端

知乎没有官方开放 API，这里使用基于 Cookie 的认证方式调用内部 API。

⚠️ 注意事项:
1. 需要从浏览器中提取 Cookie（登录知乎后 F12 → Application → Cookies → 复制所有 cookie）
2. 知乎 API 可能随时变更，如遇问题请提取最新的 Cookie 再试
3. 过于频繁的请求可能会触发反爬机制

获取 Cookie 的方法:
1. 在 Chrome 中打开 zhihu.com 并登录
2. F12 → Application → Cookies → zhihu.com
3. 复制以下关键字段的值: z_c0, _xsrf, d_c0, tst, 等
4. 最简单的方法: 在 Console 中执行 `document.cookie` 复制全部

或者使用浏览器扩展 (EditThisCookie 等) 导出 Cookie JSON。
"""

import re
import time
from pathlib import Path
from typing import Optional

import requests

from .utils import logger


class ZhihuClient:
    """知乎文章发布客户端（Cookie 认证）"""

    BASE_URL = "https://www.zhihu.com"
    API_URL = "https://api.zhihu.com"
    ZHUANLAN_URL = "https://zhuanlan.zhihu.com"

    def __init__(self, cookie_string: str):
        """
        Args:
            cookie_string: 知乎 Cookie 字符串，格式: "key1=value1; key2=value2; ..."
        """
        self.cookie_string = cookie_string
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Origin": "https://zhuanlan.zhihu.com",
                "Referer": "https://zhuanlan.zhihu.com/",
            }
        )
        self._session.cookies.update(self._parse_cookies(cookie_string))
        self._xsrf_token = self._extract_xsrf()

    @staticmethod
    def _parse_cookies(cookie_string: str) -> dict:
        """解析 Cookie 字符串为 dict"""
        cookies = {}
        for item in cookie_string.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    def _extract_xsrf(self) -> str:
        """从 Cookie 或 API 中提取 XSRF token"""
        # 优先从 Cookie 中获取 _xsrf
        cookies = self._parse_cookies(self.cookie_string)
        xsrf = cookies.get("_xsrf", "") or cookies.get("XSRF-TOKEN", "")
        if xsrf:
            return xsrf

        # 尝试从知乎首页获取
        try:
            resp = self._session.get(f"{self.BASE_URL}", timeout=10)
            match = re.search(r'_xsrf["\s:=]+["\']([^"\']+)["\']', resp.text)
            if match:
                return match.group(1)
        except Exception:
            pass

        logger.warning("未能提取 XSRF token，部分 API 可能失败")
        return ""

    # ==================== 身份验证 ====================

    def check_login(self) -> dict:
        """验证 Cookie 是否有效，返回当前用户信息"""
        url = f"{self.API_URL}/api/v4/me"
        resp = self._session.get(url, timeout=15)
        data = resp.json()

        if "error" in data:
            logger.error(f"知乎登录验证失败: {data}")
            return {"logged_in": False, "error": data.get("error", {}).get("message", "unknown")}

        user = {
            "logged_in": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "headline": data.get("headline", ""),
        }
        logger.info(f"知乎登录验证成功: {user['name']}")
        return user

    # ==================== 图片上传 ====================

    def upload_image(self, file_path: str) -> Optional[str]:
        """上传图片到知乎，返回图片 URL

        知乎图片上传返回的是 Markdown 格式的图片引用:
        ```
        {"url": "https://picx.zhimg.com/xxx.jpg", "width": 800, "height": 600}
        ```
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"图片文件不存在: {file_path}")
            return None

        url = f"{self.API_URL}/api/v4/images"
        headers = {
            "X-XSRF-TOKEN": self._xsrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

        try:
            with open(path, "rb") as f:
                resp = self._session.post(
                    url,
                    headers=headers,
                    files={"file": (path.name, f)},
                    timeout=30,
                )
            data = resp.json()

            if "url" in data:
                img_url = data["url"]
                logger.info(f"知乎图片上传成功: {img_url[:60]}...")
                return img_url
            else:
                logger.error(f"知乎图片上传失败: {data}")
                return None
        except Exception as e:
            logger.error(f"知乎图片上传异常: {e}")
            return None

    # ==================== 文章操作 ====================

    def create_article(
        self,
        title: str,
        content: str,
        title_image: str = "",
        topics: list = None,
        is_draft: bool = True,
    ) -> dict:
        """创建知乎文章

        Args:
            title: 文章标题
            content: 文章正文（HTML 格式，知乎会自动转换）
            title_image: 封面图 URL
            topics: 话题 ID 列表（选填）
            is_draft: 是否保存为草稿（True=草稿, False=直接发布）

        Returns:
            {"article_id": "...", "url": "...", "is_draft": True/False}
        """
        url = f"{self.BASE_URL}/api/v4/articles"

        body = {
            "title": title,
            "content": content,
            "delta_time": int(time.time()),
            "is_draft": is_draft,
        }

        if title_image:
            body["title_image"] = title_image
        if topics:
            body["topics"] = topics

        headers = {
            "X-XSRF-TOKEN": self._xsrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self._session.post(url, headers=headers, json=body, timeout=30)
        data = resp.json()

        if "id" in data:
            article_id = data["id"]
            # 构建文章链接
            slug = data.get("slug", "")
            if slug:
                article_url = f"https://zhuanlan.zhihu.com/p/{slug}"
            else:
                article_url = f"https://zhuanlan.zhihu.com/p/{article_id}"

            logger.info(f"知乎文章{'草稿' if is_draft else ''}创建成功: {article_url}")
            return {
                "success": True,
                "article_id": article_id,
                "url": article_url,
                "is_draft": is_draft,
            }
        else:
            error_msg = data.get("error", {}).get("message", str(data))
            logger.error(f"知乎文章创建失败: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
            }

    def update_article(
        self,
        article_id: str,
        title: str,
        content: str,
        title_image: str = "",
    ) -> dict:
        """更新已有的知乎文章"""
        url = f"{self.BASE_URL}/api/v4/articles/{article_id}"

        body = {
            "title": title,
            "content": content,
        }
        if title_image:
            body["title_image"] = title_image

        headers = {
            "X-XSRF-TOKEN": self._xsrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self._session.put(url, headers=headers, json=body, timeout=30)
        data = resp.json()

        if "id" in data:
            logger.info(f"知乎文章更新成功: {article_id}")
            return {"success": True, "article_id": article_id}
        else:
            error_msg = data.get("error", {}).get("message", str(data))
            logger.error(f"知乎文章更新失败: {error_msg}")
            return {"success": False, "error": error_msg}

    def publish_article(self, article_id: str) -> bool:
        """发布已保存为草稿的文章"""
        url = f"{self.BASE_URL}/api/v4/articles/{article_id}/publish"

        headers = {
            "X-XSRF-TOKEN": self._xsrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self._session.put(url, headers=headers, timeout=30)
        data = resp.json()

        if resp.status_code == 200 or "id" in data:
            logger.info(f"知乎文章发布成功: {article_id}")
            return True
        else:
            logger.error(f"知乎文章发布失败: {data}")
            return False

    def delete_article(self, article_id: str) -> bool:
        """删除知乎文章"""
        url = f"{self.BASE_URL}/api/v4/articles/{article_id}"

        headers = {
            "X-XSRF-TOKEN": self._xsrf_token,
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = self._session.delete(url, headers=headers, timeout=30)
        data = resp.json()

        ok = resp.status_code == 200 or "id" in data
        if ok:
            logger.info(f"知乎文章已删除: {article_id}")
        else:
            logger.error(f"知乎文章删除失败: {data}")
        return ok

    def get_article(self, article_id: str) -> dict:
        """获取知乎文章详情"""
        url = f"{self.BASE_URL}/api/v4/articles/{article_id}"
        resp = self._session.get(url, timeout=15)
        return resp.json()
