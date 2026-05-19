#!/usr/bin/env python3
"""
Personal Memory Engine — CLI启动入口
====================================
用法:
    python run.py                  # 启动服务
    python run.py --init-only     # 只初始化数据库(通过API)
    python run.py --test-insert   # 启动服务+插入测试数据
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")


def _get_api_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _wait_for_server(port: int, timeout: int = 15) -> bool:
    """等待服务器就绪"""
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2)
            data = json.loads(resp.read().decode())
            if data.get("status") == "ok":
                return True
        except (urllib.error.URLError, ConnectionError, json.JSONDecodeError):
            time.sleep(1)
    return False


def init_db(port: int = 8210):
    """通过API初始化数据库（启动服务后调用）"""
    base = _get_api_url(port)
    print(f"🔧 Checking server at {base}...")
    if not _wait_for_server(port):
        print("❌ Server not responding. Start server first: python run.py")
        return
    print(f"✅ Server is ready. Database path: data/memories.db")


def test_insert(port: int = 8210):
    """通过API插入测试数据"""
    import urllib.request
    base = _get_api_url(port)
    
    if not _wait_for_server(port):
        print("❌ Server not responding. Start server first: python run.py")
        return
    
    test_data = [
        ("GitHub PR review: fix memory leak in tokenjuice", "code", "pr#42", ["code", "rust"], 0.8),
        ("Meeting note: Q2 architecture review", "meeting", "mtg#5", ["design", "team"], 0.7),
        ("Email: project proposal from Alice", "email", "email#1024", ["project", "proposal"], 0.6),
        ("WeChat chat: weekend plans discussion", "chat", "chat#888", ["social", "weekend"], 0.3),
        ("Read article: LLM memory optimization techniques", "web", "art#12", ["research", "llm"], 0.9),
    ]
    
    print("📝 Inserting test data via API...")
    ids = []
    for content, stype, sid, tags, score in test_data:
        payload = json.dumps({
            "content": content,
            "source_type": stype,
            "source_id": sid,
            "tags": tags,
            "score": score,
        }).encode()
        req = urllib.request.Request(
            f"{base}/api/memories",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read().decode())
        ids.append(result["id"])
        print(f"  ✓ Inserted [{score}]: {content[:50]}... → {result['id']}")
    
    # 触发蒸馏
    print("\n🔄 Running distillation via API...")
    req = urllib.request.Request(f"{base}/api/distill", method="POST")
    resp = urllib.request.urlopen(req)
    stats = json.loads(resp.read().decode())
    print(f"  ✓ L1→L2: {stats.get('l1_to_l2', 0)} memories")
    print(f"  ✓ L2→L3: {stats.get('l2_to_l3', 0)} scenes")
    
    # 获取统计
    resp = urllib.request.urlopen(f"{base}/api/statistics")
    final_stats = json.loads(resp.read().decode())
    print(f"\n📊 Final statistics:")
    print(json.dumps(final_stats, ensure_ascii=False, indent=2))
    print(f"\n✅ Test complete! {len(ids)} memories inserted via API.")


def run_server(port: int = 8210):
    """启动服务器"""
    import uvicorn
    # 更新配置端口
    import yaml
    config_path = project_root / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["server"]["port"] = port
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    
    print(f"╔══════════════════════════════════════════╗")
    print(f"║   Personal Memory Engine v0.1.0          ║")
    print(f"║   Running on http://127.0.0.1:{port}        ║")
    print(f"║   API Docs: http://127.0.0.1:{port}/docs    ║")
    print(f"║   Web UI:   http://127.0.0.1:{port}/        ║")
    print(f"╚══════════════════════════════════════════╝")
    
    uvicorn.run("api.server:app", host="127.0.0.1", port=port, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="Personal Memory Engine")
    parser.add_argument("--init-only", action="store_true", help="只初始化数据库（通过API）")
    parser.add_argument("--test-insert", action="store_true", help="通过API插入测试数据（需先启动服务）")
    parser.add_argument("--port", type=int, default=8210, help="服务端口")
    
    args = parser.parse_args()
    
    if args.init_only:
        init_db(args.port)
    elif args.test_insert:
        test_insert(args.port)
    else:
        # 默认：启动服务
        run_server(args.port)


if __name__ == "__main__":
    main()
