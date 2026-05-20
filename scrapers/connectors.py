"""
Personal Memory Engine — 数据源连接器框架
=========================================
支持多种数据源接入：
- OAuth接入（GitHub/Gmail/Notion等）
- REST API轮询
- 本地文件系统监听
- 微信（wcfrog）
- 通用Webhook

每20分钟自动轮询拉取数据，清洗后注入记忆引擎

All HTTP communication uses stdlib urllib.request (no pip dependencies).
"""

from __future__ import annotations
import abc
import json
import logging
import time
import urllib.request
import urllib.error
import email
import email.policy
import imaplib
import hmac
import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── 公共数据类型 ─────────────────────────────


@dataclass
class ScrapedData:
    """采集到的原始数据"""
    source_type: str         # "github", "email", "wechat", "web", "rss"
    source_id: str           # 数据源标识
    items: list[dict]        # 数据条目列表
    fetched_at: float = 0.0  # 采集时间戳
    metadata: dict = field(default_factory=dict)


@dataclass
class ConnectorConfig:
    """连接器配置"""
    name: str
    type: str  # "oauth" | "rest" | "webhook" | "local"
    base_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_url: Optional[str] = None
    scope: str = ""
    poll_interval: int = 1200  # 秒，默认20分钟
    enabled: bool = True
    extra: dict = field(default_factory=dict)


# ─── HTTP 工具函数（替代 httpx） ──────────────


