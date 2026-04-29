# Mini Claw-Coder

**Mini Claw-Coder 是一个面向代码任务的可验证 Coding Agent Runtime。**

它不是单纯的 ChatGPT Wrapper，也不是把一堆工具接到模型上的 CLI Demo。这个项目关注的是 Coding Agent 真正进入工程场景时最容易出问题的部分：上下文失控、工具面过大、模型成本不可控、代码修改不安全、失败原因不可追踪、经验无法复用。

项目核心目标：

> 用尽量少的工具接口，构建一个可控、可观测、可评测、可持续改进的代码智能体运行时。

## 解决的问题

现有 Coding Agent 在真实代码仓库中执行多步开发任务时，经常会遇到这些问题：

- 工具越接越多，模型的行动空间变大，行为更难审计。
- 长任务中上下文不断膨胀，模型容易忘记约束、重复搜索或遗漏关键文件。
- 所有步骤都使用同一个模型，简单任务浪费成本，复杂任务又缺少升级策略。
- 代码修改缺少事务边界，容易基于过期文件内容误改。
- Agent 失败后只能看到日志，很难判断失败根因。
- 成功经验无法沉淀，下次任务仍然从零开始。

Mini Claw-Coder 将这些问题抽象为 **Agent Runtime 可靠性问题**，通过最小工具集、上下文编译、模型路由、记忆、技能、追踪和评测来解决。

## 设计定位

项目定位可以概括为：

```text
Minimal Tools + Context Compiler + Patch Transaction + Runtime Trace + Eval Loop
```

与常见 CLI Code Agent 的区别：

```text
常见方案：Read / Edit / Write / Bash / Todo / Skills 等多个语义工具
本项目：当前暴露 shell / apply_patch / tool_output_lookup，后续将 compact 作为上下文控制工具加入最小工具内核

常见方案：上下文分层与历史压缩
本项目：把上下文构造成 ContextPacket，按任务阶段编译给模型

常见方案：工具调用日志
本项目：当前已实现 trace + replay + eval + failure attribution

常见方案：一次性生成 patch
本项目：已实现 snapshot / hash / diff summary / verification binding / rollback journal 的事务化编辑
```

## 当前架构

```text
User Task
   |
   v
Agent Loop
   |
   +-- Context Manager
   |      +-- task context
   |      +-- workspace snapshot
   |      +-- file index preview
   |      +-- project memory
   |      +-- loaded skills
   |      +-- execution trace
   |
   +-- Model Router
   |      +-- planner
   |      +-- coder
   |      +-- reviewer
   |
   +-- Memory Store
   |      +-- project_memory.md
   |      +-- task_trace.jsonl
   |      +-- tool_outputs/
   |
   +-- Skill Loader
   |      +-- SKILL.md
   |
   +-- ACP-like Handoff
   |      +-- planner -> coder
   |      +-- coder -> reviewer
   |
   +-- TaskGraph / Todo
   |      +-- pending / in_progress / blocked / done / failed
   |      +-- dependencies
   |      +-- context refs
   |      +-- verification command
   |
   +-- Task Workspace Manager
   |      +-- workspace_copy isolation
   |      +-- task -> workspace attachment
   |      +-- diff summary
   |
   v
Minimal Tools
   +-- shell
   +-- apply_patch
   +-- tool_output_lookup
```

## 已实现能力

### 1. Agent Loop

核心循环位于 `mini_claw.agent`：

- 接收用户代码任务。
- 构造上下文。
- 根据任务状态选择角色和模型。
- 调用模型生成下一步行动。
- 执行工具。
- 记录 trace。
- 根据结果继续迭代或输出最终总结。

当前实现的是一个轻量 observe-think-act loop，方便后续接入更复杂的 planner、reviewer 和 tester。

### 2. 最小工具系统

工具层位于 `mini_claw.tools`。

当前只暴露三个工具：

```text
shell
apply_patch
tool_output_lookup
```

`shell` 负责：

- 搜索代码。
- 查看文件。
- 运行测试。
- 执行构建或检查命令。

`apply_patch` 负责：

- 创建文件。
- 替换文本。
- 删除文件。
- 阻止路径逃逸。
- 返回结构化修改结果。

`tool_output_lookup` 负责：

- 根据 `output_id`、数字索引、`latest` 或 `latest_truncated` 回查工具结果。
- 按 `query`、`line_start` / `line_end`、`max_chars` 获取聚焦片段。
- 支持 `focus='auto'`，根据 runtime 持久化的 lookup plan 自动选择高信号片段。
- 支持 `intent='error' | 'path' | 'symbol' | 'task'` 和 `exclude_queries`，让 agent 对同一份长输出做多跳证据细化。
- 让 agent 在不重跑外部命令的情况下二次读取长输出。

这样的设计让工具接口更少、更稳定，也更容易做安全控制和行为审计。

### 2.1 统一 Tool Output Protocol

当前工具执行结果不再直接把完整输出塞进上下文，而是拆成两层：

- **原始结果存储**：工具原始输出写入 `.mini_claw/memory/tool_outputs/<output_id>.json`。
- **上下文内预览**：Agent Step 中只保留统一结果摘要、截断状态和 lookup hint。

统一协议字段包括：

- `output_id`
- `tool`
- `ok`
- `output_chars`
- `stored_output_chars`
- `truncated`
- `store_truncated`
- `lookup_hint`

CLI 示例：

```bash
python -m mini_claw tool-output list --limit 5
python -m mini_claw tool-output show 1
```

当 observation 显示某个工具结果被截断时，agent 也可以直接调用：

```json
{
  "tool": "tool_output_lookup",
  "args": {
    "ref": "latest_truncated",
    "focus": "auto",
    "max_chars": 240
  }
}
```

如果第一次 auto focus 还不够，也可以继续细化：

```json
{
  "tool": "tool_output_lookup",
  "args": {
    "ref": "latest_truncated",
    "focus": "auto",
    "intent": "error",
    "exclude_queries": ["README.md"],
    "max_chars": 240
  }
}
```

面试讲法：

> 我把工具结果拆成“可注入预览”和“可回查原文”两层。当前 step observation 只保留统一协议摘要，长输出会被截断并存档到 tool output store，trace 里记录 output id 和截断状态。这样既降低上下文污染，也保留调试和二次查看的能力。

### 3. 上下文管理

上下文模块位于 `mini_claw.context`。

当前上下文由以下部分组成：

- 用户任务。
- 工作区文件快照。
- 项目记忆。
- 已加载技能。
- 最近执行轨迹。

当前已经引入 `ContextPacket` 和 `ContextCompiler`。每次上下文构造都会生成结构化上下文包，并产出 `ContextBudgetReport`，记录 `used_chars`、`max_chars`、是否压缩、被截断的 section 和被省略的 section。Agent Loop 会把这些预算信息写入 runtime trace，方便后续分析上下文污染和上下文缺失问题。

