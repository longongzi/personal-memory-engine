"""
Personal Memory Engine — 核心记忆引擎
======================================
三层渐进式记忆系统：L1对话(原子) → L2场景(摘要) → L3人格(长期)
基于SQLite存储，输出Obsidian兼容的Markdown记忆树

参考: OpenHuman Memory Tree + TencentDB Agent Memory 思路
"""

from __future__ import annotations
import asyncio
import json
import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class MemoryLevel(Enum):
    """记忆层级"""
    ATOMIC = 1    # L1: 原子记忆 (单条对话/事件)
    SCENE = 2     # L2: 场景记忆 (主题聚类)
    PERSONA = 3   # L3: 人格记忆 (长期综合)


class MemoryType(Enum):
    """记忆来源类型"""
    CHAT = "chat"
    EMAIL = "email"
    CODE = "code"
    DOC = "doc"
    MEETING = "meeting"
    WEB = "web"
    SYSTEM = "system"


@dataclass
class MemoryChunk:
    """单条记忆片段"""
    id: str
    level: MemoryLevel
    source_type: MemoryType
    source_id: str  # 原始来源标识
    content: str    # Markdown格式内容
    summary: str    # 摘要
    score: float    # 重要性评分 0-1
    tags: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None  # 父级L2/L3节点
    created_at: float = 0.0  # Unix timestamp
    updated_at: float = 0.0
    access_count: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.value,
            "level_name": self.level.name,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "content": self.content,
            "summary": self.summary,
            "score": self.score,
            "tags": self.tags,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "metadata": self.metadata,
        }