def _urllib_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    data: Optional[dict | str | bytes] = None,
    timeout: float = 30.0,
) -> tuple[int, dict, str]:
    """
    使用 urllib.request 发起 HTTP 请求。

    Returns:
        (status_code, response_headers_dict, response_body_str)
    """
    all_headers = {"User-Agent": "PersonalMemoryEngine/0.1.0"}
    if headers:
        all_headers.update(headers)

    body: Optional[bytes] = None
    if data is not None:
        if isinstance(data, dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            if "Content-Type" not in all_headers:
                all_headers["Content-Type"] = "application/json; charset=utf-8"
        elif isinstance(data, str):
            body = data.encode("utf-8")
            if "Content-Type" not in all_headers:
                all_headers["Content-Type"] = "text/plain; charset=utf-8"
        else:
            body = data

    req = urllib.request.Request(url, data=body, headers=all_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            resp_headers = dict(resp.headers)
            raw = resp.read()
            # 尝试用 utf-8 解码，失败则用 iso-8859-1
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("iso-8859-1")
            return status, resp_headers, text
    except urllib.error.HTTPError as e:
        status = e.code
        resp_headers = dict(e.headers)
        raw = e.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("iso-8859-1")
        return status, resp_headers, text
    except urllib.error.URLError as e:
        logger.error(f"URLError requesting {url}: {e.reason}")
        return 0, {}, str(e.reason)


def _urllib_request_json(
    url: str,
    method: str = "GET",
    headers: Optional[dict[str, str]] = None,
    data: Optional[dict] = None,
    timeout: float = 30.0,
) -> tuple[int, dict, Any]:
    """
    发起 HTTP 请求并自动解析 JSON 响应。

    Returns:
        (status_code, response_headers, parsed_json_or_raw_text)
    """
    status, resp_headers, text = _urllib_request(url, method, headers, data, timeout)
    if status >= 200 and status < 300:
        try:
            return status, resp_headers, json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return status, resp_headers, text
    return status, resp_headers, text


# ─── 基类 ─────────────────────────────────────


class BaseConnector(abc.ABC):
    """数据源连接器基类"""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._last_fetch: float = 0

    # ── urllib 辅助方法（替代 _http_client） ──

    def _request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        data: Optional[dict | str | bytes] = None,
        timeout: float = 30.0,
    ) -> tuple[int, dict, str]:
        """使用内部配置发起 HTTP 请求（urllib 实现）"""
        return _urllib_request(url, method, headers, data, timeout)

    def _request_json(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        data: Optional[dict] = None,
        timeout: float = 30.0,
    ) -> tuple[int, dict, Any]:
        """发起 HTTP 请求并返回 JSON 解析结果"""
        return _urllib_request_json(url, method, headers, data, timeout)

    # ── 抽象接口 ──

    @property
    @abc.abstractmethod
    def source_type(self) -> str:
        """数据源类型标识"""
        ...

    @abc.abstractmethod
    def fetch(self) -> ScrapedData:
        """执行一次数据采集（同步）"""
        ...

    def validate(self) -> bool:
        """验证连接配置是否有效"""
        return True

    def start(self):
        """启动连接器"""
        logger.debug(f"Connector {self.config.name} started (no-op)")

    def stop(self):
        """停止连接器"""
        logger.debug(f"Connector {self.config.name} stopped (no-op)")


# ─── 注册中心 ─────────────────────────────────


class ConnectorRegistry:
    """连接器注册中心 — 管理所有数据源"""

    def __init__(self):
        self._connectors: dict[str, BaseConnector] = {}
        self._running = False

    def register(self, connector: BaseConnector):
        """注册一个数据源连接器"""
        self._connectors[connector.config.name] = connector
        logger.info(f"Registered connector: {connector.config.name} ({connector.source_type})")

    def unregister(self, name: str):
        """注销连接器"""
        if name in self._connectors:
            del self._connectors[name]
            logger.info(f"Unregistered connector: {name}")

    def get(self, name: str) -> Optional[BaseConnector]:
        return self._connectors.get(name)

    @property
    def all(self) -> list[BaseConnector]:
        return list(self._connectors.values())

    async def fetch_all(self) -> list[ScrapedData]:
        """采集所有已注册且启用的数据源（保持 async 供外部 await 调用，内部调用同步 fetch）"""
        results = []
        for connector in self._connectors.values():
            if not connector.config.enabled:
                continue
            try:
                connector.start()
                data = connector.fetch()
                results.append(data)
                logger.info(f"Fetched {len(data.items)} items from {connector.config.name}")
            except Exception as e:
                logger.error(f"Failed to fetch from {connector.config.name}: {e}")
        return results

    async def start_all(self):
        """启动所有连接器"""
        self._running = True
        for connector in self._connectors.values():
            if connector.config.enabled:
                connector.start()

    async def stop_all(self):
        """停止所有连接器"""
        self._running = False
        for connector in self._connectors.values():
            connector.stop()

    def handle_webhook(self, webhook_name: str, payload: dict, headers: Optional[dict] = None) -> Optional[ScrapedData]:
        """
        处理推模式 Webhook 数据。

        在注册的连接器中查找名称匹配且为 WebhookReceiver 子类的实例，
        将 payload 注入后返回 ScrapedData。

        Args:
            webhook_name: Webhook 连接器名称（对应 ConnectorConfig.name）
            payload:      推送的 JSON 数据
            headers:      推送的 HTTP 请求头（用于签名验证）

        Returns:
            ScrapedData 若找到对应接收器并处理成功，否则 None
        """
        connector = self._connectors.get(webhook_name)
        if connector is None:
            logger.warning(f"No connector found for webhook: {webhook_name}")
            return None
        if not isinstance(connector, WebhookReceiver):
            logger.warning(f"Connector {webhook_name} is not a WebhookReceiver")
            return None
        try:
            return connector.receive(payload, headers)
        except Exception as e:
            logger.error(f"Webhook {webhook_name} processing failed: {e}")
            return None


# ─── 内置连接器 ──────────────────────────────


class RSSConnector(BaseConnector):
    """RSS 2.0 / Atom Feed 连接器 — 支持双格式解析"""

    @property
    def source_type(self) -> str:
        return "rss"

    def fetch(self) -> ScrapedData:
        url = self.config.base_url
        if not url:
            raise ValueError("RSSConnector requires base_url in config")

        status, resp_headers, text = self._request(url)
        if status >= 300 or status == 0:
            raise RuntimeError(f"Failed to fetch RSS feed: HTTP {status}")

        items = []
        root = ET.fromstring(text)

        # ── 尝试识别格式 ──
        # Atom: <feed xmlns="http://www.w3.org/2005/Atom">
        # RSS:  <rss version="2.0"><channel>...

        if root.tag == "{http://www.w3.org/2005/Atom}feed":
            items = self._parse_atom(root)
        elif root.tag == "rss" or root.tag.lower() == "rss":
            items = self._parse_rss2(root)
        else:
            # 兜底：试着同时查两种
            items = self._parse_atom(root)
            if not items:
                items = self._parse_rss2(root)

        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )

    # ── Atom 解析 ──

    @staticmethod
    def _parse_atom(root: ET.Element) -> list[dict]:
        """解析 Atom 格式 (RFC 4287)"""
        ns = "http://www.w3.org/2005/Atom"
        items = []
        for entry in root.iter(f"{{{ns}}}entry"):
            title_el = entry.find(f"{{{ns}}}title")
            link_el = entry.find(f"{{{ns}}}link")
            summary_el = entry.find(f"{{{ns}}}summary")
            content_el = entry.find(f"{{{ns}}}content")
            published_el = entry.find(f"{{{ns}}}published")
            updated_el = entry.find(f"{{{ns}}}updated")
            author_el = entry.find(f"{{{ns}}}author")

            # link 可能是 <link href="..."/> 或多个 <link rel="alternate" href="..."/>
            href = ""
            if link_el is not None:
                href = link_el.get("href", "") or ""
            if not href:
                # 遍历查找 alternate link
                for lnk in entry.findall(f"{{{ns}}}link"):
                    rel = lnk.get("rel", "alternate")
                    if rel == "alternate" or rel == "":
                        href = lnk.get("href", "") or ""
                        if href:
                            break

            content_text = ""
            if content_el is not None:
                content_text = content_el.text or ""
                # Atom content 可能包裹在 CDATA 或内含 HTML
                if not content_text:
                    content_text = ET.tostring(content_el, encoding="unicode", method="text")
            text = summary_el.text if summary_el is not None else content_text

            author_name = ""
            if author_el is not None:
                name_el = author_el.find(f"{{{ns}}}name")
                if name_el is not None:
                    author_name = name_el.text or ""

            items.append({
                "title": title_el.text if title_el is not None else "",
                "url": href,
                "summary": text,
                "published": published_el.text if published_el is not None else (updated_el.text if updated_el is not None else ""),
                "author": author_name,
                "fetched_at": time.time(),
                "format": "atom",
            })
        return items

    # ── RSS 2.0 解析 ──

    @staticmethod
    def _parse_rss2(root: ET.Element) -> list[dict]:
        """解析 RSS 2.0 格式"""
        items = []
        channel = root.find("channel")
        if channel is None:
            return items

        for item in channel.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pubdate_el = item.find("pubDate")
            author_el = item.find("author")
            guid_el = item.find("guid")

            items.append({
                "title": title_el.text if title_el is not None else "",
                "url": link_el.text if link_el is not None else "",
                "summary": desc_el.text if desc_el is not None else "",
                "published": pubdate_el.text if pubdate_el is not None else "",
                "author": author_el.text if author_el is not None else "",
                "guid": guid_el.text if guid_el is not None else "",
                "fetched_at": time.time(),
                "format": "rss2",
            })
        return items