ContextPacket 还会注入 `File Index Preview`，它不是完整文件内容，而是文件路径、语言、大小、关键符号和少量预览行。模型先看到候选文件索引，再通过 `shell` 按需读取完整文件，形成渐进式披露。

长任务里，runtime 还会对较早的步骤自动做一次轻量 compact：保留最近几步完整 trace，把更早的步骤压成 `Working Summary` 注入上下文。这个 summary 会记录已压缩步骤数、工具调用分布、已修改文件和 older step highlights，并写入 `context_compacted` trace，避免执行轨迹无限膨胀。

### 3.1 FileIndex / 渐进式披露

文件索引模块位于 `mini_claw.context.file_index`。

当前支持：

- 忽略 `.git`、`.mini_claw`、`.venv`、`node_modules`、缓存目录等无关内容。
- 按后缀识别 Python、JavaScript、TypeScript、Markdown、JSON、YAML 等文本文件。
- 抽取文件大小、语言、预览行。
- 对 Python 提取 `class` / `def` 符号。
- 对 JS / TS 提取 `class` / `function` / `const` 等符号。
- 对 Markdown 提取标题。
- 根据当前任务 query 对文件进行轻量打分。

CLI 示例：

```bash
python -m mini_claw index --query "memory file index" --limit 8
```

面试讲法：

> 我没有让模型一上来读取大量完整文件，而是先注入 FileIndex Preview，让模型看到路径、语言、符号和少量预览。只有当任务需要具体实现细节时，才通过 shell 读取完整文件。这是一种渐进式披露策略，可以降低上下文污染和 token 浪费。

### 4. 模型路由

模型路由位于 `mini_claw.routing`。

当前策略：

- 第一步使用 `planner`。
- 正常执行使用 `coder`。
- 出现失败后切换到 `reviewer`。
- 多次失败后升级到更强模型。

这个模块用于展示一个关键思想：

> Coding Agent 不应该所有步骤都使用同一个模型，而应该根据任务阶段、失败次数和风险等级动态选择模型。

### 5. 记忆系统

记忆模块位于 `mini_claw.memory`。

当前持久化两类信息：

```text
.mini_claw/memory/project_memory.md
.mini_claw/memory/task_trace.jsonl
.mini_claw/memory/tool_outputs/<output_id>.json
```

`project_memory.md` 用于存储项目级知识，例如：

- 项目技术栈。
- 常用测试命令。
- 启动方式。
- 用户偏好。
- 不建议修改的文件。

`task_trace.jsonl` 用于记录 agent 每一步行为，方便排查问题和后续做 eval。

`tool_outputs/<output_id>.json` 用于记录工具原始结果、结果预览、截断状态和回查入口。

当前 memory 不是简单把历史对话全部塞回 prompt，而是分成两类：

- **可注入记忆**：`project_memory.md`，进入 ContextPacket，帮助模型复用项目级事实。
- **可回放记忆**：`task_trace.jsonl`，不直接全部注入模型，而是用于 replay、eval、失败归因和系统调试。
- **可回查工具结果**：`tool_outputs/*.json`，保存工具原始输出，避免长结果直接污染 observation。

这样的设计可以避免长期历史污染上下文，同时保留 agent 行为的可观测性。

### 6. Skill 系统

技能模块位于 `mini_claw.skills`。

每个 skill 是一个目录，包含一个 `SKILL.md`。当前支持两种格式：

- 普通 Markdown：兼容旧 skill。
- 带 front matter 的 Skill Contract：定义触发条件、输入输出、工具边界和验证方式。

```text
.mini_claw/skills/python-debug/SKILL.md
.mini_claw/skills/react-fix/SKILL.md
.mini_claw/skills/repo-onboarding/SKILL.md
```

Skill Contract 示例：

```yaml
---
name: repo-onboarding
description: Inspect an unfamiliar repository and summarize supported facts.
triggers:
  - inspect
  - repository
inputs:
  - user task
  - file index preview
outputs:
  - repository summary
allowed_tools:
  - shell
forbidden_paths:
  - .git
  - .mini_claw
verification:
  - cite observed files or command output
---
```

Agent 在构造上下文时会根据当前任务 query 对 skill 进行轻量相关性打分，最多注入 3 个相关 skill，而不是全量注入所有技能。

CLI 示例：

```bash
python -m mini_claw skills list --include-examples
python -m mini_claw skills match "inspect this repository" --include-examples
```

后续可以继续升级为：

- 从失败归因中生成 skill patch。
- 通过 eval 验证 skill 是否真的提升成功率。

### 7. ACP-like Handoff

协议模块位于 `mini_claw.protocol`。

当前提供了轻量的 handoff 消息结构：

```text
Planner -> Coder
Coder -> Reviewer
Reviewer -> Integrator
```

它不是为了复刻某个完整协议，而是为了把 agent 内部协作抽象成稳定的数据结构，方便后续扩展多 Agent、任务图和 worktree 隔离。

### 8. Eval Runner / EvalBench

评测模块位于 `mini_claw.evals`。

当前支持 JSONL 格式任务：

```json
{"task": "Inspect the repository and summarize what kind of project this is."}
```

运行后输出：

```text
total
passed
failed
```

后续会加入更多指标：

- 成功率。
- 工具调用次数。
- 重试次数。
- 上下文压缩次数。
- 模型升级次数。
- patch 行数。
- 测试是否通过。
- 失败归因类型。

当前还实现了离线 `EvalBench`：

- 使用 JSON/JSONL 描述 bench case。
- 每个 case 可以创建临时工作区文件。
- 使用 scripted model actions 测试 runtime，不依赖 API key。
- 支持 verification commands。
- 支持 expected_success，用于测试预期失败和失败归因。
- 输出 success_rate、tool_calls、context_builds、agent_step_failures、patch_transactions、failure_root_cause 等指标。

这让项目可以先用离线数据验证 runtime 能力，再接真实模型跑端到端成功率。

### 9. Patch Transaction

安全编辑模块位于 `mini_claw.safety`。

`apply_patch` 当前已经升级为事务化执行：

- 每次 patch 生成唯一 `transaction_id`。
- 修改前捕获文件快照。
- 对文件内容计算 `sha256`。
- 支持 `expected_sha256` 作为写入前置条件。
- `replace` 操作使用非空 `old` 文本作为乐观锁。
- 覆盖已有文件时必须提供 `expected_sha256` 或显式 `allow_overwrite=true`。
- 删除已有文件时必须提供 `expected_sha256` 或显式 `allow_delete=true`。
- 可选开启 read-before-write guard：`shell` 读取文件时会记录 `.mini_claw/memory/read_snapshots.jsonl`，`apply_patch` 写入已有文件前会校验该文件是否被读过且 hash 未漂移。
- 如果没读过目标文件，会返回 `READ_BEFORE_WRITE_REQUIRED`；如果读后文件发生变化，会返回 `STALE_READ_SNAPSHOT`。
- 如果事务中间失败，会自动按快照回滚。
- 每次事务写入 `.mini_claw/patch_journal/*.json`，记录 before / after / diff_summary / verification_results / error / rolled_back。
- 支持将验证命令绑定到 patch transaction，通过 `verify` 字段在修改后自动运行测试或检查命令。
- 验证失败时默认保留 patch，便于 agent 继续修复；也可以显式设置 `rollback_on_verification_failure=true` 自动回滚。