class MemoryEngine:
    """
    记忆引擎核心 — 三层渐进式记忆系统
    
    架构：
        L1 (原子记忆) ──蒸馏──→ L2 (场景摘要) ──蒸馏──→ L3 (人格记忆)
        ↑                         ↑                          ↑
    实时写入               定时聚合                长期压缩
    """

    def __init__(self, db_path: str | Path, vault_dir: str | Path):
        self.db_path = Path(db_path)
        self.vault_dir = Path(vault_dir)
        self._init_db()

    def _init_db(self):
        """初始化SQLite数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                level INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT DEFAULT '',
                score REAL DEFAULT 0.5,
                tags TEXT DEFAULT '[]',
                parent_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_memories_level ON memories(level);
            CREATE INDEX IF NOT EXISTS idx_memories_score ON memories(score);
            CREATE INDEX IF NOT EXISTS idx_memories_parent ON memories(parent_id);
            CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
            
            CREATE TABLE IF NOT EXISTS memory_tags (
                memory_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (memory_id, tag),
                FOREIGN KEY (memory_id) REFERENCES memories(id)
            );
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON memory_tags(tag);
        """)
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    async def insert(self, chunk: MemoryChunk) -> str:
        """插入一条记忆，自动生成ID"""
        chunk.id = chunk.id or self._generate_id(chunk)
        chunk.created_at = chunk.created_at or time.time()
        chunk.updated_at = chunk.updated_at or time.time()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                INSERT OR REPLACE INTO memories
                (id, level, source_type, source_id, content, summary, score,
                 tags, parent_id, created_at, updated_at, access_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chunk.id, chunk.level.value, chunk.source_type.value,
                chunk.source_id, chunk.content, chunk.summary, chunk.score,
                json.dumps(chunk.tags), chunk.parent_id,
                chunk.created_at, chunk.updated_at, chunk.access_count,
                json.dumps(chunk.metadata),
            ))
            
            # 写标签
            for tag in chunk.tags:
                await db.execute(
                    "INSERT OR IGNORE INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                    (chunk.id, tag)
                )
            await db.commit()
        
        # 同步写入Obsidian vault
        self._write_vault_file(chunk)
        
        return chunk.id

    async def get(self, memory_id: str) -> Optional[MemoryChunk]:
        """获取单条记忆"""
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            
            # 增加访问次数
            await db.execute(
                "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                (memory_id,)
            )
            await db.commit()
            
            return self._row_to_chunk(row)

    async def query(
        self,
        level: Optional[MemoryLevel] = None,
        source_type: Optional[MemoryType] = None,
        tags: Optional[list[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_desc: bool = True,
    ) -> list[MemoryChunk]:
        """查询记忆，支持多维度过滤"""
        conditions = []
        params = []
        
        if level:
            conditions.append("m.level = ?")
            params.append(level.value)
        if source_type:
            conditions.append("m.source_type = ?")
            params.append(source_type.value)
        if keyword:
            conditions.append("(m.content LIKE ? OR m.summary LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        
        # 标签查询通过子查询
        tag_join = ""
        if tags:
            placeholders = ",".join("?" for _ in tags)
            tag_join = f"JOIN memory_tags mt2 ON m.id = mt2.memory_id AND mt2.tag IN ({placeholders})"
            params.extend(tags)
        
        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)
        
        order = "DESC" if sort_desc else "ASC"
        safe_sort = "m.created_at" if sort_by in ("created_at", "score", "access_count", "updated_at") else "m.created_at"
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            
            # 去重: 有tag_join时可能重复行
            distinct = "DISTINCT" if tag_join else ""
            cursor = await db.execute(f"""
                SELECT {distinct} m.* FROM memories m {tag_join}
                {where}
                ORDER BY {safe_sort} {order}
                LIMIT ? OFFSET ?
            """, params + [limit, offset])
            
            rows = await cursor.fetchall()
            return [self._row_to_chunk(r) for r in rows]

    async def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            cursor = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            await db.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def get_tree(self, level: MemoryLevel = MemoryLevel.PERSONA) -> list[dict]:
        """获取记忆树（层级结构）"""
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute("""
                SELECT id, level, summary, score, source_type, parent_id,
                       created_at, access_count
                FROM memories ORDER BY level, score DESC
            """)
            rows = await cursor.fetchall()
        
        # 构建树
        tree = {}
        for r in rows:
            node = {
                "id": r["id"],
                "level": r["level"],
                "summary": r["summary"],
                "score": r["score"],
                "source_type": r["source_type"],
                "parent_id": r["parent_id"],
                "created_at": r["created_at"],
                "access_count": r["access_count"],
                "children": []
            }
            tree[r["id"]] = node
        
        # 挂载子节点
        roots = []
        for node in tree.values():
            if node["parent_id"] and node["parent_id"] in tree:
                tree[node["parent_id"]]["children"].append(node)
            else:
                roots.append(node)
        
        # 只返回 <=level 的根节点
        return [n for n in roots if n["level"] <= level.value]

    async def distill(self) -> dict:
        """
        蒸馏：L1→L2→L3 渐进式压缩
        返回蒸馏统计
        """
        stats = {"l1_to_l2": 0, "l2_to_l3": 0}
        
        l1_memories = await self.query(
            level=MemoryLevel.ATOMIC, limit=10000, sort_by="score", sort_desc=False
        )
        
        # L1→L2: 按主题聚类（按tags或source_type分组）
        clusters = {}
        for mem in l1_memories:
            key = ",".join(sorted(mem.tags)) if mem.tags else mem.source_type.value
            if key not in clusters:
                clusters[key] = []
            clusters[key].append(mem)
        
        for key, items in clusters.items():
            if len(items) < 2:
                continue
            # 生成L2摘要
            l2_content = self._merge_content(items)
            l2_summary = f"主题: {key} | 共{len(items)}条记录 | 时间跨度: {self._time_span(items)}"
            l2_score = sum(m.score for m in items) / len(items) * 1.2  # 聚合加分
            l2_score = min(l2_score, 1.0)
            
            l2_chunk = MemoryChunk(
                id=self._generate_id_from_content(f"l2_{key}"),
                level=MemoryLevel.SCENE,
                source_type=items[0].source_type,
                source_id=f"distilled:{key}",
                content=l2_content,
                summary=l2_summary,
                score=l2_score,
                tags=list(set(t for m in items for t in m.tags)),
                created_at=min(m.created_at for m in items),
                updated_at=max(m.updated_at for m in items),
            )
            await self.insert(l2_chunk)
            
            # 更新L1的parent指向L2
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                for mem in items:
                    await db.execute(
                        "UPDATE memories SET parent_id = ?, level = ? WHERE id = ?",
                        (l2_chunk.id, MemoryLevel.ATOMIC.value, mem.id)
                    )
                await db.commit()
            
            stats["l1_to_l2"] += len(items)
        
        # L2→L3: 聚合所有L2生成人格记忆
        l2_memories = await self.query(
            level=MemoryLevel.SCENE, limit=1000, sort_by="score", sort_desc=False
        )
        
        if len(l2_memories) >= 2:
            l3_content = self._merge_content(l2_memories)
            l3_tags = list(set(t for m in l2_memories for t in m.tags))
            l3_summary = f"人格摘要 | 覆盖{len(l2_memories)}个场景 | 标签: {', '.join(l3_tags[:10])}"
            l3_score = sum(m.score for m in l2_memories) / len(l2_memories) * 1.5
            l3_score = min(l3_score, 1.0)
            
            l3_chunk = MemoryChunk(
                id="persona_master",
                level=MemoryLevel.PERSONA,
                source_type=MemoryType.SYSTEM,
                source_id="distilled:persona",
                content=l3_content,
                summary=l3_summary,
                score=l3_score,
                tags=l3_tags,
                created_at=time.time(),
                updated_at=time.time(),
            )
            await self.insert(l3_chunk)
            
            # 更新所有L2的parent
            async with aiosqlite.connect(str(self.db_path)) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                for mem in l2_memories:
                    await db.execute(
                        "UPDATE memories SET parent_id = ? WHERE id = ?",
                        (l3_chunk.id, mem.id)
                    )
                await db.commit()
            
            stats["l2_to_l3"] = len(l2_memories)
        
        # TODO: 集成LLM做语义级摘要 (使用OpenAI/DeepSeek)
        
        return stats

    async def get_statistics(self) -> dict:
        """获取记忆统计"""
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute("""
                SELECT level, COUNT(*) as count, AVG(score) as avg_score,
                       SUM(access_count) as total_access
                FROM memories GROUP BY level
            """)
            rows = await cursor.fetchall()
            
            cursor2 = await db.execute("SELECT COUNT(DISTINCT tag) as tag_count FROM memory_tags")
            tag_row = await cursor2.fetchone()
            
            cursor3 = await db.execute("""
                SELECT source_type, COUNT(*) as count FROM memories GROUP BY source_type
            """)
            sources = await cursor3.fetchall()
        
        levels = {1: "L1-ATOMIC", 2: "L2-SCENE", 3: "L3-PERSONA"}
        return {
            "total_memories": sum(r["count"] for r in rows),
            "by_level": {
                levels[r["level"]]: {
                    "count": r["count"],
                    "avg_score": round(r["avg_score"], 3),
                    "total_access": r["total_access"],
                }
                for r in rows
            },
            "by_source": {r["source_type"]: r["count"] for r in sources},
            "total_tags": tag_row["tag_count"] if tag_row else 0,
            "vault_path": str(self.vault_dir),
        }

    # ─── 内部方法 ────────────────────────────

    def _generate_id(self, chunk: MemoryChunk) -> str:
        raw = f"{chunk.source_type.value}:{chunk.source_id}:{time.time_ns()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _generate_id_from_content(self, content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _row_to_chunk(self, row) -> MemoryChunk:
        return MemoryChunk(
            id=row["id"],
            level=MemoryLevel(row["level"]),
            source_type=MemoryType(row["source_type"]),
            source_id=row["source_id"],
            content=row["content"],
            summary=row["summary"],
            score=row["score"],
            tags=json.loads(row["tags"]),
            parent_id=row["parent_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=row["access_count"],
            metadata=json.loads(row["metadata"]),
        )

    def _merge_content(self, items: list[MemoryChunk]) -> str:
        """合并多条记忆内容为Markdown"""
        lines = []
        for item in sorted(items, key=lambda x: x.created_at):
            dt = datetime.fromtimestamp(item.created_at, tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            lines.append(f"## [{date_str}] {item.summary}")
            lines.append("")
            lines.append(item.content)
            lines.append("---")
            lines.append("")
        return "\n".join(lines)

    def _time_span(self, items: list[MemoryChunk]) -> str:
        """计算时间跨度"""
        times = [m.created_at for m in items if m.created_at]
        if not times:
            return "未知"
        start = datetime.fromtimestamp(min(times), tz=timezone.utc)
        end = datetime.fromtimestamp(max(times), tz=timezone.utc)
        delta = end - start
        days = delta.days
        if days > 30:
            return f"{days//30}个月"
        if days > 0:
            return f"{days}天"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}小时"
        return f"{delta.seconds//60}分钟"

    def _write_vault_file(self, chunk: MemoryChunk):
        """写入Obsidian兼容的Markdown文件"""
        if not chunk.level or chunk.level.value < 1:
            return
        
        # 按层级分目录
        level_dirs = {1: "atomic", 2: "scenes", 3: "persona"}
        subdir = level_dirs.get(chunk.level.value, "other")
        
        vault_path = self.vault_dir / subdir
        vault_path.mkdir(parents=True, exist_ok=True)
        
        # 文件名: 时间_摘要前40字.md
        dt = datetime.fromtimestamp(chunk.created_at, tz=timezone.utc)
        safe_summary = "".join(c for c in chunk.summary[:40] if c.isalnum() or c in " _-")
        filename = f"{dt.strftime('%Y%m%d_%H%M')}_{safe_summary}.md"
        filepath = vault_path / filename
        
        # 元数据frontmatter
        frontmatter = {
            "id": chunk.id,
            "level": chunk.level.name,
            "source": chunk.source_type.value,
            "score": round(chunk.score, 3),
            "tags": chunk.tags,
            "parent": chunk.parent_id or "",
            "created": dt.isoformat(),
            "accessed": chunk.access_count,
        }
        
        content = f"""---
{json.dumps(frontmatter, ensure_ascii=False, indent=2)}
---

{chunk.content}
"""
        try:
            filepath.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write vault file {filepath}: {e}")
