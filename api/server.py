"""
Personal Memory Engine — FastAPI REST + WebSocket 服务
======================================================
双向通信：
- REST API：记忆CRUD、数据源管理、配置
- WebSocket：实时记忆推送、采集进度通知
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from core.engine import MemoryEngine, MemoryChunk, MemoryLevel, MemoryType
from core.tokenjuice import TokenJuice
from scrapers.connectors import ConnectorRegistry, ConnectorConfig

logger = logging.getLogger(__name__)


# ─── Pydantic Models ────────────────────────

class CreateMemoryRequest(BaseModel):
    content: str
    source_type: str = "chat"
    source_id: str = "manual"
    summary: str = ""
    tags: list[str] = []
    score: float = 0.5


class QueryRequest(BaseModel):
    level: Optional[str] = None
    source_type: Optional[str] = None
    tags: Optional[list[str]] = None
    keyword: Optional[str] = None
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"
    sort_desc: bool = True


class ConnectorRegisterRequest(BaseModel):
    name: str
    type_: str = Field(alias="type")
    base_url: Optional[str] = None
    access_token: Optional[str] = None
    poll_interval: int = 1200
    extra: dict = {}


# ─── App State ──────────────────────────────

class AppState:
    engine: MemoryEngine
    tokenjuice: TokenJuice
    registry: ConnectorRegistry
    config: dict
    websockets: set[WebSocket] = set()
    poll_task: Optional[asyncio.Task] = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    state.config = cfg
    
    engine_cfg = cfg.get("engine", {})
    storage_cfg = cfg.get("storage", {})
    project_root = Path(__file__).parent.parent
    
    db_path = project_root / storage_cfg.get("database", "data/memories.db")
    vault_dir = project_root / storage_cfg.get("vault_dir", "data/vault")
    
    state.engine = MemoryEngine(db_path, vault_dir)
    state.tokenjuice = TokenJuice()
    state.registry = ConnectorRegistry()
    
    # 启动自动轮询任务
    poll_interval = engine_cfg.get("poll_interval", 20) * 60
    state.poll_task = asyncio.create_task(_poll_loop(poll_interval))
    
    logger.info("Personal Memory Engine started")
    yield
    
    # 关闭
    state.poll_task.cancel()
    await state.registry.stop_all()
    logger.info("Personal Memory Engine stopped")


app = FastAPI(
    title="Personal Memory Engine",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── WebSocket 连接管理 ──────────────────────

async def broadcast(message: dict):
    """广播消息到所有WebSocket客户端"""
    dead = set()
    for ws in state.websockets:
        try:
            await ws.send_json(message)
        except Exception:
            dead.add(ws)
    state.websockets -= dead


async def _poll_loop(interval_seconds: int):
    """自动轮询数据源"""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            logger.info("Polling all data sources...")
            await broadcast({"type": "poll_start"})
            
            scraped_data = await state.registry.fetch_all()
            
            for data in scraped_data:
                # TokenJuice压缩
                for item in data.items:
                    content_str = json.dumps(item, ensure_ascii=False)
                    compressed = state.tokenjuice.compress(content_str)
                    
                    chunk = MemoryChunk(
                        id="",
                        level=MemoryLevel.ATOMIC,
                        source_type=MemoryType(data.source_type),
                        source_id=data.source_id,
                        content=compressed.output[:2000],
                        summary=compressed.summary,
                        score=0.5,
                        metadata={"original_size": compressed.original_chars},
                    )
                    await state.engine.insert(chunk)
                
                await broadcast({
                    "type": "poll_result",
                    "source": data.source_type,
                    "count": len(data.items),
                })
            
            # 定期蒸馏
            if len(scraped_data) > 0:
                stats = await state.engine.distill()
                await broadcast({"type": "distill_result", "stats": stats})
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}")
            await broadcast({"type": "poll_error", "error": str(e)})


# ─── REST API ────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "time": time.time()}


async def _get_engine(request=None):
    """获取引擎实例——兼容不同调用方式"""
    if request is not None:
        return request.app.state.engine
    return state.engine




@app.post("/api/memories")
async def create_memory(req: CreateMemoryRequest):
    """创建一条记忆"""
    chunk = MemoryChunk(
        id="",
        level=MemoryLevel.ATOMIC,
        source_type=MemoryType(req.source_type),
        source_id=req.source_id,
        content=req.content,
        summary=req.summary or req.content[:100],
        score=req.score,
        tags=req.tags,
    )
    mid = await state.engine.insert(chunk)
    
    await broadcast({"type": "memory_created", "id": mid, "summary": chunk.summary})
    return {"id": mid}


@app.get("/api/memories/tree")
async def get_memory_tree(level: int = 3):
    """获取记忆树"""
    lvl = MemoryLevel(level) if 1 <= level <= 3 else MemoryLevel.PERSONA
    tree = await state.engine.get_tree(lvl)
    return {"tree": tree}


@app.get("/api/memories/{memory_id}")
async def get_memory(memory_id: str):
    """获取单条记忆"""
    chunk = await state.engine.get(memory_id)
    if not chunk:
        raise HTTPException(404, "Memory not found")
    return chunk.to_dict()


@app.post("/api/memories/query")
async def query_memories(req: QueryRequest):
    """查询记忆"""
    level = MemoryLevel[req.level] if req.level else None
    source_type = MemoryType[req.source_type] if req.source_type else None
    
    results = await state.engine.query(
        level=level,
        source_type=source_type,
        tags=req.tags,
        keyword=req.keyword,
        limit=req.limit,
        offset=req.offset,
        sort_by=req.sort_by,
        sort_desc=req.sort_desc,
    )
    return {"results": [r.to_dict() for r in results], "count": len(results)}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    """删除记忆"""
    ok = await state.engine.delete(memory_id)
    if not ok:
        raise HTTPException(404, "Memory not found")
    await broadcast({"type": "memory_deleted", "id": memory_id})
    return {"ok": True}


@app.get("/api/statistics")
async def get_statistics():
    """获取记忆统计"""
    return await state.engine.get_statistics()


@app.post("/api/distill")
async def trigger_distill():
    """手动触发蒸馏"""
    stats = await state.engine.distill()
    await broadcast({"type": "distill_result", "stats": stats})
    return stats


@app.post("/api/compress")
async def compress_text(text: str, is_html: bool = False):
    """测试TokenJuice压缩效果"""
    result = state.tokenjuice.compress(text, is_html=is_html)
    return {
        "original_chars": result.original_chars,
        "compressed_chars": result.compressed_chars,
        "ratio": round(result.ratio, 4),
        "estimated_tokens_saved": result.estimated_tokens_saved,
        "strategies_applied": result.strategies_applied,
        "output": result.output[:2000],  # 只返回预览
        "summary": result.summary,
    }


@app.post("/api/connectors/register")
async def register_connector(req: ConnectorRegisterRequest):
    """注册数据源连接器"""
    from scrapers.connectors import RSSConnector, GitHubConnector, WebScraperConnector
    
    config = ConnectorConfig(
        name=req.name,
        type=req.type_,
        base_url=req.base_url,
        access_token=req.access_token,
        poll_interval=req.poll_interval,
        extra=req.extra,
    )
    
    connector_map = {
        "rss": RSSConnector,
        "github": GitHubConnector,
        "web": lambda c: WebScraperConnector(c, c.extra.get("urls", [])),
    }
    
    connector_cls = connector_map.get(req.type_)
    if not connector_cls:
        raise HTTPException(400, f"Unknown connector type: {req.type_}")
    
    connector = (lambda c: connector_cls(c) if callable(connector_cls) else connector_cls(config))(
        config
    ) if not callable(connector_cls) else connector_cls(config)
    
    state.registry.register(connector)
    return {"name": req.name, "type": req.type_, "status": "registered"}


@app.get("/api/connectors")
async def list_connectors():
    """列出已注册的数据源"""
    return {
        "connectors": [
            {"name": c.config.name, "type": c.config.type, "source_type": c.source_type}
            for c in state.registry.all
        ]
    }


@app.post("/api/connectors/fetch")
async def trigger_fetch():
    """手动触发一次全量采集"""
    results = await state.registry.fetch_all()
    return {
        "sources": [{"type": r.source_type, "count": len(r.items)} for r in results],
        "total_items": sum(len(r.items) for r in results),
    }


# ─── WebSocket ──────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket实时事件推送"""
    await websocket.accept()
    state.websockets.add(websocket)
    
    try:
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            match msg.get("action"):
                case "ping":
                    await websocket.send_json({"type": "pong"})
                case "query":
                    # 在WebSocket中直接查询
                    results = await state.engine.query(**msg.get("params", {}))
                    await websocket.send_json({
                        "type": "query_result",
                        "id": msg.get("id"),
                        "results": [r.to_dict() for r in results],
                    })
                case _:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown action: {msg.get('action')}",
                    })
    except WebSocketDisconnect:
        state.websockets.discard(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        state.websockets.discard(websocket)


# ─── Web UI ─────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """简单Web管理界面"""
    ui_path = Path(__file__).parent.parent / "ui" / "index.html"
    if ui_path.exists():
        return ui_path.read_text(encoding="utf-8")
    return HTMLResponse("<h1>Personal Memory Engine</h1><p>Web UI not found. Run setup first.</p>")


# ─── 启动入口 ────────────────────────────────

def run():
    """使用 uvicorn 启动服务器"""
    import uvicorn
    cfg = state.config.get("server", {})
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8210)
    
    print(f"╔══════════════════════════════════════════╗")
    print(f"║   Personal Memory Engine v0.1.0          ║")
    print(f"║   Running on http://{host}:{port}        ║")
    print(f"║   API Docs: http://{host}:{port}/docs    ║")
    print(f"║   Web UI:   http://{host}:{port}/        ║")
    print(f"╚══════════════════════════════════════════╝")
    
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
