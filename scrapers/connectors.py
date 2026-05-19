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
"""

from __future__ import annotations
import abc
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


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


class BaseConnector(abc.ABC):
    """数据源连接器基类"""

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._http_client: Optional[httpx.AsyncClient] = None
        self._last_fetch: float = 0

    @property
    @abc.abstractmethod
    def source_type(self) -> str:
        """数据源类型标识"""
        ...

    @abc.abstractmethod
    async def fetch(self) -> ScrapedData:
        """执行一次数据采集"""
        ...

    async def validate(self) -> bool:
        """验证连接配置是否有效"""
        return True

    async def start(self):
        """启动连接器（初始化HTTP客户端等）"""
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "PersonalMemoryEngine/0.1.0"},
            )

    async def stop(self):
        """停止连接器"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


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
        """采集所有已注册且启用的数据源"""
        results = []
        for connector in self._connectors.values():
            if not connector.config.enabled:
                continue
            try:
                await connector.start()
                data = await connector.fetch()
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
                await connector.start()

    async def stop_all(self):
        """停止所有连接器"""
        self._running = False
        for connector in self._connectors.values():
            await connector.stop()


# ─── 内置连接器示例 ─────────────────────────

class RSSConnector(BaseConnector):
    """RSS/Atom feed连接器"""

    @property
    def source_type(self) -> str:
        return "rss"

    async def fetch(self) -> ScrapedData:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        
        resp = await self._http_client.get(self.config.base_url)
        resp.raise_for_status()
        
        # 简易RSS解析（完整版可用feedparser）
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        
        items = []
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = entry.find("{http://www.w3.org/2005/Atom}title")
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            summary = entry.find("{http://www.w3.org/2005/Atom}summary")
            published = entry.find("{http://www.w3.org/2005/Atom}published")
            
            items.append({
                "title": title.text if title is not None else "",
                "url": link.get("href") if link is not None else "",
                "summary": summary.text if summary is not None else "",
                "published": published.text if published is not None else "",
                "fetched_at": time.time(),
            })
        
        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )


class GitHubConnector(BaseConnector):
    """GitHub OAuth连接器 — 拉取issues/PRs/commits"""

    @property
    def source_type(self) -> str:
        return "github"

    async def fetch(self) -> ScrapedData:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"token {self.config.access_token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "PersonalMemoryEngine/0.1.0",
                },
            )
        
        items = []
        urls = [
            "https://api.github.com/notifications",
            "https://api.github.com/user/repos?sort=updated&per_page=10",
        ]
        
        for url in urls:
            try:
                resp = await self._http_client.get(url)
                resp.raise_for_status()
                items.extend(resp.json())
            except Exception as e:
                logger.warning(f"github fetch {url} failed: {e}")
        
        return ScrapedData(
            source_type=self.source_type,
            source_id=self.config.name,
            items=items,
            fetched_at=time.time(),
        )

    async def validate(self) -> bool:
        """验证token有效性"""
        try:
            resp = await self._http_client.get("https://api.github.com/user")
            return resp.status_code == 200
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

    async def fetch(self) -> ScrapedData:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        
        items = []
        for url in self.urls:
            try:
                resp = await self._http_client.get(url)
                resp.raise_for_status()
                items.append({
                    "url": url,
                    "content": resp.text[:10000],  # 限制大小
                    "status_code": resp.status_code,
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
