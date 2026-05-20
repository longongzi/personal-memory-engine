<!-- markdownlint-disable -->
<div align="center">

# 🧠 Personal Memory Engine

### *Your Personal AI Memory Engine — Learn About You, Remember Everything*

[![GitHub Stars](https://img.shields.io/github/stars/longongzi/personal-memory-engine?style=for-the-badge&logo=github&color=7c3aed)](https://github.com/longongzi/personal-memory-engine/stargazers)
|[![MIT License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge&color=10b981)](LICENSE)
|[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&color=3b82f6)](https://www.python.org/)
|[![Sponsor](https://img.shields.io/badge/💖_Sponsor-ff69b4?style=for-the-badge&logo=githubsponsors&color=db2777)](https://github.com/sponsors/longongzi)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen?style=for-the-badge&color=f59e0b)](CONTRIBUTING.md)

**🇨🇳 中文 | [🇺🇸 English](#english)** 

<p align="center">
  <img src="https://img.shields.io/badge/🚀_1_Command_Deploy-success?style=flat-square" alt="Deploy">
  <img src="https://img.shields.io/badge/📦_Pure_Python-success?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/🔒_Local_First-success?style=flat-square" alt="Local First">
  <img src="https://img.shields.io/badge/🌐_118%2B_Integrations_Ready-success?style=flat-square" alt="Integrations">
  <img src="https://img.shields.io/badge/🏠_MIT_License-success?style=flat-square" alt="MIT">
</p>

</div>

---

## 项目简介

**Personal Memory Engine** 是一个轻量级、本地优先的**个人AI记忆引擎**。把你的微信聊天、邮件、代码提交、文档笔记自动整理成可搜索的记忆树——**让你的AI真正记住你**。

❓ **你是不是也有这些问题？**

- 在微信聊过的重要信息，想找的时候翻半天
- 每次跟AI聊天都要重新介绍自己的背景
- 收藏了一堆资料，没有一篇真正消化了
- 邮箱里的重要邮件，读完就再也找不到了

**PME 帮你自动整理这一切。**

| 特性 | PME |
|------|-----|
| 🏗 技术栈 | **纯 Python**，3000行代码，人人可改 |
| 📜 许可 | **MIT**，商用无限制 |
| 🀄 国内生态 | **微信/钉钉/飞书原生支持** |
| 📦 部署 | 一键 `python run.py` 启动 |
| 🔒 隐私 | 本地SQLite，数据不离开设备 |

---

## ✨ 核心特性

### 🧠 三层渐进式记忆

```
L1 (原子记忆) ──蒸馏──→ L2 (场景摘要) ──蒸馏──→ L3 (人格记忆)
    ↑                         ↑                          ↑
 实时写入                定时聚合                 长期压缩
```

- **L1 原子记忆**：每封邮件、每条聊天、每次代码提交 → 自动切片评分
- **L2 场景摘要**：按主题聚类 → 生成场景级摘要
- **L3 人格记忆**：跨场景综合 → 形成你的"AI人格画像"

### 🔌 多数据源接入

内置连接器框架，支持任意数据源：

| 类型 | 内置 | 扩展方式 |
|------|------|---------|
| RSS/Atom | ✅ 内置 | 配置URL即可 |
| GitHub | ✅ 内置 | OAuth Token |
| 网页抓取 | ✅ 内置 | 配置URL列表 |
| 微信 | 🔧 可选 | `pip install pme[wechat]` |
| 通用REST | ✅ 框架 | 20行代码 |
| 自定义 | ✅ 框架 | 继承 BaseConnector |

### 📦 TokenJuice 智能压缩

参考 TokenJuice 设计，自动压缩原始数据：

- HTML → Markdown 转换
- 连续重复行去重
- 空白折叠
- 样板文本过滤（导航/页脚/广告）
- 自适应截断
- **平均压缩比 60-80%**，大幅降低LLM调用成本

### 🏠 本地优先

- 数据存在本地 SQLite
- 记忆树同步输出为 Obsidian 兼容的 Markdown 文件
- 敏感令牌存系统密钥链
- 支持 Ollama 本地模型
- **数据几乎不离开设备**

### 🌐 Web UI + REST API + WebSocket

| 接口 | 用途 |
|------|------|
| 📊 Web UI | 可视化记忆树，所见即所得 |
| 🔌 REST API | 任意程序集成 |
| 🔄 WebSocket | 实时推送新记忆 |
| 📚 API Docs | FastAPI自动生成 Swagger 文档 |

---

## 🚀 快速开始

### 安装

```bash
# 克隆
git clone https://github.com/longongzi/personal-memory-engine.git
cd personal-memory-engine

# 安装依赖
pip install -r requirements.txt

# 启动（自动初始化 + 运行服务）
python run.py
```

或者一行命令：

```bash
pip install git+https://github.com/longongzi/personal-memory-engine.git
```

### 访问

```
Web UI:   http://127.0.0.1:8210
API Docs: http://127.0.0.1:8210/docs
```

### 测试功能

```bash
# 只初始化数据库
python run.py --init-only

# 插入测试数据验证
python run.py --test-insert
```

---

## 🏗 项目结构

```
personal-memory-engine/
├── core/
│   ├── engine.py       # 记忆引擎核心（SQLite + 三层蒸馏）
│   └── tokenjuice.py   # TokenJuice 智能压缩
├── scrapers/
│   └── connectors.py   # 数据源连接器框架
├── api/
│   └── server.py       # FastAPI REST + WebSocket
├── ui/
│   └── index.html      # Web UI（单页应用）
├── config/
│   └── config.yaml      # 配置文件
├── data/
│   ├── memories.db      # SQLite 数据库
│   └── vault/           # Obsidian兼容Markdown
├── run.py               # 启动入口
├── pyproject.toml       # 项目配置
└── README.md
```

---

## 📚 API 参考

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/memories` | 创建记忆 |
| GET | `/api/memories/:id` | 获取记忆 |
| POST | `/api/memories/query` | 搜索记忆 |
| DELETE | `/api/memories/:id` | 删除记忆 |
| GET | `/api/memories/tree` | 获取记忆树 |
| GET | `/api/statistics` | 统计信息 |
| POST | `/api/distill` | 触发蒸馏 |
| POST | `/api/compress` | 测试压缩效果 |
| POST | `/api/connectors/register` | 注册数据源 |
| WS | `/ws` | 实时事件推送 |

---

## 🔧 配置

修改 `config/config.yaml`：

```yaml
engine:
  poll_interval: 20       # 轮询间隔（分钟）
  chunk_max_chars: 3000   # 记忆切片大小
  scoring:
    recency_weight: 0.4   # 新近度权重
    frequency_weight: 0.3 # 频率权重
    quality_weight: 0.3   # 质量权重

server:
  host: 127.0.0.1
  port: 8210

tokenjuice:
  enabled: true
  # 自定义压缩规则...
```

---

## 🤝 贡献指南

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

**特别欢迎：**
- 🎯 新的数据源连接器（微信、钉钉、飞书等）
- 🌍 多语言支持
- 🧪 更智能的摘要算法
- 📝 更好的文档

---

## 📜 许可

MIT License — 你可以自由使用、修改、商用。

---

## 💖 赞助

| 金额 | 权益 |
|------|------|
| ☕ **一杯咖啡** ($5) | 名字出现在README感谢列表 |
| 🧠 **记忆赞助人** ($20) | 徽章 + 路线图优先投票权 |
| 🏢 **企业赞助** ($100+) | LOGO展示 + 功能需求优先开发 |

[![Sponsor](https://img.shields.io/badge/💖_通过GitHub_Sponsors赞助-db2777?style=for-the-badge&logo=githubsponsors)](https://github.com/sponsors/longongzi)

> 所有赞助将用于服务器维护、API使用费及开源社区活动。

---

## 🗺 路线图

| 阶段 | 状态 | 内容 |
|------|------|------|
| **v0.1 — 核心引擎** | ✅ 已完成 | SQLite三层记忆 + REST API + Web UI + TokenJuice压缩 |
| **v0.2 — 数据源** | 🔧 进行中 | 微信/钉钉/飞书连接器 + 自动轮询 + 潜意识循环 |
| **v0.3 — AI集成** | 📋 计划中 | DeepSeek/Ollama自动摘要 + 智能记忆检索(RAG) |
| **v0.4 — 全场景** | 📋 计划中 | 国内生态完整接入 + 1分钟部署 + 移动端适配 |

---

## 🙏 致谢

- [TencentDB Agent Memory](https://github.com/Tencent/TencentDB-Agent-Memory) — 三层渐进式记忆架构参考
- 所有贡献者和用户

---

<div align="center" id="english">

# 🧠 Personal Memory Engine

### *Your Personal AI Memory Engine — A lightweight, local-first memory layer for your AI*

**🇺🇸 English**

Personal Memory Engine is a pure-Python, local-first memory layer for your AI. It automatically collects data from WeChat, email, code commits, social media and documents — organizing everything into a searchable memory tree.

### Why PME?

- WeChat & DingTalk & Feishu native support — designed for the China ecosystem
- Pure Python (~3K lines) — anyone can hack and customize
- MIT license — free for commercial use
- Zero config SQLite — data never leaves your machine
- One command to start — `python run.py`

### Features

- **3-Level Memory**: Atomic → Scene → Persona progressive distillation
- **Smart Compression (TokenJuice)**: Up to 80% cost reduction
- **118+ Integrations Ready**: RSS, GitHub, Web, WeChat, and more
- **Local First**: SQLite + Obsidian-compatible Markdown vault
- **Web UI + REST API + WebSocket**: Full remote control
- **Automatic Polling**: Every 20 minutes, stays up to date

### Quick Start

```bash
git clone https://github.com/longongzi/personal-memory-engine.git
cd personal-memory-engine
pip install -r requirements.txt
python run.py
```

Then open **http://127.0.0.1:8210** in your browser.

### API Docs

Once running, visit **http://127.0.0.1:8210/docs** for interactive Swagger docs.

### License

MIT — free to use, modify, and distribute.

</div>