这让代码修改不再是一次普通写文件，而是具有 precondition、read snapshot、stale-read blocking、diff、verification、journal 和 rollback 的事务。

CLI 运行 agent 时可以显式开启 read-before-write：

```bash
python -m mini_claw run "fix app.py" --enforce-read-before-write
```

### 10. Failure Attribution

失败归因模块位于 `mini_claw.reliability`。

当 agent 没有在最大步数内完成任务时，系统会根据最后的 observation 生成 `FailureReport`：

```text
BAD_TOOL_USE
MODEL_OUTPUT_INVALID
PATCH_CONFLICT
READ_BEFORE_WRITE_REQUIRED
STALE_READ_SNAPSHOT
COMMAND_TIMEOUT
DEPENDENCY_OR_ENVIRONMENT
VERIFICATION_FAILED
UNKNOWN
```

失败报告会写入最终结果和 `task_trace.jsonl`，包含：

- root_cause
- evidence
- suggested_action

这让失败不只是日志，而是可以进入 eval、skill 更新和 routing policy 调整的结构化信号。

### 11. Trace Replay

回放模块位于 `mini_claw.tracing`。

`mini_claw replay` 可以读取 `.mini_claw/memory/task_trace.jsonl`，输出一次运行的结构化摘要：

- 总事件数。
- context build 次数。
- tool call 次数。
- 失败工具调用次数。
- 被截断的 tool output 次数。
- patch transaction 数量。
- failure report 数量。
- 各类事件分布。

这让 trace 不只是日志文件，而是可以被分析、比较和纳入 eval 的运行时证据。

### 12. TaskGraph / Todo

任务图模块位于 `mini_claw.task_graph`。

当前支持持久化任务节点：

```text
task_id
objective
status
owner_role
dependencies
context_refs
verification_command
workspace_path
notes
background_run_ids
```

状态包括：

```text
pending
in_progress
blocked
done
failed
```

CLI 支持：

```bash
python -m mini_claw todo add "Implement FileIndex preview" --task-id fileindex
python -m mini_claw todo list
python -m mini_claw todo ready
python -m mini_claw todo show fileindex
python -m mini_claw todo note fileindex "pytest is running in background"
python -m mini_claw todo status fileindex done
```

这个模块让复杂任务不再只是线性对话，而是可以拆成带依赖、上下文引用和验证命令的持久化任务图。现在 `TaskNode` 还可以挂接 `background_run_ids`，把长时间验证、构建或抓取命令直接绑定到任务节点上，便于后续 `todo show` 审阅。

### 13. 任务级隔离工作区

任务级隔离模块同样位于 `mini_claw.task_graph`。

当前提供一个不依赖 `git worktree` 的基础隔离实现：`workspace_copy`。

它的目标不是立即解决所有并行合并问题，而是先把“任务在独立环境里修改代码”这件事落地，并让结果可比较、可挂接到 TaskGraph：

- 在 `.mini_claw/task_workspaces/<task_id>` 下创建任务级工作区副本。
- 为每个任务工作区记录 base manifest，用于判断主工作区是否已经漂移。
- 默认忽略 `.git`、`.mini_claw`、`.venv`、`node_modules`、缓存目录等内部内容。
- `workspace create <task_id>` 会自动把隔离工作区路径写回对应 `TaskNode.workspace_path`。
- `workspace list` 可以查看隔离工作区及其是否已挂接任务图。
- `workspace diff <task_id>` 可以把任务工作区和主工作区做文本差异摘要。
- `workspace merge <task_id>` 会基于 manifest 检测冲突，并通过事务化 patch 安全合回主工作区。

CLI 示例：

```bash
python -m mini_claw workspace create fileindex
python -m mini_claw workspace list
python -m mini_claw workspace diff fileindex
python -m mini_claw workspace merge fileindex --dry-run
```

这让“任务编排 -> 隔离执行 -> 差异回看 -> 安全合并”形成了一个基础闭环。后续可以在这个基础上继续补真正的 integrator 角色、冲突仲裁策略和 `git worktree` 模式。

## 快速开始

运行离线 mock agent：

```bash
python -m mini_claw run "inspect this repository"
```

启动交互式 coding chat（更接近持续发需求的工作流）：

```bash
python -m mini_claw chat
python -m mini_claw chat --provider openai-compatible --model your-coder-model
```

`chat` 默认使用隔离工作区执行每一轮任务，并在成功后自动 merge-back；如果仓库里存在 `tests/`，会默认附带 `python -m unittest discover -s tests -q` 作为 merge 验证命令。输入 `/help` 可以查看可用命令，输入 `/exit` 结束会话。

运行示例 eval：

```bash
python -m mini_claw eval examples/eval_tasks.jsonl
```

运行离线 EvalBench：

```bash
python -m mini_claw bench examples/bench/runtime_smoke.json
```

对比不同 routing policy：

```bash
python -m mini_claw bench-routing examples/bench/runtime_smoke.json --policies basic signal-aware
```

查看文件预览索引：

```bash
python -m mini_claw index --query "agent loop" --limit 10
```

创建持久化 session 并续跑：

```bash
python -m mini_claw session create --name repo-debug
python -m mini_claw session list
python -m mini_claw run "inspect this repository" --session 1
python -m mini_claw session show 1
python -m mini_claw session replay 1
python -m mini_claw session turn-show 1 1
python -m mini_claw dashboard
```

管理任务图和隔离工作区：

```bash
python -m mini_claw todo list
python -m mini_claw todo show fileindex
python -m mini_claw todo note fileindex "started repo-wide unittest"
python -m mini_claw workspace create fileindex
python -m mini_claw workspace diff fileindex
python -m mini_claw workspace merge fileindex --dry-run
```

运行后台命令并把结果挂到任务图：

```bash
python -m mini_claw background start --task-id fileindex --label unittest --command "python -m unittest discover -s tests -q"
python -m mini_claw background list
python -m mini_claw background show 1
python -m mini_claw background wait 1
```

查看工具结果存档：

```bash
python -m mini_claw tool-output list --limit 5
python -m mini_claw tool-output show 1
```

回放 runtime trace：

```bash
python -m mini_claw replay
```

运行测试：

```bash
python -m unittest discover -s tests -q
```

接入 OpenAI-compatible 接口：

```bash
set MINI_CLAW_API_KEY=your_key
python -m mini_claw run "fix the failing test" --provider openai-compatible --model your-coder-model
```

使用自定义 endpoint：

```bash
set MINI_CLAW_BASE_URL=https://your-endpoint.example/v1
set MINI_CLAW_API_KEY=your_key
python -m mini_claw run "add a CLI option" --provider openai-compatible --model your-model
```