class GitHubConnector(BaseConnector):
    """GitHub OAuth连接器 — 拉取issues/PRs/commits"""

    @property
    def source_type(self) -> str:
        return "github"

    def _github_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"token {self.config.access_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.config.access_token:
            headers["Authorization"] = f"token {self.config.access_token}"
        return headers

    def fetch(self) -> ScrapedData:
        items = []
        urls = [
            "https://api.github.com/notifications",
            "https://api.github.com/user/repos?sort=updated&per_page=10",
        ]

        for url in urls:
            try:
                status, resp_headers, data = self._request_json(url, headers=self._github_headers())
                if status >= 200 and status < 300:
                    if isinstance(data, list):
                        items.extend(data)
                    elif isinstance(data, dict):
                        items.append(data)
                else:
                    logger.warning(f"github fetch {url} failed: HTTP {status}")
            except Exception as e:
                logger.warning(f"github fetch {url} failed: {e}")

        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )

    def validate(self) -> bool:
        """验证token有效性"""
        try:
            status, _, _ = self._request_json("https://api.github.com/user", headers=self._github_headers())
            return status == 200
        except Exception:
            return False


class WebScraperConnector(BaseConnector):
    """通用网页抓取连接器"""

    @property
    def source_type(self) -> str:
        return "web"

    def __init__(self, config: ConnectorConfig, urls: list[str]):
        super().__init__(config)
        self.urls = urls

    def fetch(self) -> ScrapedData:
        items = []
        for url in self.urls:
            try:
                status, resp_headers, text = self._request(url)
                items.append({
                    "url": url,
                    "content": text[:10000],  # 限制大小
                    "status_code": status,
                    "fetched_at": time.time(),
                })
            except Exception as e:
                logger.warning(f"web scrape {url} failed: {e}")

        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )


