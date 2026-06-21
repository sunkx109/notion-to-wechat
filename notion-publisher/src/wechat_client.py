"""微信公众平台 API 封装

参考文档: https://developers.weixin.qq.com/doc/offiaccount/Drafts/Drafts.html

关键 API:
- 获取 access_token: GET /cgi-bin/token
- 上传图文内图片: POST /cgi-bin/media/uploadimg
- 上传永久素材: POST /cgi-bin/material/add_material
- 创建草稿: POST /cgi-bin/draft/add
- 发布: POST /cgi-bin/freepublish/submit
- 获取草稿列表: POST /cgi-bin/draft/batchget
"""

import json
import time
from pathlib import Path
from typing import Optional

import requests

from .utils import logger


class WeChatClient:
    """微信公众平台 API 客户端"""

    BASE_URL = "https://api.weixin.qq.com"

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    # ==================== Access Token ====================

    def _ensure_token(self):
        """确保 access_token 有效"""
        if self._access_token and time.time() < self._token_expires_at - 300:
            return

        url = f"{self.BASE_URL}/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        if "access_token" not in data:
            logger.error(f"获取 access_token 失败: {data}")
            raise RuntimeError(f"微信 access_token 获取失败: {data.get('errmsg', 'unknown error')}")

        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200)
        logger.info("access_token 已刷新")

    @property
    def access_token(self) -> str:
        self._ensure_token()
        return self._access_token  # type: ignore


    def _post_json(self, path: str, body: dict, timeout: int = 30) -> dict:
        r"""POST JSON with proper UTF-8 encoding (no \uXXXX escaping for CJK)"""
        import json
        url = f"{self.BASE_URL}{path}"
        resp = requests.post(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout,
        )
        return resp.json()

    def _get(self, path: str, timeout: int = 15) -> dict:
        url = f"{self.BASE_URL}{path}"
        resp = requests.get(url, timeout=timeout)
        return resp.json()

    # ==================== 图片上传（图文内图片） ====================

    def upload_content_image(self, file_path: str) -> str:
        """上传图文消息内的图片，返回微信 CDN URL

        图片大小不超过 10MB，支持 bmp/png/jpeg/jpg/gif 格式。
        返回的 URL 仅用于图文消息内容中，不可作为封面。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"图片文件不存在: {file_path}")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError(f"图片超过 10MB 限制: {file_path}")

        url = f"{self.BASE_URL}/cgi-bin/media/uploadimg?access_token={self.access_token}"
        with open(path, "rb") as f:
            resp = requests.post(
                url,
                files={"media": (path.name, f, "image/png" if path.suffix == ".png" else "image/jpeg")},
                timeout=30,
            )
        data = resp.json()

        if "url" not in data:
            logger.error(f"上传图片失败: {data}")
            raise RuntimeError(f"微信图片上传失败: {data.get('errmsg', 'unknown error')}")

        logger.info(f"图片已上传: {data['url']}")
        return data["url"]

    # ==================== 永久素材上传（封面图） ====================

    def upload_material(self, file_path: str, material_type: str = "image") -> dict:
        """上传永久素材（封面图等），返回 {media_id, url}"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"素材文件不存在: {file_path}")

        url = (
            f"{self.BASE_URL}/cgi-bin/material/add_material"
            f"?access_token={self.access_token}&type={material_type}"
        )
        with open(path, "rb") as f:
            resp = requests.post(
                url,
                files={"media": (path.name, f, "image/png" if path.suffix == ".png" else "image/jpeg")},
                timeout=30,
            )
        data = resp.json()

        if "media_id" not in data:
            logger.error(f"上传永久素材失败: {data}")
            raise RuntimeError(f"微信素材上传失败: {data.get('errmsg', 'unknown error')}")

        logger.info(f"永久素材已上传: media_id={data['media_id']}")
        return {"media_id": data["media_id"], "url": data.get("url", "")}

    # ==================== 草稿箱 ====================

    def create_draft(
        self,
        title: str,
        content: str,
        thumb_media_id: str = "",
        need_open_comment: int = 0,
        only_fans_can_comment: int = 0,
    ) -> str:
        """创建草稿，返回草稿 media_id

        Args:
            title: 标题 (≤64 字)
            content: 正文 HTML (微信富文本格式)
            thumb_media_id: 封面图永久素材 media_id
            need_open_comment: 是否开启评论 (0/1)
            only_fans_can_comment: 是否仅粉丝可评论 (0/1)
        """
        url = f"{self.BASE_URL}/cgi-bin/draft/add?access_token={self.access_token}"
        article = {
            "title": title,
            "content": content,
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": only_fans_can_comment,
        }
        # thumb_media_id 为必填，但为空时先尝试不传（某些情况下微信接受）
        if thumb_media_id:
            article["thumb_media_id"] = thumb_media_id

        body = {"articles": [article]}
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        data = resp.json()

        if "media_id" not in data:
            logger.error(f"创建草稿失败: {data}")
            raise RuntimeError(f"微信草稿创建失败: {data.get('errmsg', 'unknown error')}")

        logger.info(f"草稿已创建: media_id={data['media_id']}")
        return data["media_id"]

    def update_draft(
        self,
        media_id: str,
        index: int,
        title: str,
        content: str,
        thumb_media_id: str = "",
    ) -> bool:
        """更新已有草稿"""
        url = f"{self.BASE_URL}/cgi-bin/draft/update?access_token={self.access_token}"
        body = {
            "media_id": media_id,
            "index": index,
            "articles": {
                "title": title,
                "content": content,
                "thumb_media_id": thumb_media_id,
            },
        }
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        data = resp.json()

        if data.get("errcode", -1) != 0:
            logger.error(f"更新草稿失败: {data}")
            return False

        logger.info(f"草稿已更新: media_id={media_id}")
        return True

    def list_drafts(self, offset: int = 0, count: int = 20) -> list[dict]:
        """列出草稿列表"""
        url = f"{self.BASE_URL}/cgi-bin/draft/batchget?access_token={self.access_token}"
        body = {
            "offset": offset,
            "count": count,
            "no_content": 1,  # 不返回正文，节省流量
        }
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        data = resp.json()

        if "item" not in data:
            logger.error(f"获取草稿列表失败: {data}")
            return []

        total = data.get("total_count", 0)
        items = data["item"]
        logger.info(f"草稿列表: 共 {total} 条，当前页 {len(items)} 条")
        return items

    def get_draft(self, media_id: str) -> dict:
        """获取单个草稿详情"""
        url = f"{self.BASE_URL}/cgi-bin/draft/get?access_token={self.access_token}"
        body = {"media_id": media_id}
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        return resp.json()

    def delete_draft(self, media_id: str) -> bool:
        """删除草稿"""
        url = f"{self.BASE_URL}/cgi-bin/draft/delete?access_token={self.access_token}"
        body = {"media_id": media_id}
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        data = resp.json()

        ok = data.get("errcode", -1) == 0
        if ok:
            logger.info(f"草稿已删除: media_id={media_id}")
        else:
            logger.error(f"删除草稿失败: {data}")
        return ok

    # ==================== 发布 ====================

    def publish(self, media_id: str) -> Optional[str]:
        """发布草稿，返回 publish_id 或 None

        注意: 公众号每天有限制发布次数（服务号每月 4 次群发，订阅号每天 1 次群发）。
        这里使用「发布」接口（不占用群发配额，但不会推送给全部粉丝，会出现在主页）。
        """
        url = f"{self.BASE_URL}/cgi-bin/freepublish/submit?access_token={self.access_token}"
        body = {"media_id": media_id}
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=30)
        data = resp.json()

        if "publish_id" not in data:
            logger.error(f"发布失败: {data}")
            return None

        logger.info(f"发布成功: publish_id={data.get('publish_id')}, msg_id={data.get('msg_data_id')}")
        return data.get("publish_id")

    def get_publish_status(self, publish_id: str) -> dict:
        """查询发布状态"""
        url = f"{self.BASE_URL}/cgi-bin/freepublish/get?access_token={self.access_token}"
        body = {"publish_id": publish_id}
        resp = requests.post(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, timeout=15)
        data = resp.json()
        return data