## 工具调用协议

`apply_patch` 使用结构化操作：

```json
{
  "operations": [
    {
      "op": "write",
      "path": "src/app.py",
      "content": "print('hello')\n"
    },
    {
      "op": "replace",
      "path": "src/app.py",
      "old": "hello",
      "new": "mini claw"
    }
  ],
  "verify": ["python -m unittest discover -s tests -q"],
  "rollback_on_verification_failure": false
}
```

支持的操作：

```text
write
replace
delete
```

当前已实现路径逃逸保护、文件快照 hash、事务 journal、diff 摘要、verification 绑定和失败回滚。

## 面试讲法

可以这样介绍这个项目：

> 我做的是一个面向代码任务的 Agent Runtime，不只是 CLI Code Agent。项目的核心问题是：如何让 Coding Agent 在真实代码仓库里可控、可观测、可评测地完成任务。我没有选择堆很多外部工具，而是把行动接口收敛到 shell、apply_patch 和只读的 tool_output_lookup，再把复杂能力放到 runtime 层，包括上下文管理、模型路由、记忆系统、skill 系统、handoff、trace、eval、事务化编辑和失败归因。这样 agent 的每次上下文构造、工具调用、文件修改和失败原因都能被记录、分析和改进。

## 与同类项目的差异

| 维度 | 常见 CLI Code Agent | Mini Claw-Coder |
| --- | --- | --- |
| 工具系统 | 多个语义工具 | shell / apply_patch / tool_output_lookup 最小工具核 |
| 上下文 | 分层拼接和压缩 | 面向 Context Compiler 演进 |
| 渐进披露 | 预览注入 + 按需读取 | FileIndex Preview + shell 按需读取 |
| 编辑安全 | read-before-write | Patch Transaction：read snapshot / stale-read block / hash / diff / verify / journal / rollback |
| 工具结果治理 | 长输出容易直接污染上下文 | 统一 output protocol + truncation + result lookup + lookup policy + evidence planner |
| 日志 | runtime tracing | trace + replay + eval |
| 失败处理 | 人工看日志 | Failure Attribution：失败根因、证据和建议动作 |
| 技能系统 | 按需加载技能 | Skill Contract：triggers / inputs / outputs / tools / paths / verification |
| 任务编排 | Todo / 任务图 | TaskGraph / Todo + task workspace attachment |
| 隔离与合并 | worktree / patch flow | workspace_copy + manifest conflict detection + transactional merge |
| 多 Agent | 角色协作 | ACP-like handoff + workspace_copy 隔离基础版 |

## 路线图

### P0：可运行的 Coding Agent Runtime

- [x] CLI 入口。
- [x] Agent Loop。
- [x] mock model client。
- [x] OpenAI-compatible client。
- [x] shell 工具。
- [x] apply_patch 工具。
- [x] memory trace。
- [x] skill loader。
- [x] Skill metadata contract。
- [x] eval runner。
- [x] offline EvalBench。
- [x] TaskGraph / Todo。
- [x] FileIndex / 渐进式披露。

### P1：可靠性增强

- [x] ContextPacket / ContextCompiler。
- [x] 文件快照与 hash 校验。
- [x] Patch Transaction。
- [x] read-before-write guard。
- [x] stale-read snapshot blocking。
- [x] rollback journal。
- [x] Runtime Event Schema。
- [x] Failure Attribution。
- [x] diff 摘要。
- [x] patch 与 verification 命令绑定。

### P2：评测与自进化

- [x] EvalBench 框架。
- [x] 统计工具调用、context build、agent step failure、patch transaction。
- [ ] 构建 10 个 coding eval tasks。
- [ ] 统计耗时、重试、patch 大小和上下文长度。
- [x] 支持 trace replay。
- [ ] 根据失败归因生成 skill patch。
- [ ] 使用 eval 验证 skill 和 routing policy 的改进效果。

### P3：多 Agent 协作

- [x] 持久化任务图。
- [ ] reviewer / tester / integrator 角色。
- [x] 基础 merge flow。
- [ ] 多候选 patch 仲裁。
- [x] 任务级 workspace_copy 隔离。
- [ ] git worktree 隔离。
- [ ] ACP adapter。

## 项目价值

Mini Claw-Coder 的价值不在于替代 Cursor、Claude Code 或其他成熟产品，而在于完整拆解并实现 Coding Agent 的核心运行时机制：

- Agent 如何行动。
- 上下文如何组织。
- 模型如何路由。
- 工具如何约束。
- 修改如何验证。
- 失败如何归因。
- 经验如何沉淀。

这些能力正是 Agent 应用开发岗位需要的底层工程能力。

## 工程记录

项目实现过程、测试数据、memory 设计取舍、优化过程和面试追问统一维护在：

```text
docs/ENGINEERING_LOG_ZH.md
```

后续每次新增能力或跑 eval，都应该把关键命令、结果和设计取舍补到这份文档里。

## 最新增强：Skill Guardrail 与候选记忆

Skill Contract 现在已经不只是上下文提示，而是接入了 runtime guardrail：

- `allowed_tools` 会限制 active skill 下允许调用的工具。
- `forbidden_paths` 会阻止工具参数中引用禁止路径。
- 违规调用会记录为 `agent_step_failed`，reason 为 `skill_guardrail`。
- Failure Attribution 会识别 `SKILL_GUARDRAIL_BLOCKED`。

Memory 也升级为 candidate-first 策略：

- 成功任务不会直接写入长期 `project_memory.md`。
- 系统先写入 `.mini_claw/memory/memory_candidates.jsonl`。
- 每条候选记忆包含 `source`、`confidence`、`evidence` 和 `tags`。
- mock provider 不写候选记忆，避免演示输出污染长期记忆。

查看候选记忆：

```bash
python -m mini_claw memory candidates
python -m mini_claw memory promote 1 --reason "verified by tests"
python -m mini_claw memory reject 1 --reason "low confidence"
```

Promote/reject 决策会写入 `.mini_claw/memory/memory_candidate_decisions.jsonl`，并记录到 runtime trace。被 promote 的候选会按类型处理：项目事实类候选会追加到 `project_memory.md`，`evidence_lookup_strategy` 会保持独立，`skill_patch_candidate` 会生成 `.mini_claw/skill_patches/<artifact_id>.md` 审阅 artifact，避免把一次性的运行时策略或演进建议直接污染长期项目记忆。

## 最新增强：任务级隔离工作区

TaskGraph 现在不只记录任务状态，也能记录任务对应的隔离工作区：

- 新增 `TaskWorkspaceManager`，在 `.mini_claw/task_workspaces/<task_id>` 下创建任务级工作区副本。
- `workspace create` 会自动把生成的工作区路径挂到对应 `TaskNode.workspace_path`。
- `workspace list` 会展示隔离工作区与任务图的挂接状态。
- `workspace diff` 会输出任务工作区相对主工作区的差异摘要，便于 integrator 后续接手。