# ─── 新增：IMAP 邮件连接器 ───────────────────


class ImapEmailConnector(BaseConnector):
    """
    IMAP 邮件连接器 — 专为 QQ 邮箱设计

    配置示例:
        ConnectorConfig(
            name="qqmail",
            type="rest",
            extra={
                "imap_host": "imap.qq.com",
                "imap_port": 993,
                "username": "123456@qq.com",
                "password": "授权码",       # QQ邮箱需使用授权码
                "mailbox": "INBOX",          # 收件箱
                "since_days": 7,             # 拉取最近N天的邮件
                "max_emails": 50,            # 单次最大拉取数
            }
        )
    """

    @property
    def source_type(self) -> str:
        return "email"

    def fetch(self) -> ScrapedData:
        imap_host = self.config.extra.get("imap_host", "imap.qq.com")
        imap_port = int(self.config.extra.get("imap_port", 993))
        username = self.config.extra.get("username", "")
        password = self.config.extra.get("password", "")
        mailbox = self.config.extra.get("mailbox", "INBOX")
        since_days = int(self.config.extra.get("since_days", 7))
        max_emails = int(self.config.extra.get("max_emails", 50))

        if not username or not password:
            raise ValueError("IMAP username and password (授权码) are required")

        items = []
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        try:
            mail.login(username, password)
            mail.select(mailbox, readonly=True)

            # 搜索 since_days 天内的邮件
            from datetime import timedelta
            since_date = (datetime.now().astimezone().replace(tzinfo=None) - timedelta(days=since_days)).strftime("%d-%b-%Y")
            status, message_ids = mail.search(None, f"SINCE {since_date}")
            if status != "OK":
                logger.warning(f"IMAP search failed: {status}")
                return ScrapedData(
                    source_type=self.source_type,
                    source_id=self.config.name,
                    items=[],
                    fetched_at=time.time(),
                )

            ids = message_ids[0].split() if message_ids[0] else []
            # 只取最近的 max_emails 封
            ids = ids[-max_emails:]

            for mid in ids:
                try:
                    status, msg_data = mail.fetch(mid, "(RFC822)")
                    if status != "OK" or not msg_data or msg_data[0] is None:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subject = msg.get("Subject", "")
                    sender = msg.get("From", "")
                    received_date = msg.get("Date", "")
                    message_id_val = msg.get("Message-ID", "")

                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    try:
                                        body_text = payload.decode("utf-8", errors="replace")
                                    except Exception:
                                        body_text = payload.decode("iso-8859-1", errors="replace")
                                break
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            try:
                                body_text = payload.decode("utf-8", errors="replace")
                            except Exception:
                                body_text = payload.decode("iso-8859-1", errors="replace")

                    items.append({
                        "subject": subject,
                        "from": sender,
                        "date": received_date,
                        "message_id": message_id_val,
                        "body": body_text[:5000],  # 限制正文长度
                        "fetched_at": time.time(),
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse email {mid}: {e}")
                    continue

            mail.close()
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP connection/login failed: {e}")
            raise
        finally:
            try:
                mail.logout()
            except Exception:
                pass

        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )


# ─── 新增：Webhook 推模式基类 ─────────────────


class WebhookReceiver(BaseConnector):
    """
    推模式 Webhook 接收器基类。

    子类只需实现 _handle_payload(payload, headers) -> list[dict] 方法。
    receive() 方法被 ConnectorRegistry.handle_webhook() 调用。
    """

    @property
    def source_type(self) -> str:
        return "webhook"

    @abc.abstractmethod
    def _handle_payload(self, payload: dict, headers: Optional[dict]) -> list[dict]:
        """
        处理推送的 Webhook 数据载荷。

        Args:
            payload: 请求体 JSON 解析后的字典
            headers: HTTP 请求头

        Returns:
            数据条目列表（每项为一个 dict）
        """
        ...

    def receive(self, payload: dict, headers: Optional[dict] = None) -> ScrapedData:
        """
        接收并处理一次 Webhook 推送。

        由 ConnectorRegistry.handle_webhook() 调用，返回 ScrapedData。
        """
        items = self._handle_payload(payload, headers)
        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
            metadata={"webhook": True, "headers": headers} if headers else {"webhook": True},
        )

    def fetch(self) -> ScrapedData:
        """
        Webhook 接收器不支持主动拉取。

        Raises:
            NotImplementedError: WebhookReceiver 只能通过 receive() 推模式接收数据
        """
        raise NotImplementedError(
            "WebhookReceiver does not support active fetch. "
            "Use receive(payload) or ConnectorRegistry.handle_webhook()."
        )


