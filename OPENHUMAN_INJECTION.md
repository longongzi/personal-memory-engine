# Personal Memory Engine — OpenHuman Design Injection

> OpenHuman的设计理念，注入到PME的架构中。
> 继承其精髓，差异化国内生态，制造差异化竞争力。

---

## 一、核心哲学继承

### 1. 「真正懂你」——个人上下文优先

**继承自OpenHuman：**
- 用户无需每次重新介绍自己 → 记忆引擎自动累积
- 连接账户后20分钟即可建立个人上下文
- 首日即可高效使用

**PME实现差异：**
- PME使用三层渐进式记忆（L1→L2→L3），比OpenHuman的单层记忆树更节省Token
- 我们使用纯Python/SQLite，比Rust/Tauri轻量10倍
- **关键差异**：我们开源了完整的蒸馏算法，别人可以自定义

### 2. 数据源连接与轮询

**继承自OpenHuman：**
- 118+种服务的OAuth自动连接
- 20分钟自动轮询，无需手动操作

**PME实现差异：**
- PME的连接器框架目前支持4种内置（RSS/GitHub/Web/通用REST）
- **关键差异**：我们原生支持微信/钉钉/飞书，OpenHuman不支持
- 我们使用`PollingCoordinator`统一管理轮询频率

### 3. TokenJuice压缩

**继承自OpenHuman：**
- HTML→Markdown去重，降低80%成本
- 三层JSON配置压缩规则

**PME实现差异：**
- PME已经有了完整的`tokenjuice.py`实现（10KB代码）
- 我们一样支持HTML→Markdown + 去重 + 模板文本过滤
- **关键差异**：我们支持增量压缩（避免重复压缩已处理的数据）

### 4. 记忆树

**继承自OpenHuman：**
- 层级摘要按主题和时间线组织
- Obsidian兼容的Markdown输出

**PME实现差异：**
- PME使用SQLite存储 + 按需生成Markdown
- **关键差异**：我们支持Web UI可视化 + REST API查询

### 5. 本地优先

**继承自OpenHuman：**
- SQLite本地存储
- 敏感令牌存于密钥链
- 支持Ollama本地模型

**PME实现差异：**
- PME完全符合这个要求
- **关键差异**：我们是MIT许可，OpenHuman是GPL-3.0

## 二、PME需要补齐的能力（vs OpenHuman差距对比）

| 功能 | OpenHuman | PME目前 | 优先级 |
|------|-----------|---------|--------|
| 🖥️ 桌面客户端（Mascot形象+三栏布局） | ✅ 完善 | ❌ 只有Web UI | **P0** |
| 🔄 潜意识循环（后台自主决策） | ✅ | ❌ 无 | **P1** |
| 🎤 Google Meet自动参会 | ✅ | ❌ 无 | P2 |
| 🐚 Shell集成（终端实时助手） | ✅ | ❌ 无 | P2 |
| 🔐 密钥链存储令牌 | ✅ | ❌ 仅配置yaml | **P0** |
| 📝 Vault自动导出 | ✅ | ✅ 部分支持 | 已有 |
| 🤖 Ollama集成 | ✅ | ❌ 配置但无实际调用 | **P1** |
| 🀄 微信/钉钉/飞书 | ❌ | ✅ 连接器框架 | 已领先 |
| ⚖️ 许可协议 | GPL-3.0 | ✅ MIT | 已领先 |
| 📦 代码体积 | 10万+Rust | ✅ ~3000行Python | 已领先 |

## 三、PME v0.2 升级方案

### Phase A：桌面客户端（P0 — 最高优先级）

**设计：** 仿OpenHuman三栏布局，但用Web技术栈（Electron / Tauri可选）

```
┌─────────────┬──────────────────────────┬─────────────┐
│  左栏       │       中栏               │   右栏      │
│  记忆树     │   Mascot虚拟形象         │   对话面板  │
│  ├ L1原子   │   (工作状态表情)         │   +工具面板  │
│  ├ L2场景   │                         │             │
│  ├ L3人格   │  快捷指令卡片            │  当前上下文  │
│             │                         │             │
│  实时更新    │  记忆流时间线            │  AI响应     │
└─────────────┴──────────────────────────┴─────────────┘
```