这一版刻意先不直接依赖 `git worktree`，因为我更想先证明任务隔离、任务编排和差异回看的数据结构是通的。等 integrator merge flow 和冲突策略稳定后，再接 `git worktree` 会更自然。

## 最新增强：任务工作区安全合并

任务级隔离现在不只停留在“分出去改”，而是补上了基础 merge flow：

- `workspace create` 会记录 base manifest，保存创建时主工作区的文本文件快照摘要。
- `workspace merge` 会先比较 base manifest、当前主工作区和任务工作区，判断主工作区是否已经漂移。
- 如果主工作区和任务工作区都改了同一个文件，merge 会直接阻止并给出 conflict。
- 无冲突时，merge 会复用 `PatchTransaction` 把改动事务化写回主工作区，并支持 verification 命令。
- 如果任务图里配置了 `verification_command`，`workspace merge` 默认会带上它一起执行。

这一版的重点是把任务隔离最终也收敛到同一套安全编辑机制里，而不是单独开一条“直接 copy 回主仓库”的旁路。

## 最新增强：统一 Tool Output Protocol

工具结果现在不再是“每个工具各返一段字符串”，而是统一接入 tool output store：

- Agent Loop 在每次工具执行后生成统一 `output_handle`。
- observation 中只保留结果预览、字符数、截断状态和 lookup hint。
- 原始结果会存到 `.mini_claw/memory/tool_outputs/<output_id>.json`。
- `tool_call` trace 会记录 `output_handle`，Replay 可以统计被截断的 tool output 数量。
- CLI 提供 `tool-output list/show`，可以回查之前的命令输出和 patch 结果。
- agent 也可以通过 `tool_output_lookup` 基于 `output_id`、`latest` 或 `latest_truncated` 做二次读取。
- runtime 还会挂起 `pending lookup`；如果模型在截断结果之后立刻重复执行 read-only shell inspection，`lookup policy` 会阻断这次调用并要求先走 `tool_output_lookup`。
- tool output store 还会为每条结果生成 `lookup_plan`，给出建议 query、行范围和原因；`tool_output_lookup` 的 `focus='auto'` 会直接消费这份 plan。
- `lookup_plan` 现在还带 `kind` 与 `score`，`tool_output_lookup` 支持 `intent` 和 `exclude_queries`，可以在 path clue -> error clue 这样的多跳证据搜索里继续细化。
- Replay 也会统计 `lookup_auto_focus_calls` 和 `lookup_refinement_calls`，方便观察 agent 是否真正利用了 evidence planner。
- 成功任务如果实际使用了 evidence planner，runtime 会在 `task_finished` 中写入 `evidence_summary`，并额外生成 `evidence_lookup_strategy` memory candidate，把这次证据搜索路径沉淀下来。
- 被 promote 的 `evidence_lookup_strategy` 不会直接写入 `project_memory.md`，而是作为独立策略记忆保留；后续任务构造 `ContextPacket` 时，会按当前 task query 检索最相关的 promoted strategy，并注入单独的 `Evidence Strategies` section，让系统复用“怎么找证据”，同时避免长期事实记忆和运行时策略记忆混在一起。

这版能力的关键价值，是把“工具输出过长导致上下文污染”和“结果太短又丢细节”这两个问题拆开处理：上下文里放预览，存储里放原文，trace 里放引用。

## 最新增强：Candidate-first Skill 自进化

这轮我把 evidence planner 的反馈继续接到了 skill 系统，但仍然保持 candidate-first，不让 runtime 直接修改 `SKILL.md`：

- 当任务成功、实际使用了 evidence lookup，而且当前任务命中了相关 skill 时，runtime 会额外生成 `skill_patch_candidate`。
- 这个 candidate 会记录 `target_skill`、证据查询、intent、建议补充的 triggers / verification，以及一段明确的 instruction patch，核心是把 `tool_output_lookup`、`focus='auto'` 和 refine 流程补回 skill。
- `skill_patch_candidate` 即使被 promote，也不会写入 `project_memory.md`；promote 会生成 `.mini_claw/skill_patches/<artifact_id>.md`，把建议变成可审阅、可归档的 patch artifact。
- Replay 新增 `skill_patch_candidates`、`skill_patch_artifacts_created`、`skill_patch_eval_runs`、`skill_patch_eval_passed` 和 `skill_patch_apply_previews` 指标，可以统计一次运行中生成了多少个建议、多少建议进入人工审阅流、有多少通过验证门禁，以及有多少生成过合入预览。
- CLI 的 `memory candidates` 现在支持 `--kind`、`--status`、`--query` 和 `--limit`，方便单独查看这类演进候选。
- CLI 新增 `memory skill-patches`、`memory skill-patch-show`、`memory skill-patch-verify` 和 `memory skill-patch-preview`，用于列出、查看、验证和 dry-run 预览 promote 后生成的 skill patch artifact。

CLI 示例：

```bash
python -m mini_claw memory candidates --kind skill_patch_candidate
python -m mini_claw memory candidates --kind skill_patch_candidate --query "lookup repo"
python -m mini_claw memory promote skill-patch-candidate-id --reason "reviewed"
python -m mini_claw memory skill-patches
python -m mini_claw memory skill-patch-show 1
python -m mini_claw memory skill-patch-verify 1 --command "python -m unittest discover -s tests -q"
python -m mini_claw memory skill-patch-preview 1
```

这一版的重点不是“让 agent 自动改自己的 skill”，而是先把成功任务里的新经验结构化成可审核建议，再通过 promote 生成独立 artifact，把验证命令和结果追加回 artifact，最后只生成 `SKILL.md` 的 dry-run diff。这样既保留了自进化方向，也保留了工程上的可控性、审计记录和 eval gate。

## 最新增强：Git Worktree 任务隔离

任务工作区现在支持两种隔离模式：

- `copy`：默认模式，在 `.mini_claw/task_workspaces/<task_id>` 下复制当前工作区，适合非 git 项目和测试环境。
- `git-worktree`：在 `.mini_claw/task_worktrees/<task_id>` 下创建独立 git worktree，并自动创建 `mini-claw/<task_id>` 分支，适合真实仓库中的并行任务隔离。

CLI 示例：

```bash
python -m mini_claw workspace create fileindex --mode copy
python -m mini_claw workspace create fileindex --mode git-worktree
python -m mini_claw workspace list
python -m mini_claw workspace diff fileindex
```

不管使用哪种隔离模式，`workspace create` 都会记录 base manifest，并把生成路径挂回 `TaskGraph`。后续 `workspace diff` / `workspace merge` 继续复用同一套 manifest conflict detection 和 `PatchTransaction`，避免任务隔离绕过安全编辑机制。

## 最新增强：最小多 Agent 编排闭环

现在 TaskGraph 不只是任务记录，也可以驱动一个最小可运行的多角色流程：

```text
planner -> coder -> tester -> integrator
```

这版先采用顺序编排，不做复杂并发：