# ─── 新增：ServerChan 推送工具类 ──────────────


class ServerChanPusher:
    """
    ServerChan 推送工具类 — 通过微信推送消息

    使用 ServerChan 的 SCKey 向微信发送消息通知。
    发消息接口: https://sctapi.ftqq.com/{SCKEY}.send

    用法:
        pusher = ServerChanPusher("your-sckey")
        pusher.push("标题", "内容")
    """

    def __init__(self, sckey: str):
        """
        Args:
            sckey: ServerChan SendKey（从 serverchan.com 获取）
        """
        self.sckey = sckey
        self._base_url = "https://sctapi.ftqq.com"

    @property
    def _push_url(self) -> str:
        return f"{self._base_url}/{self.sckey}.send"

    def push(self, title: str, content: str = "") -> dict:
        """
        发送一条微信推送消息。

        Args:
            title:   消息标题（必填，最长 128 字符）
            content: 消息内容（可选，支持 Markdown）

        Returns:
            响应 JSON（ServerChan 返回的消息推送结果）

        Raises:
            RuntimeError: 推送失败时抛出
        """
        data = {"title": title, "content": content}
        status, resp_headers, body = _urllib_request_json(
            self._push_url,
            method="POST",
            data=data,
            timeout=15.0,
        )
        if status != 200:
            raise RuntimeError(f"ServerChan push failed: HTTP {status} — {body}")

        if isinstance(body, dict) and body.get("code") != 0:
            logger.warning(f"ServerChan returned non-zero code: {body}")

        return body if isinstance(body, dict) else {"raw": body}

    def push_scraped(self, data: ScrapedData, max_items: int = 5) -> dict:
        """
        将 ScrapedData 摘要推送到微信。

        Args:
            data:      采集到的数据
            max_items: 最多显示的条目数

        Returns:
            ServerChan 推送响应
        """
        title = f"📥 {data.source_type} — {data.source_id}"
        lines = [f"采集到 {len(data.items)} 条新数据，时间: {datetime.fromtimestamp(data.fetched_at).isoformat()}"]
        for item in data.items[:max_items]:
            title_text = item.get("title") or item.get("subject") or item.get("url", "")
            lines.append(f"- {title_text}")
        if len(data.items) > max_items:
            lines.append(f"... 还有 {len(data.items) - max_items} 条未显示")
        content = "\n\n".join(lines)
        return self.push(title, content)

    def validate(self) -> bool:
        """验证 SCKey 是否有效（通过发送一条测试消息）"""
        try:
            resp = self.push("ServerChanPusher 验证", "此消息为连接验证测试，可忽略")
            return isinstance(resp, dict)
        except Exception:
            return False