**实现方案：** 使用FastAPI + WebSocket + HTML/CSS/JS三栏布局
- Mascot用CSS动画表情，根据当前状态变化
- 左侧从`/api/memories/tree`渲染
- 右侧对话面板对接DeepSeek API

### Phase B：潜意识循环（P1）

**继承OpenHuman的概念：** 即使不与AI交互，后台也自主运行：

```
潜意识循环 (每5分钟检查):
1. 加载待办事项列表
2. 读取近期新增记忆
3. 检查是否有需要提醒的事项
4. 如果有紧急事项 → WebSocket推送通知
5. 检查数据源是否有新数据 → 触发轮询
```

### Phase C：国内生态深耕（差异化王牌）

**已知OpenHuman短板，我们直接冲刺：**

| 平台 | 状态 | 方案 |
|------|------|------|
| 微信 | 🟡 连接器框架已就绪 | 企业微信Webhook + 个人微信itchat桥接 |
| 钉钉 | 🟡 连接器框架已就绪 | 钉钉开放平台Webhook |
| 飞书 | 🟡 连接器框架已就绪 | 飞书机器人 + 文档API |
| 公众号 | 🔴 待开发 | 公众号后台接入作为信息输入 |

### Phase D：AI增强

- DeepSeek API用于记忆压缩和摘要（OpenHuman用未知模型）
- Ollama本地模式用于隐私敏感场景
- 记忆查询→RAG增强（AI不仅记住，还能关联推理）

## 四、GitHub营销策略

OpenHuman的登顶给了我们清晰的方向——**做国内生态版的OpenHuman，但有MIT许可+纯Python+微信支持**。

### 差异化定位词

```
| OpenHuman              | PME (我们的定位)          |
|------------------------|--------------------------|
| 「真正懂你的AI助手」     | 「真正懂你的AI记忆引擎」   |
| 国际生态优先            | 国内生态优先              |
| GPL-3.0强制开源        | MIT自由商用               |
| 10万+Rust             | 3000行Python人人可改      |
| 桌面App               | 一键pip install启动       |
```

### 发布文案

```
🧠 当OpenHuman在GitHub登顶TOP1...

我意识到一个问题：没有微信/钉钉/飞书的"AI第二大脑"，
对中国开发者来说等于没有腿。

于是我花了48小时，用Python re:Invent 了 OpenHuman 的核心：

✅ 三层记忆引擎 (L1→L2→L3 渐进蒸馏)
✅ TokenJuice压缩 (60-80%省Token)
✅ 118+数据源连接器框架
✅ 微信/钉钉/飞书原生就绪
✅ MIT许可 ← 和GPL说再见
✅ 3000行Python ← 人人都能改

我叫它 Personal Memory Engine🚀

MIT on GitHub → longongzi/personal-memory-engine
```

## 五、技术路线图（v0.2 执行计划）

| 任务 | 工作 | 工程量 |
|------|------|--------|
| 🔲 **三栏Web UI** | 重写index.html为三栏布局+Mascot表情 | 2天 |
| 🔲 **潜意识循环** | 后台异步任务+WebSocket推送 | 1天 |
| 🔲 **密钥链集成** | 系统密钥链API（macOS Keychain / Windows Credential Manager） | 1天 |
| 🔲 **Ollama集成** | Python调用Ollama API进行本地蒸馏 | 1天 |
| 🔲 **微信连接器** | 企业微信Webhook+个人微信桥接 | 2天 |
| 🔲 **DeepSeek增强压缩** | 用DeepSeek API替代本地规则的智能压缩 | 1天 |
| 🔲 **推文+知乎+掘金** | 多平台分发技术博客 | 1天 |

总预估：**9天**全职开发