- `planner`：选择 ready task，并将任务置为 `in_progress`。
- `coder`：准备或复用任务级隔离工作区；开启 `--run-coder-agent` 后，会在任务工作区内运行 AgentLoop。
- `tester`：在任务工作区执行 `TaskNode.verification_command`。
- `integrator`：测试通过后调用 `workspace merge`，继续复用 manifest conflict detection、verification 和 `PatchTransaction`。
- 每次角色移交都会写入 `multi_agent_handoff` trace，每个角色步骤都会写入 `orchestration_step` trace。
- `replay` 会统计 `multi_agent_handoffs`、`orchestration_steps`、角色分布、`tester_failures`、`integrator_merges` 和 `integrator_failures`，方便观察多 Agent 编排是否真的推进到了 tester / integrator。

CLI 示例：

```bash
python -m mini_claw orchestrate --limit 1 --mode copy
python -m mini_claw orchestrate --limit 1 --mode git-worktree
python -m mini_claw orchestrate --dry-run
python -m mini_claw orchestrate --run-coder-agent --provider openai-compatible --model your-coder-model
python -m mini_claw replay
```

这一版的重点是把“任务图 -> 隔离执行 -> 测试 -> integrator 合并”跑通。默认模式仍然可以消费已经存在的任务工作区改动，便于测试 integrator；开启 `--run-coder-agent` 后，coder 会在任务工作区中运行真实 AgentLoop。后续可以把顺序执行升级为并行候选 patch + integrator 仲裁。

## 最新增强：持久化 Session 与续跑上下文

这轮补的是 user-facing session 层，但实现上仍然复用了现有 runtime 的 trace、context packet 和 memory：

- 新增 `session create/list/show`，把会话持久化到 `.mini_claw/sessions/<session_id>/`。
- `run` 新增 `--session`，可以把当前请求挂到已有 session 上继续执行。
- 每次 session turn 都会生成独立 turn 记录，保存任务、结果、修改文件、失败报告和一份 turn-level trace slice。
- 会话历史不会直接污染当前 task query，而是作为单独的 `Session Context` section 注入 `ContextPacket`。
- 这样 file index、memory retrieval、skill matching 仍然围绕当前任务工作，但模型又能看到最近几轮已经做过什么。
- 新增 `session replay`，把一个 session 里所有已完成 turn 的 trace slice 聚合起来，输出成功率、tool call、route reason 和 failure root cause。
- 新增 `session turn-show`，可以下钻到单个 turn，看该轮任务、修改文件、失败根因和 trace replay 指标。

CLI 示例：

```bash
python -m mini_claw session create --name repo-debug
python -m mini_claw run "inspect this repository" --session 1
python -m mini_claw run "now summarize the risks" --session 1
python -m mini_claw session show 1
python -m mini_claw session replay 1
python -m mini_claw session turn-show 1 2
```

这一版的重点不是把 CLI 变成聊天壳，而是把“可恢复会话”和“会话级复盘”都收敛到同一套 runtime 数据结构里。session 只负责组织 turn 历史和上下文续接；而 `session replay` / `session turn-show` 则复用 turn-level trace slice，把一整轮会话里发生过什么重新压成结构化证据。所以这层能力是增量的，而不是平行系统。

## 最新增强：统一 Runtime Dashboard

这轮补的是一个真正面向演示和运维观察的总览入口：

- 新增 `dashboard` 命令，把 workspace 里的 trace replay、session、task graph、background runs、tool outputs 和 memory 候选统一汇总。
- 默认会聚焦最近一个 session，并直接展示它的 turn 数、成功/失败情况和聚合后的 session replay 指标。
- task graph 会按状态统计，并额外列出当前 ready task，方便看到编排是否卡住。
- background run 会按状态统计，并展示最近几条运行记录；tool output store 会展示总量和被截断的结果数量。
- memory candidate 和 skill patch eval 也会出现在同一个面板里，让“经验沉淀”不再藏在单独子命令后面。

CLI 示例：

```bash
python -m mini_claw dashboard
python -m mini_claw dashboard --session 1
python -m mini_claw dashboard --watch --interval 2
python -m mini_claw dashboard --watch --changes-only --interval 2
python -m mini_claw dashboard --json
python -m mini_claw dashboard --json --output-file .mini_claw/dashboard.json
python -m mini_claw dashboard --watch --json --output-file .mini_claw/dashboard.ndjson
python -m mini_claw export dashboard --output-file .mini_claw/dashboard_export.json
python -m mini_claw export doctor --output-file .mini_claw/doctor_export.json
python -m mini_claw export team-board --output-file .mini_claw/team_board_export.json
python -m mini_claw export bundle --output-file .mini_claw/runtime_bundle.json
python -m mini_claw export bundle --session 1 --output-file .mini_claw/session_bundle.json
python -m mini_claw export bundle --watch --iterations 2 --interval 0 --output-file .mini_claw/runtime_bundle.ndjson
python -m mini_claw export bundle --watch --changes-only --iterations 2 --interval 0
python -m mini_claw viewer --input-file .mini_claw/runtime_bundle.ndjson --output-file .mini_claw/runtime_viewer.html
python -m mini_claw viewer --from-workspace --source-target bundle --output-file .mini_claw/runtime_viewer.html
python -m mini_claw viewer --from-workspace --source-target team-board --output-file .mini_claw/team_board_viewer.html
python -m mini_claw viewer --from-workspace --source-target bundle --refresh-seconds 2 --output-file .mini_claw/runtime_viewer_live.html
python -m mini_claw viewer --from-workspace --source-target bundle --demo-mode --output-file .mini_claw/runtime_viewer_demo.html
python -m mini_claw viewer --from-workspace --source-target bundle --demo-mode --demo-focus team --output-file .mini_claw/runtime_viewer_demo_team.html
python -m mini_claw viewer --from-workspace --source-target bundle --demo-mode --demo-focus runtime --demo-script short --output-file .mini_claw/runtime_viewer_demo_short.html
python -m mini_claw viewer --from-workspace --source-target bundle --demo-mode --demo-language zh --output-file .mini_claw/runtime_viewer_demo_zh.html
python -m mini_claw home
python -m mini_claw home --style tui
python -m mini_claw home --style tui --preset compact
python -m mini_claw home --style tui --preset ops
python -m mini_claw home --style tui --preset interview
python -m mini_claw home --style tui --preset interview --demo-mode --demo-script short
python -m mini_claw home --style tui --preset interview --demo-mode --demo-language zh --demo-script short
python -m mini_claw home --style tui --preset interview --demo-mode --demo-focus runtime --demo-script short
python -m mini_claw home --style tui --focus team --width 96
python -m mini_claw home --style tui --collapse team,background
python -m mini_claw home --style tui --preset compact --watch --interval 2
python -m mini_claw home --style tui --preset compact --watch-layout full --watch --interval 2
python -m mini_claw home --style tui --preset interview --watch --interval 2
python -m mini_claw home --style tui --watch --changes-only --interval 2
python -m mini_claw home --watch --interval 2
python -m mini_claw home --json --output-file .mini_claw/home.json
python -m mini_claw team board
python -m mini_claw team board --watch --interval 2
python -m mini_claw team board --watch --changes-only --interval 2
python -m mini_claw team board --json --output-file .mini_claw/team_board.json
python -m mini_claw team board --watch --json --output-file .mini_claw/team_board.ndjson
python -m mini_claw team status
python -m mini_claw team run --limit 1
python -m mini_claw doctor
python -m mini_claw doctor --json
python -m mini_claw doctor --watch --interval 2
python -m mini_claw doctor --watch --changes-only --interval 2
python -m mini_claw doctor --summary-only
python -m mini_claw doctor --fail-on trace_missing,session_missing
python -m mini_claw doctor --ignore session_missing
python -m mini_claw doctor --severity-at-least warn
python -m mini_claw doctor --category trace,sessions --json
python -m mini_claw doctor --sort-by severity --json
python -m mini_claw doctor --json --output-file .mini_claw/doctor.json
python -m mini_claw doctor --watch --json --output-file .mini_claw/doctor.ndjson
python -m mini_claw session replay 1 --json
```

