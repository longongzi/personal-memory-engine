#!/usr/bin/env python3
"""Personal Memory Engine — Demo录制脚本
录制核心功能使用流程的截图，用于合成GIF演示。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

BASE = "http://127.0.0.1:8210"
OUTPUT_DIR = "demo_screenshots"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def req(method, path, data=None):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:200]}

def step(n, label, response):
    """记录每个步骤的结果"""
    status = "✅" if "error" not in response else "❌"
    print(f"  {status} Step {n}: {label}")

print("=" * 60)
print("🧠 Personal Memory Engine — Demo Recording")
print("=" * 60)

print("\n📡 [1] Health Check")
r = req("GET", "/api/health")
step(1, f"Server status: {r.get('status')}", r)

print("\n📝 [2] Create Memories — 插入多条示例记忆")
samples = [
    {"content": "# Python异步编程笔记\nasyncio是Python并发编程的核心库。\n- async/await语法\n- 事件循环机制\n- 协程调度", "source_type": "doc", "tags": ["python", "async", "programming"]},
    {"content": "# 今日邮件：项目评审\n项目Alpha的架构评审定在周五下午3点。需要准备：\n1. 技术方案PPT\n2. 性能测试报告\n3. API文档更新", "source_type": "email", "tags": ["work", "project", "meeting"]},
    {"content": "# 代码提交：fix(api): 修复用户认证流程\n- 修复JWT token过期处理\n- 增加refresh_token轮换\n- 优化数据库查询性能", "source_type": "code", "tags": ["github", "bugfix", "auth"]},
    {"content": "# 技术会议：AI Agent架构讨论\n讨论了如何构建模块化AI Agent系统：\n- 工具调用框架设计\n- 记忆系统分层\n- 多Agent协作模式", "source_type": "meeting", "tags": ["ai", "architecture", "agent"]},
    {"content": "# 微信对话：周末计划\n用户计划周末学习Rust语言基础。\n- 安装Rust工具链\n- 完成《Rust程序设计》前5章\n- 写一个CLI工具练手", "source_type": "chat", "tags": ["rust", "study", "weekend"]},
]
for i, s in enumerate(samples):
    r = req("POST", "/api/memories", s)
    step(2, f"Inserted: {s['content'][:30]}...", r)
    time.sleep(0.3)

print("\n📊 [3] Statistics Overview")
r = req("GET", "/api/statistics")
step(3, f"Total memories: {r.get('total_memories')}", r)

print("\n🌳 [4] Memory Tree View")
r = req("GET", "/api/memories/tree")
step(4, f"Tree depth: {len(r)} nodes in response", r)

print("\n🔍 [5] Search — Filter by tag")
r = req("POST", "/api/memories/query", {"tags": ["python"]})
count = r.get("count", 0) if isinstance(r, dict) else 0
results = r.get("results", []) if isinstance(r, dict) else (r if isinstance(r, list) else [])
step(5, f"Found {count} memories tagged 'python'", r)

print("\n🔍 [6] Search — Filter by source")
r = req("POST", "/api/memories/query", {"source_type": "email"})
count = r.get("count", 0) if isinstance(r, dict) else 0
step(6, f"Found {count} email-sourced memories", r)

print("\n🔬 [7] TokenJuice Compression Test")
html_sample = "<html><body><h1>Hello World</h1><p>This is a <b>test</b> paragraph with lots of HTML noise.</p><nav><a href='#'>Link1</a><a href='#'>Link2</a></nav><footer>Copyright 2026</footer></body></html>"
r = req("POST", "/api/compress", {"text": html_sample, "is_html": True})
ratio = r.get("ratio", 0)
step(7, f"Compression: {html_sample} → {r.get('compressed_chars')} chars (ratio: {ratio:.1%})", r)

print("\n🧪 [8] Distillation — L1→L2→L3")
r = req("POST", "/api/distill")
step(8, f"Distilled: L1→L2={r.get('l1_to_l2', 0)}, L2→L3={r.get('l2_to_l3', 0)}", r)

print("\n📊 [9] Statistics After Distillation")
r = req("GET", "/api/statistics")
bl = r.get("by_level", {})
l1 = bl.get("L1-ATOMIC", {}).get("count", 0)
l2 = bl.get("L2-SCENE", {}).get("count", 0)
l3 = bl.get("L3-PERSONA", {}).get("count", 0)
step(9, f"After distill — L1:{l1}, L2:{l2}, L3:{l3}", r)

print("\n🌳 [10] Memory Tree After Distillation")
r = req("GET", "/api/memories/tree")
step(10, f"Tree with {len(r)} nodes", r)

print("\n📋 [11] Get Single Memory")
r = req("GET", "/api/memories/query")
if isinstance(r, list) and r:
    first_id = r[0]["id"]
    r2 = req("GET", f"/api/memories/{first_id}")
    step(11, f"Retrieved: {r2.get('summary', '')[:50]}", r2)

print("\n" + "=" * 60)
print("✅ Demo Recording Complete")
print("=" * 60)
