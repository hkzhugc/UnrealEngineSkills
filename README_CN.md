# Unreal Engine AI 编程助手技能集

[English](README.md)

> **注意**：以下路径使用 `.claude` 作为 AI 助手配置目录名。如果您使用的工具
> 目录不同（如 `.windsurf`、`.cursor` 等），请相应替换。Python 脚本会自动
> 检测正确目录，也可通过环境变量 `AGENT_DIR_NAME` 覆盖。

一组 [Claude Code 技能](https://docs.anthropic.com/en/docs/claude-code)（同时兼容其他 LLM 编程客户端），让 AI 助手深入理解 Unreal Engine 4.26 代码库。

## 解决什么问题

UE 源码对 AI 来说很难处理——1,200+ 个模块、4,000 万行以上的 C++，没有任何导航地图。这套技能构建并维护一个**结构化知识图谱**，让 AI 能够：

- 在提出修改建议前，先理解模块依赖关系和分层结构
- 为每个模块生成准确的功能摘要
- 追踪 Shader 到 C++ 的绑定关系，辅助渲染相关工作
- 按正确的依赖顺序规划跨模块修改
- 通过函数目录发现和编写 Blueprint 可调用的 Python 脚本

## 技能一览

### `ue-knowledge-init` — 冷启动生成器

从零构建完整的知识图谱。确定性的 Python 脚本处理繁重工作（解析 1,274 个 Build.cs 文件、映射 595 个 Shader），LLM 子代理以受控的批次生成人类可读的模块摘要。

| 阶段 | 脚本 | 需要 LLM? | 输出 |
|------|------|----------|------|
| 1. 模块图谱 | `parse_module_graph.py` | 否 | `module_graph.json`（约 1,274 个模块，拓扑层级 0-23） |
| 2. 模块摘要 | `generate_summaries.py` | 是（分批子代理） | 每个模块一个 `modules/{Name}.md` |
| 3. Shader 映射 | `generate_shader_map.py` | 否 | `shader_map.json`（595 个 Shader → C++ 对应关系） |

快速开始：

```bash
# 运行全部（阶段 1 和 3 自动完成，阶段 2 输出批处理计划）
python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py

# 或者分阶段单独运行
python Engine/.claude/skills/ue-knowledge-init/scripts/parse_module_graph.py
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_shader_map.py
python Engine/.claude/skills/ue-knowledge-init/scripts/generate_summaries.py --tier 1 --resume
```

### `ue-knowledge-reader` — 导航与查询工具

日常使用的主要技能。当你打开一个 UE 源文件或问"X 是怎么工作的"时，这个技能会：

1. 从文件路径识别所属模块
2. 通过 `query_module_graph.py` 查询依赖图谱（绝不直接加载 727KB 的 JSON）
3. 加载模块摘要作为上下文
4. 提供紧凑的定位信息头和跨模块导航

如果某个模块的摘要不存在，它会通过子代理**按需生成**——知识图谱在你工作的过程中逐步自我完善。

### `ue-knowledge-update` — 增量更新器

在代码变更后保持知识图谱同步。按类型分类变更文件（依赖 / API / 实现 / Shader），然后：

- 如果 Build.cs 文件有变更，重新运行 `parse_module_graph.py`
- 编辑受影响的模块摘要（或通过子代理生成缺失的摘要）
- 如果 Shader 有变更，更新 `shader_map.json`
- 追加记录到 `changelog.md`

### `ue-script-catalog` — 脚本发现与执行

连接到预构建的引擎 Blueprint 可调用函数目录。支持按意图搜索函数、编写 Python 代码片段，以及通过 MCP 在编辑器中执行。

## 架构

```
Engine/.claude/skills/                    ← 本仓库
├── ue-knowledge-init/
│   ├── SKILL.md                          ← 技能指令
│   ├── scripts/
│   │   ├── parse_module_graph.py         ← 阶段 1：Build.cs → module_graph.json
│   │   ├── generate_shader_map.py        ← 阶段 3：Shader → shader_map.json
│   │   ├── generate_summaries.py         ← 阶段 2：批处理计划器（JSON 输出）
│   │   ├── query_module_graph.py         ← 图谱命令行查询工具
│   │   └── init_all.py                   ← 主编排器
│   └── references/
│       ├── summary-template.md           ← 模块摘要输出格式
│       └── summary-generation-prompt.md  ← 共享的子代理提示词（单模块 + 批量）
├── ue-knowledge-reader/
│   ├── SKILL.md
│   └── references/
│       └── graph-schema.md               ← module_graph.json 结构文档
├── ue-knowledge-update/
│   ├── SKILL.md
│   └── scripts/
│       └── trigger_knowledge_update.py
└── ue-script-catalog/
    ├── SKILL.md
    └── references/
        └── safety-protocol.md

Engine/.claude/knowledge/                 ← 生成的输出（不在本仓库中）
├── module_graph.json
├── shader_map.json
├── changelog.md
└── modules/
    ├── Core.md
    ├── Engine.md
    └── ...
```

## 设计决策

**为什么用 Python 脚本而不是纯 LLM？**
解析 1,279 个 Build.cs 文件和 595 个 Shader 是确定性的文本提取——用 LLM token 做这些事会导致上下文溢出。Python 脚本在 30 秒内完成，零幻觉风险。LLM 只用于需要智能的任务：阅读头文件并撰写有用的摘要。

**为什么用查询工具而不是直接读 module_graph.json？**
生成的 `module_graph.json` 约 727KB / 27K 行。直接加载到任何 LLM 上下文窗口都不现实。`query_module_graph.py` 在 Python 中加载它，只返回请求的片段（通常不超过 50 行）。

**为什么用子代理分发而不是 `claude` CLI？**
摘要生成最初通过 `claude -p` 子进程调用。后改为子代理分发（通过 Task 工具），这样技能可以在任何 LLM 客户端上工作——Claude Code、Cursor、Cline、Copilot 等。

**为什么在 reader/update 中按需生成摘要？**
如果 `ue-knowledge-init` 只生成了 tier-1 的摘要（10 个模块），其余 1,264 个模块将永远没有摘要。reader 和 updater 现在能在遇到缺失时自动填补，使知识图谱逐步自我完善。

**为什么要共享提示词模板？**
三个技能（init、reader、update）都需要通过子代理生成摘要。提示词原本在三处重复（每处约 30 行）。提取到 `summary-generation-prompt.md` 后，修改生成逻辑只需改一个地方。

## 安装

1. 将本仓库克隆到 `Engine/.claude/skills/`：
   ```bash
   cd /path/to/UnrealEngine/Engine/.claude
   git clone https://github.com/hkzhugc/UnrealEngineSkills.git skills
   ```

2. 运行知识图谱初始化：
   ```bash
   cd /path/to/UnrealEngine
   python Engine/.claude/skills/ue-knowledge-init/scripts/init_all.py
   ```

3. 技能会被 Claude Code（或任何从 `.claude/skills/` 目录读取 `SKILL.md` 文件的兼容 LLM 客户端）自动识别。

## 环境要求

- Python 3.6+
- Unreal Engine 4.26 源码
- 支持技能文件的 LLM 编程助手（Claude Code 等）

## 许可证

MIT