`home --style tui` now also supports `--demo-mode --demo-language bilingual|en|zh --demo-focus auto|team|runtime|sessions --demo-script short|full`, which adds a terminal talk-track panel above the board for interview-style walkthroughs.

`dashboard` 现在还支持 `--watch`，可以周期性刷新整屏；配合 `--session` 可以盯某个 session，配合 `--iterations` 可以做有界演示或脚本化测试。从第二次刷新开始，watch 模式还会在面板顶部输出 “Changes Since Last Refresh”，把 trace、task、background、tool output、memory 这些状态变化先标出来，再给完整快照。再进一步，`--changes-only` 会在首屏之后隐藏完整面板，只保留 delta，适合盯长时间运行的 session 或后台任务。现在 `dashboard` 和 `session show/replay/turn-show` 还支持 `--json`，可以直接喂脚本、前端或外部编排器；其中 `dashboard --watch --json` 会按刷新轮次输出一行一个 JSON 对象，而 `dashboard --json` 默认会输出紧凑版的 tool output 摘要，不会把整段 stdout/stderr 原文塞进总览对象里。和 `doctor` 一样，`dashboard` 现在也支持 `--output-file`，单次 JSON 会直接写文件，watch JSON 会连续追加成 NDJSON。

如果上层系统不想关心 `dashboard` / `doctor` 各自的参数细节，现在还可以直接走统一的 `export` 入口：`export dashboard` 导出一份 runtime 总览，`export doctor` 导出一份 runtime 健康诊断，`export team-board` 导出一份 team control surface 快照，`export bundle` 则把 `dashboard + doctor + team_board + 可选的 session replay` 打成一个单次 JSON 包。加上 `--watch` 之后，它会按刷新轮次持续输出 NDJSON，并直接带上 `changes`、`changes_by_section` 和 `changes_by_section_delta`；如果再加 `--changes-only`，首轮之后就只保留变化元数据，不再重复整份 snapshot，更适合被外部脚本、前端或集成环境直接调用。

在这层结构化导出之上，现在还可以直接生成一个本地 HTML viewer。`viewer` 会读取导出的 JSON 或 NDJSON，把迭代切换、summary、changes、changes_by_section、delta 和完整 snapshot 收成一个单文件页面，双击就能打开，不需要额外前端工程或 dev server。现在它还支持 `--from-workspace`，可以直接从当前 workspace 渲染一份 `dashboard`、`doctor`、`team-board` 或 `bundle` 页面，不需要先手动落一份 export 文件；再配合 `--refresh-seconds`，还能生成一个带轻量自动刷新的页面，适合盯着现场演示或长时间运行的 workspace。进一步地，`--demo-mode` 会把第一屏压成更适合面试讲解的摘要版，把 runtime health、trace、失败工具调用、ready tasks、session 和 replay 这些高信号指标先顶出来，并附上一段更像讲稿的 talk track，方便你直接顺着页面往下讲；`--demo-language` 可以在 `bilingual`、`en`、`zh` 三种 talk track 语言里切换，`--demo-focus` 允许你显式指定第一屏偏向 `team` 还是 `runtime`，默认是 `auto`，而 `--demo-script` 则可以在 `short` 和 `full` 之间切换讲稿长度。这样你既可以用完整版完整走一遍系统，也可以在 60 到 90 秒里用短版先把主线讲清楚。这一层很适合面试演示，因为你可以先录一份 bundle，再把运行时状态、健康诊断和 replay 变化作为一个可翻页的本地面板展示出来；也可以在现场直接跑 `viewer --from-workspace --source-target team-board` 先展示 team control surface，再切到 `viewer --from-workspace --demo-mode --demo-focus runtime --demo-script short --demo-language zh` 展示更短的 runtime 页面。

如果更想直接在终端里开场，现在还有一个更薄的 `home` 入口。`home` 不会把所有细节一股脑铺开，而是直接从 `bundle` 和 `team_board` 里抽出第一屏最值得讲的 headline：team health、runtime health、trace、ready tasks、失败工具调用、background runs 和 latest session；然后往下接 team queue、runtime health、runtime counts 和 latest session。现在它除了默认的 plain 文本视图，还支持 `--style tui`，会把这些信息压成更紧凑的双列终端面板；再配合 `--focus team|runtime|sessions` 和 `--width`，可以控制第一屏优先讲哪条线以及终端布局宽度。新加的 `--collapse` 则允许你把 `team`、`runtime_health`、`runtime_counts`、`sessions`、`background`、`session_replay`、`changes` 这些 panel 收成摘要行，让第一屏更像真正的 control surface。再往前一步，`--preset compact|ops|interview` 把常用布局直接打包好了：`compact` 更适合小终端和日常巡检，`ops` 偏 runtime/health 监控，`interview` 则偏 team-first 的讲解顺序；如果你后面又手动给了 `--focus`、`--width` 或 `--collapse`，这些显式参数仍然会覆盖预设。现在这些预设还开始影响 watch 行为了：`compact` 在 `watch` 下默认会在第二轮开始切到 delta 视图，只保留概览和变化面板；`ops` 默认保留整屏刷新，更像 live monitor；`interview` 也保留整屏刷新，但会默认把 changes panel 收成折叠摘要，减少对主叙事的干扰。如果你想覆盖这些默认行为，可以显式加 `--watch-layout full|delta`，或者手动加 `--changes-only` 强制所有预设都走 delta。`watch` 模式下，这个 TUI 还会把变化直接收成 `Changes Since Last Refresh` 面板，并且在发生变化的子面板标题上打 `*`；如果再加 `--changes-only`，第二轮开始就只保留概览和变化面板，不再重复整屏首页。它也支持 `--json` 和 `--output-file`，所以既可以作为终端首页，也可以作为后续更完整 TUI 的稳定数据源。

另外，多角色编排这条线现在也补了一个更 user-facing 的 `team` 入口。`team board` 会把 team queue、runtime health、session 和 background runs 收成一屏，更适合做面试开场；现在它还支持 `--watch`、`--changes-only`、`--json` 和 `--output-file`，可以像 dashboard / doctor 一样持续刷新并把结果直接落成 JSON / NDJSON，把 team control surface 变成 live monitor 和稳定的数据出口。`team status` 会把 task graph 压成 ready / active / blocked 的状态摘要，适合先给面试官看“系统现在在哪”；`team run` 则直接用 planner -> coder -> tester -> integrator 这组角色语言来描述一次执行，把 ready tasks、handoff flow 和任务状态变化收成一屏更像产品的总结。底层仍然复用已有的 TaskGraph、task workspace、verification 和 merge 逻辑，所以这层不是另起炉灶，而是把已经做好的 runtime orchestration 翻译成更容易讲明白的产品接口。

在机器接口层面，`team board --watch --json` 现在除了顶层 `changes` 之外，也会带稳定的 `changes_by_section` 和 `changes_by_section_delta`，把增量拆成 `team_status`、`runtime_health`、`runtime_counts`、`latest_session` 和 `background_runs` 五个 section，并额外给出每个 section 的数值变化。这样上层如果要做终端 TUI、本地 viewer 或更薄的前端壳，就不需要自己再从文本差异里做二次拆分。

在此基础上，`doctor` 会直接复用同一份 dashboard snapshot，给出一份更适合面试演示、CI 或自动化脚本消费的 runtime 健康诊断。它会把 failed tool calls、failed background runs、blocked tasks、failed session turns、truncated tool outputs 和 pending memory candidates 归类成 `fail / warn / info` 三档，并且每条 finding 都带稳定的 `category` 字段，方便后续接前端或告警系统；JSON 结果里还会额外输出 `summary_by_category`，便于直接做分组卡片或告警聚合。默认只有 `fail` 会返回非零退出码，配合 `--strict-warnings` 则可以把 warning 也提升成失败。现在它也支持 `--watch` 和 `--json`，可以像 dashboard 一样持续刷新；`doctor --watch --json` 会按轮次输出一行一个 JSON 对象，并带上 `changes`、`summary_by_category_delta` 和 `exit_code`，很适合做轻量监控或 CI gate。再进一步，`--changes-only` 可以在 watch 模式里只显示增量，`--summary-only` 则把输出压成单行 summary，更适合 shell 脚本、CI log 或面试现场的快速展示；`--fail-on` 则允许你按 finding code 定义更细粒度的失败条件，比如把 `trace_missing`、`session_missing` 这类平时只是提示的信息，在 CI 或集成环境里提升成硬失败，而 `--ignore` 可以把已知噪音 finding 从输出和退出码计算里一起剔除。`--severity-at-least` 则允许你只保留 `warn` 或 `fail` 级别的结果，`--category` 则允许你只保留某几类问题，`--sort-by` 则允许你把 findings 按 `severity`、`category` 或 `code` 稳定排序，进一步压缩输出并保持展示顺序一致。现在 `--output-file` 还可以把单次 JSON 结果直接写入文件，或把 watch 模式下的 JSON 连续追加成 NDJSON，方便外部采集器直接消费。

这一版的重点不是做一个漂亮壳子，而是把 runtime 里已经存在的可观测信号收束成一屏，并进一步变成带 delta、可结构化导出的 live monitor。这样面试时可以先跑一个总览，再切到 watch 模式，甚至切到 `--changes-only` 或 `--json`，让面试官看到 session、task、background、trace、memory 不只是同一套系统，而且天然具备被上层产品或自动化系统消费的接口。

## 最新增强：后台命令与任务挂接

这轮补的是更偏“产品表层可用性”的能力，但实现上仍然沿用 runtime-first 的思路：

- 新增 `background start/list/show/wait`，把长时间运行的命令持久化到 `.mini_claw/background/`。
- 每个后台命令都会生成独立 `run_id`、stdout/stderr 日志文件和状态记录，可在后续 CLI 调用中继续查看。
- runner 在开始和结束时会写入 `background_run_started` / `background_run_finished` trace，保持和现有 replay / trace 体系一致。
- 如果通过 `--task-id` 启动后台命令，run id 会自动挂到 `TaskNode.background_run_ids`，并追加一条带时间戳的任务 note。
- `todo show` 可以直接看到任务对应的后台运行记录，避免“任务状态”和“长时间命令”分裂成两套信息源。

CLI 示例：

```bash
python -m mini_claw todo add "Run repo-wide verification" --task-id verify-all --verify "python -m unittest discover -s tests -q"
python -m mini_claw background start --task-id verify-all --label unittest --command "python -m unittest discover -s tests -q"
python -m mini_claw background list
python -m mini_claw background wait 1
python -m mini_claw todo show verify-all
```

这一版的重点不是做一个“能跑后台进程的小功能”，而是把后台执行结果也纳入任务编排、trace 和持久化审计里。这样面试时可以很清楚地讲：交互式 agent 负责推进决策，长耗时命令走后台通道，但两者仍然归到同一套 runtime 数据结构中。

## 最新增强：自动 Context Compact

这轮补的是长任务上下文治理：

- runtime 在步骤数超过阈值后，会自动把较早的步骤压成 `Working Summary`，只保留最近几步完整 `Execution Trace`。
- `Working Summary` 会记录 `compacted_steps`、工具分布、已修改文件和 older step highlights，优先保留“发生过什么”和“下一步需要记住什么”。
- 每次 compact 都会写 `context_compacted` trace 事件；Replay 新增 `context_compactions` 指标。
- 这是一层 deterministic compact，不依赖额外模型调用，优先解决长任务里 trace 无限制膨胀的问题。

这一版先不做模型主动触发 compact，也不做二次摘要树。目标是先把“自动压缩 + 上下文注入 + trace 可观测”这条链路补完整。

## 最新增强：Signal-aware Routing

这轮把模型路由从“按阶段切角色”推进成“吃 runtime 信号的路由”：

- `ModelRouter` 现在会综合 `pending_lookup`、`failure_count`、`compacted_steps` 和最近一次 context budget 信号做判断。
- 当存在 `pending lookup` 时，下一步优先走 `reviewer`，避免模型继续重复广义 shell inspection。
- 当新的 compact 刚发生、较早步骤已经进入 `Working Summary` 时，下一步会切到 `summarizer`，先消费压缩后的历史，再继续执行。
- `context_build` trace 现在会记录 `route_reason` 和 `route_signals`，后续可以直接复盘“这一步为什么选这个角色”。
- prompt 里也会显式注入 `Current role` 和 `Role guidance`，让 role 不只是 trace 标签。
- CLI 新增 `bench-routing`，可以直接对比 `basic` 和 `signal-aware` 两套策略在同一组离线 bench 上的 route reason 分布。

这一版仍然是规则驱动 router，不是 learned policy，也还没有把 offline eval 数据反哺回 routing policy。目标是先把 routing 和 runtime 状态真正打通。
