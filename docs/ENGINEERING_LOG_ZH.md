# Mini Claw-Coder 工程记录

这个文档用于持续记录项目实现过程、测试数据、优化过程和面试可讲细节。后续每次新增能力、改策略、跑评测，都要把关键证据补到这里，避免面试时只有结论没有过程。

## 记录原则

- 记录“为什么做”，不只记录“做了什么”。
- 每个重要模块都要写清楚问题、方案、取舍、测试和后续优化。
- 测试数据优先写可复现命令和结果。
- 没实现的能力明确标注为后续计划，不包装成已完成。

## 当前项目定位

Mini Claw-Coder 是一个面向代码任务的可验证 Coding Agent Runtime。

核心目标：

```text
Execution Interface + Context Compiler + Safety Guardrails + Task Orchestration + Runtime Observability + Eval & Knowledge Loop
```

项目不追求单纯堆工具，而是研究如何用稳定执行接口和完整运行时模块实现更可控的代码任务执行能力。

## Memory 系统设计

### 当前实现

当前 memory 是两层设计：

```text
.mini_claw/memory/project_memory.md
.mini_claw/memory/task_trace.jsonl
.mini_claw/memory/tool_outputs/<output_id>.json
```

`project_memory.md` 是可注入记忆：

- 存项目技术栈。
- 存常用测试命令。
- 存启动方式。
- 存用户偏好。
- 存项目约束。
- 会进入 ContextPacket，被模型直接使用。

`task_trace.jsonl` 是可回放记忆：

- 存 task_started。
- 存 context_build。
- 存 tool_call。
- 存 agent_step_failed。
- 存 task_finished。
- 不会全量注入模型。
- 用于 trace replay、eval、failure attribution 和系统调试。

`tool_outputs/<output_id>.json` 是可回查工具结果：

- 存工具原始输出。
- 存结果预览。
- 存截断状态和 lookup hint。
- 用于长输出回查和后续 agent 二次读取。

这个设计的核心取舍：

> 不是把所有历史都塞回 prompt，而是把“可执行时复用的项目知识”和“可分析时回放的行为轨迹”分开。

### 已实现优化

#### 1. Project Memory 预算感知召回

原始问题：

如果 `project_memory.md` 越来越长，直接全量注入会污染上下文，并挤占代码片段、trace 和任务约束的位置。

当前改进：

- 短记忆直接注入。
- 长记忆按 Markdown section 切分。
- 使用当前任务 query 做轻量关键词匹配。
- 优先保留相关 section 和文件头部说明。
- 在预算内返回相关记忆。
- 无结构长文本使用 head-tail 截断。

相关文件：

```text
mini_claw/memory/store.py
mini_claw/context/manager.py
tests/test_memory_store.py
```

设计原因：

- 不引入向量库，保持项目轻量。
- 先解决上下文污染问题。
- 让 memory 从“只会存”升级到“按任务召回”。

面试表述：

> 我没有一开始就上向量数据库，而是先实现了一个更容易解释和验证的 project memory retrieval。项目记忆按 Markdown section 组织，长记忆会根据当前任务做预算感知召回，只把相关 section 注入 ContextPacket。完整历史则留在 trace 里用于 replay 和 eval，避免污染模型上下文。

### 当前不足

- 还没有自动从成功任务中提取 project memory。
- 还没有 memory 写入审核机制，容易写入错误经验。
- 还没有 memory 置信度、来源和更新时间。
- 还没有长期记忆索引文件。
- 还没有基于失败归因自动生成 skill candidate。
- 还没有对 memory 命中率做量化评测。

### 后续优化方向

#### 1. 结构化 Project Memory

计划将 `project_memory.md` 规范成固定 section：

```text
## Stack
## Commands
## Constraints
## User Preferences
## Known Failures
## Verified Fixes
## Skill Candidates
```

每条记忆增加：

```text
source
confidence
updated_at
evidence
```

#### 2. Memory 写入策略

只有满足以下条件才写入长期 memory：

- 任务成功。
- verification 通过。
- trace 中有证据。
- 不是一次性临时信息。

高风险记忆需要人工确认：

- 用户偏好。
- 安全约束。
- 项目架构判断。
- 依赖或部署相关信息。

#### 3. Memory 评测指标

后续 eval 中增加：

```text
memory_injected_chars
memory_selected_sections
memory_hit_rate
context_budget_saved
success_rate_with_memory
success_rate_without_memory
```

目标是证明 memory 不只是“有”，而是能提升任务成功率或降低工具调用次数。

## 已实现能力记录

### 2026-04-19：项目骨架

实现内容：

- CLI 入口。
- Agent Loop。
- mock model client。
- OpenAI-compatible client。
- shell 工具。
- apply_patch 工具。
- Context Manager。
- Model Router。
- Memory Store。
- Skill Loader。
- ACP-like Handoff。
- JSONL Eval Runner。

验证命令：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw eval examples\eval_tasks.jsonl
```

当时测试结果：

```text
4 tests passed
mock agent run passed
sample eval passed
```

### 2026-04-19：可靠性增强 P1

实现内容：

- ContextPacket / ContextCompiler。
- 文件快照。
- sha256 预条件。
- Patch Transaction。
- rollback journal。
- RuntimeEvent schema。
- Failure Attribution。

核心价值：

- 上下文从拼接升级为结构化编译。
- 文件修改从普通写入升级为事务。
- 失败从日志升级为结构化原因。

验证命令：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw eval examples\eval_tasks.jsonl
```

当时测试结果：

```text
10 tests passed
mock agent run passed
sample eval passed
```

### 2026-04-19：可验证能力增强

实现内容：

- Patch diff summary。
- Patch verification binding。
- rollback_on_verification_failure。
- Trace Replay。

核心价值：

- patch journal 记录 before / after / diff / verification。
- 修改后可以绑定测试命令。
- trace 可以回放成结构化报告。

验证命令：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw replay
python -m mini_claw eval examples\eval_tasks.jsonl
```

当时测试结果：

```text
13 tests passed
mock agent run passed
trace replay passed
sample eval passed
```

### 2026-04-19：Memory 召回优化

实现内容：

- `project_memory.md` 读取支持 `query` 和 `max_chars`。
- 长 project memory 按 Markdown section 切分。
- 按当前任务关键词进行轻量相关性选择。
- 无结构长文本使用 head-tail 截断。
- ContextManager 按任务构造 project memory section。

相关测试：

```text
tests/test_memory_store.py
```

预期价值：

- 降低长期记忆对上下文的污染。
- 为后续 memory 命中率和上下文预算统计打基础。
- 面试时可以解释 memory retrieval 的设计取舍。

验证命令：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw replay
python -m mini_claw eval examples\eval_tasks.jsonl
```

当前测试结果：

```text
15 tests passed
mock agent run passed
trace replay passed
sample eval passed: total 1, passed 1, failed 0
```

## 当前测试数据

最新验证命令应包括：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw replay
python -m mini_claw eval examples\eval_tasks.jsonl
```

最新结果在每轮开发结束后更新。

截至 2026-04-19 当前最新结果：

```text
compileall passed
50 tests passed
mock agent run passed
trace replay passed
sample eval passed
runtime_smoke bench passed: total 5, passed 5, failed 0
file index command passed
skills list/match passed
memory candidates/promote/reject command passed
workspace create/list/diff command passed
workspace merge command passed
tool-output list/show command passed
tool_output_lookup bench passed
lookup_policy_smoke passed
tool-output show lookup plan passed
multi_hop_lookup_smoke passed
replay includes lookup_auto_focus_calls / lookup_refinement_calls
successful evidence lookup creates strategy candidate
```

### 2026-04-19：EvalBench 与 TaskGraph

实现内容：

- 新增离线 EvalBench。
- Bench case 支持 `setup_files`、`scripted_actions`、`verification_commands` 和 `expected_success`。
- 新增 `ScriptedModelClient`，用于无 API key 的 runtime 评测。
- Bench report 输出 success_rate、tool_calls、context_builds、failed_tool_calls、agent_step_failures、patch_transactions、failure_root_cause。
- 新增基础 TaskGraph / Todo。
- TaskNode 支持 task_id、objective、status、owner_role、dependencies、context_refs、verification_command、notes。
- CLI 新增 `bench` 和 `todo` 命令。

相关文件：

```text
mini_claw/evals/bench.py
mini_claw/llm/scripted.py
mini_claw/task_graph/graph.py
examples/bench/runtime_smoke.json
tests/test_bench.py
tests/test_task_graph.py
```

设计原因：

- 面试时不能只说“我们可评测”，要有可复现 benchmark 和指标。
- 离线 EvalBench 可以先验证 runtime、patch、verify、trace 和 failure attribution，不依赖 API key。
- TaskGraph 是后续多 Agent 协作、复杂任务拆解和 worktree 隔离的前置结构。

关键修正：

- 初版 scripted client 在 actions 用尽后自动返回成功 final，导致预期失败 case 被误判成功。
- 修正为 actions 用尽后返回 no action / no final，只有显式 final 才能成功。
- Failure Attribution 从“只看最后 observation”升级为“扫描最近 observation”，避免早期关键错误被后续错误覆盖。

验证命令：

```bash
python -m compileall mini_claw
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw todo list
```

当前 bench 结果：

```text
total: 2
passed: 2
failed: 0
success_rate: 100.00%
avg_tool_calls: 0.50
avg_context_builds: 2.50
patch_and_verify_smoke: PASS
failure_attribution_smoke: PASS
failure_root_cause: BAD_TOOL_USE
```

### 2026-04-19：FileIndex / 渐进式披露

实现内容：

- 新增 `mini_claw.context.file_index`。
- ContextPacket 注入 `File Index Preview`。
- CLI 新增 `index` 命令。
- 文件索引包含 path、size_bytes、language、symbols、preview、score。
- 默认忽略 `.git`、`.mini_claw`、`.venv`、`node_modules`、缓存目录等无关内容。
- Python 提取 class / def 符号。
- JS / TS 提取 class / function / const 符号。
- Markdown 提取标题。
- 根据当前任务 query 对文件进行轻量相关性打分。

相关文件：

```text
mini_claw/context/file_index.py
mini_claw/context/manager.py
tests/test_file_index.py
```

设计原因：

- 我们之前只有 workspace tree，信息密度低，也缺少符号和预览。
- FileIndex 让模型先看到候选文件、关键符号和少量预览，再通过 shell 读取完整文件，避免一开始污染上下文。
- 这让上下文披露从“一次性塞全量仓库”改成了“先预览、再按需深读”的两阶段流程。

CLI 示例：

```bash
python -m mini_claw index --query "memory file index" --limit 8
```

测试结果：

```text
20 tests passed
index command passed
bench runtime_smoke passed
mock agent run passed
```

面试表达：

> 我把仓库上下文披露分成两层：第一层是 FileIndex Preview，只包含路径、语言、符号和少量预览；第二层才是通过 shell 按需读取完整文件。这样模型不会在任务一开始就被大量无关代码淹没，同时 trace 里可以观察每次上下文构建到底披露了哪些信息。

### 2026-04-19：Skill metadata 契约

实现内容：

- `SKILL.md` 支持 front matter metadata。
- 新增 `SkillContract`。
- 支持字段：name、description、triggers、inputs、outputs、allowed_tools、forbidden_paths、verification。
- 旧版纯 Markdown skill 仍可加载。
- ContextManager 根据任务 query 选择最多 3 个相关 skill 注入上下文。
- CLI 新增 `skills list` 和 `skills match`。

相关文件：

```text
mini_claw/skills/loader.py
mini_claw/context/manager.py
examples/sample_skill/SKILL.md
tests/test_skill_loader.py
```

CLI 示例：

```bash
python -m mini_claw skills list --include-examples
python -m mini_claw skills match "inspect this repository" --include-examples
```

设计原因：

- 之前我们的 skill 只是 Markdown 片段，缺少触发条件和边界。
- Skill Contract 让 skill 从 prompt 片段升级为能力模块。
- 这样后续才能把工具权限、路径限制和验证要求接进 guardrail。

当前边界：

- 当前 allowed_tools / forbidden_paths 是声明式边界，会进入 ContextPacket 约束模型行为。
- 后续可以继续接入工具调用 guardrail，实现硬约束。

测试结果：

```text
22 tests passed
skills list passed
skills match passed
bench runtime_smoke passed
mock agent run passed
```

面试表达：

> Skill 不只是 prompt 片段，而是有触发条件、输入输出、工具边界和验证方式的能力模块。当前我先实现了声明式契约和相关性召回，后续可以把 allowed_tools 和 forbidden_paths 接到工具调用 guardrail，形成硬执行边界。

## 面试常见追问

### 1. 你们的 memory 和简单历史记录有什么区别？

不是保存聊天记录再全部塞给模型。我们把 memory 分成两类：`project_memory.md` 是可注入记忆，用于当前任务执行；`task_trace.jsonl` 是可回放记忆，用于调试、eval 和失败归因。这样既能复用项目知识，又不会让长历史污染上下文。

### 2. 为什么没有一开始用向量数据库？

这个项目的目标是轻量、可验证、可解释。早期 memory 的主要问题不是语义召回不够强，而是上下文污染和缺少写入策略。所以先用 Markdown section + budget-aware retrieval，保证行为可解释、测试简单、面试能讲清楚。后续如果项目记忆规模变大，再引入 embedding 或向量库。

### 3. 怎么证明 memory 有用？

后续会做 A/B eval：

```text
关闭 project memory
开启全量 project memory
开启预算感知 memory retrieval
```

比较：

```text
任务成功率
工具调用次数
上下文长度
失败归因分布
测试通过率
```

### 4. memory 写错怎么办？

后续会做 memory write policy：

- 只有 verification 通过的结论才能自动写入。
- 高风险记忆需要人工确认。
- 每条 memory 保留 source、confidence、evidence。
- 失败任务只写入 failure pattern，不写入未经验证的项目事实。

### 5. 这和 Skill 有什么关系？

Memory 存项目事实和运行轨迹，Skill 存可复用操作流程。比如“这个项目测试命令是 X”属于 memory；“遇到 pytest import error 时按哪些步骤排查”属于 skill。后续 Failure Attribution 可以生成 skill candidate，再通过 eval 验证是否值得固化。
## 当前优先级建议

最应该先做：

```text
1. EvalBench + 指标报告
2. TaskGraph / Todo
3. Memory 写入策略
4. 任务级隔离
5. Skill guardrail 硬约束
```

原因：

- EvalBench 能立刻支撑面试数据。
- TaskGraph、FileIndex 和 Skill metadata 已经补齐基础能力，下一步要增强 memory 写入、任务隔离和 skill guardrail。
- Skill guardrail 能把当前声明式契约升级成真正的工具调用硬约束。
- Memory 写入策略能让记忆系统更完整。
### 2026-04-19：Skill Guardrail 与候选记忆

实现内容：

- 新增 `mini_claw.agent.guardrails.SkillGuardrail`。
- Active skill 的 `allowed_tools` 会在工具执行前被校验。
- Active skill 的 `forbidden_paths` 会扫描工具参数，命中则阻止执行。
- 被阻止的调用会写入 `agent_step_failed`，reason 为 `skill_guardrail`。
- Failure Attribution 新增 `SKILL_GUARDRAIL_BLOCKED`。
- 新增 `MemoryCandidate`。
- 成功任务后生成 `memory_candidates.jsonl` 候选记忆。
- mock provider 不生成候选记忆，避免演示输出污染长期 memory。
- CLI 新增 `memory candidates`、`memory promote`、`memory reject`。

相关文件：

```text
mini_claw/agent/guardrails.py
mini_claw/agent/loop.py
mini_claw/memory/candidates.py
mini_claw/memory/store.py
tests/test_skill_guardrail.py
tests/test_memory_store.py
```

设计原因：

- Skill Contract 只进入 prompt 时，仍然依赖模型自觉遵守。
- Guardrail 把 `allowed_tools` / `forbidden_paths` 升级为工具执行前的硬约束。
- Memory 不应该自动把所有成功结论写入长期记忆，应先作为候选，带证据和置信度，后续再确认或评测。

当前边界：

- shell 命令中的 forbidden path 目前基于字符串扫描，后续可以升级为命令解析或沙箱策略。
- memory candidate 已支持 promote / reject，后续可增加 eval 验证后自动建议 promote。

测试结果：

```text
28 tests passed
runtime_smoke bench passed
memory candidates/promote/reject command passed
replay includes memory_candidate_created events
```

面试表达：

> 我把 Skill 从“提示词片段”推进到了 runtime guardrail。active skill 声明的 allowed_tools 和 forbidden_paths 会在工具执行前被校验，违规调用会被阻止并进入 trace。Memory 采用 candidate-first 策略，成功任务先生成带证据和置信度的候选记忆，经过 promote/reject 决策后才进入长期 project memory。

### 2026-04-19：任务级隔离工作区

实现内容：

- 新增 `mini_claw.task_graph.workspace.TaskWorkspaceManager`。
- 支持 `workspace_copy` 隔离模式，在 `.mini_claw/task_workspaces/<task_id>` 下创建任务级工作区副本。
- 创建时默认忽略 `.git`、`.mini_claw`、`.venv`、`node_modules`、缓存目录和构建产物，减少无关内容复制。
- 支持 `workspace diff <task_id>`，对任务工作区和主工作区做文本差异摘要。
- `TaskNode` 新增 `workspace_path` 字段。
- `workspace create <task_id>` 会自动把隔离工作区路径挂接到 `TaskGraph`，让任务编排和任务隔离打通。
- `todo list` 新增 `workspace=` 输出，`workspace list` 新增 `linked=yes/no` 状态。

相关文件：

```text
mini_claw/task_graph/workspace.py
mini_claw/task_graph/graph.py
mini_claw/cli.py
tests/test_task_workspace.py
tests/test_task_graph.py
tests/test_cli_workspace.py
```

设计原因：

- 任务级隔离是复杂任务编排里很重要的一环，也是在面试里很容易被追问的一环。
- 我这一版先不直接依赖 `git worktree`，而是先证明三个东西已经跑通：任务图、任务隔离目录、主工作区差异比较。
- 这样做的好处是实现轻量、测试简单、对本地环境依赖更少，也更容易讲清楚为什么需要 integrator。

为什么不是一上来就做 git worktree：

- 当前项目重点是 Runtime 数据结构和执行链路，不是 Git plumbing。
- `workspace_copy` 已经足够支撑“多任务独立修改 + 差异回看 + 后续统一合并”的工程叙事。
- 等 integrator merge flow、patch provenance 和冲突策略补齐后，再换成 `git worktree` 的收益会更明确。

当前边界：

- 当前是“副本隔离”，不是“原生 Git 分支隔离”。
- `workspace diff` 目前只对常见文本文件做摘要，不处理二进制文件。
- 还没有多候选 patch 仲裁和 integrator 角色编排。
- 如果任务 id 包含特殊字符，CLI 会在工作区目录名中做安全化处理，建议实际使用稳定的短 task id。

验证命令：

```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw workspace create fileindex
python -m mini_claw todo list
python -m mini_claw workspace list
python -m mini_claw workspace diff fileindex
```

测试结果：

```text
35 tests passed
runtime_smoke bench passed: total 2, passed 2, failed 0
workspace create fileindex passed
todo list shows workspace attachment
workspace list shows linked=yes
workspace diff fileindex passed: (no changes)
```

面试表达：

> 我把“任务编排”和“任务隔离”真正接到了一起。每个 TaskNode 现在都可以挂一个独立工作区，agent 可以在隔离目录里改代码，再通过 diff 回看和后续 integrator 合并到主工作区。当前我先用 workspace_copy 做基础版，因为它更轻量、可测试、可解释，下一步再升级到 git worktree 和 integrator merge flow。

### 2026-04-19：任务工作区安全合并

实现内容：

- `workspace create` 现在会额外记录 base manifest，保存创建任务工作区时主工作区的文本文件快照摘要。
- 新增 `TaskWorkspaceManager.merge(...)`。
- `workspace merge <task_id>` 会比较三份状态：base manifest、当前主工作区、当前任务工作区。
- 如果主工作区和任务工作区都改了同一个文件，会直接返回 conflict，阻止覆盖。
- 无冲突时，merge 会复用 `PatchTransaction` 把任务工作区改动事务化写回主工作区。
- merge 支持 verification commands，并且默认会接入 `TaskGraph` 上的 `verification_command`。
- merge 成功后会刷新 manifest，让后续 merge 只关注新的任务侧改动。

相关文件：

```text
mini_claw/task_graph/workspace.py
mini_claw/cli.py
tests/test_task_workspace.py
tests/test_cli_workspace.py
```

设计原因：

- 如果任务隔离最后只是“把目录里的文件 copy 回来”，那其实没有真正解决代码智能体的编辑安全问题。
- 我希望把任务工作区最终也收敛到和 `apply_patch` 一样的安全语义：有前置条件、有冲突检测、有 journal、有 verification。
- 这样隔离执行不是一个旁路功能，而是接入同一套 runtime 可观测性和可靠性框架。

为什么用 manifest：

- merge 判断冲突时，不应该只比较“主工作区 vs 任务工作区”。
- 更关键的是知道任务工作区创建时主工作区长什么样，也就是 base。
- 所以我在 create 阶段记录 base manifest，merge 阶段做三方比较：

```text
base manifest
current main workspace
current task workspace
```

- 只有当“任务变了、主工作区没变”时，才允许自动 merge。

当前边界：

- 当前 manifest 只覆盖常见文本文件，不覆盖二进制文件。
- 冲突粒度目前是文件级，不是 hunk 级三方合并。
- merge 目前还是单任务单入口，尚未抽象成真正的 integrator role。
- 当前没有 patch provenance 追踪，后续可以补“这个 merge 来自哪个 task / 哪次候选 patch”。

验证命令：

```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw workspace create fileindex
python -m mini_claw workspace merge fileindex --dry-run
```

测试结果：

```text
35 tests passed
runtime_smoke bench passed: total 2, passed 2, failed 0
workspace merge fileindex --dry-run passed: no pending text changes
task workspace merge unit tests passed
CLI merge uses task verification command
```

面试表达：

> 我没有把任务隔离做成一个简单目录副本，而是补了一个安全 merge flow。任务工作区创建时会记录 base manifest，merge 时会做 base / main / task 三方比较。只有主工作区没有漂移时，才会把任务改动通过事务化 patch 合回去，并自动绑定验证命令。这样任务隔离最终还是落回同一套可审计、可回滚、可验证的编辑机制。

### 2026-04-19：统一 Tool Output Protocol

实现内容：

- `ToolResult` 仍然返回工具原始结果，但 Agent Loop 不再直接把原始输出塞进 `step.observation`。
- 新增 `ToolOutputHandle`，统一描述 `output_id`、字符数、截断状态和 lookup hint。
- `MemoryStore.store_tool_result(...)` 会把工具原始结果存到 `.mini_claw/memory/tool_outputs/<output_id>.json`。
- Agent 当前 observation 只保留结果预览、`output_id` 和回查提示。
- CLI 新增 `tool-output list` / `tool-output show`。
- `tool_call` trace payload 新增 `output_handle`。
- Trace Replay 新增 `truncated_tool_outputs` 统计。

相关文件：

```text
mini_claw/tools/base.py
mini_claw/tools/shell.py
mini_claw/agent/loop.py
mini_claw/memory/store.py
mini_claw/cli.py
mini_claw/tracing/replay.py
tests/test_memory_store.py
tests/test_cli_tool_output.py
tests/test_agent_tool_output.py
tests/test_trace_replay.py
```

设计原因：

- 长输出、截断和结果回查正好对应 Coding Agent 很现实的上下文污染问题。
- 之前 `shell` 直接把长输出截断后塞进 observation，虽然能跑，但模型看不到统一结构，trace 里也缺少结果引用。
- 我希望工具输出遵守和 patch / trace 一样的思路：当前上下文里放摘要，完整信息放存储，运行时里放引用。

为什么要把 observation 和原始结果分开：

- 模型当前步骤通常不需要完整 stdout，只需要知道工具是否成功、输出大概说了什么、如果需要去哪里查全文。
- 如果把长输出直接塞回 observation，很容易挤掉任务约束、文件预览和近期推理痕迹。
- 所以现在 observation 只保留：

```text
tool
ok
output_id
chars
truncated
lookup_hint
preview
```

- 真正的原始结果则进入 tool output store。

当前边界：

- 当前已经有 agent 可调用的 `tool_output_lookup`，并补上了基础 `lookup policy`，可以在截断结果后阻断重复的 shell inspection。
- shell 结果仍然是一次性捕获，不是流式分块存储。
- 当前只做文本结果存档，不处理二进制 artifact。
- `tool-output show` 展示的是持久化后的结果；如果原始输出大到超过 store budget，仍会被标记 `store_truncated=True`。

验证命令：

```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw run "inspect this repository"
python -m mini_claw tool-output list --limit 5
python -m mini_claw tool-output show 1
python -m mini_claw replay
```

测试结果：

```text
42 tests passed
mock agent run passed
tool-output list passed
tool-output show 1 passed
replay includes truncated_tool_outputs metric
tool_output_lookup agent test passed
```

面试表达：

> 我把工具结果做成了统一 output protocol。工具原始结果不会直接塞回 observation，而是先存到 tool output store，再把 `output_id`、字符数、截断状态和预览注入上下文。这样长输出不会污染当前推理，但需要时又能精确回查。我还把这个引用写进 trace，所以 replay 和 eval 可以统计到底有多少工具结果被截断。

### 2026-04-19：Agent 内部结果回查

实现内容：

- 新增 `mini_claw.tools.tool_output_lookup.ToolOutputLookupTool`。
- Agent 现在可以直接通过 `tool_output_lookup` 读取先前工具结果，而不需要通过 shell 调 CLI。
- `ref` 支持 `output_id`、数字索引、`latest` 和 `latest_truncated`。
- 支持 `query`、`line_start`、`line_end` 和 `max_chars`，用于只取需要的结果片段。
- `SYSTEM_PROMPT` 已加入回查工具说明，并提示在 observation 显示截断时优先走 lookup。
- `build_agent`、`eval runner` 和 `EvalBench` 都已接入该工具。

相关文件：

```text
mini_claw/tools/tool_output_lookup.py
mini_claw/agent/prompts.py
mini_claw/cli.py
mini_claw/evals/runner.py
mini_claw/evals/bench.py
tests/test_tool_output_lookup.py
tests/test_agent_tool_output.py
examples/bench/runtime_smoke.json
```

设计原因：

- 如果结果回查只存在于 CLI，对用户有用，但对 agent 自己并不是真正的能力。
- 我希望把 lookup 从“人工调试入口”推进到“runtime 内部可调用工具”。
- 这样 agent 在看到长输出被截断时，可以不重跑外部命令，而是针对已有结果做二次读取。

为什么不让 agent 直接再跑一次 shell：

- 重跑命令可能有副作用，也可能因为环境变化得到不一致结果。
- 对于长日志、构建输出、搜索结果这类内容，很多时候真正需要的是“回到已有结果里找关键片段”。
- 所以 `tool_output_lookup` 本质上是一个只读 introspection tool，它读取的是 runtime 已经持久化的结果，不是外部环境。

当前边界：

- 当前 lookup 粒度是字符窗口和行范围，还没有做到结构化列、JSON path 或语义搜索。
- `latest_truncated` 是方便用法，但复杂任务里更稳定的方式仍然是显式使用 `output_id`。
- 还没有基于 trace 自动学习“什么情况下应该触发 lookup”的策略。

验证命令：

```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw run "inspect this repository"
python -m mini_claw tool-output list --limit 5
```

测试结果：

```text
42 tests passed
runtime_smoke bench passed: total 3, passed 3, failed 0
tool_output_lookup_smoke passed
agent can lookup truncated tool output
CLI tool-output list/show still passed
```

面试表达：

> 一开始我只有结果存档和 CLI 回查，但那还不算 agent 能力。后面我补了一个只读的 `tool_output_lookup`，让 agent 可以基于 `output_id`、`latest` 或 `latest_truncated` 直接回看之前的工具结果，还能按 query 或行范围只取需要的片段。这样它不需要重跑外部命令，就能在已有证据上继续推理。

### 2026-04-19：自动结果回查策略

实现内容：

- 新增 `mini_claw.agent.tool_output_policy.ToolOutputLookupPolicy`。
- 在 `TaskState` 中加入 `pending_lookup`，把“刚产生的截断结果”变成可被 runtime 跟踪的结构化状态。
- 当 shell 结果被截断时，runtime 会挂起 `pending lookup`；如果模型下一步重复发起 read-only shell inspection，loop 会阻断这次调用，并返回带 `output_id` 和 lookup hint 的明确指令。
- 成功执行 `tool_output_lookup` 后会自动清空对应 `pending lookup`，避免长期残留约束。
- trace 新增 `lookup_policy_blocked` 事件，Replay 新增 `lookup_policy_blocks` 指标。
- `runtime_smoke.json` 新增 `lookup_policy_smoke`，验证“先被策略拦下，再通过 lookup 继续完成任务”的完整链路。

相关文件：
```text
mini_claw/agent/tool_output_policy.py
mini_claw/agent/state.py
mini_claw/agent/loop.py
mini_claw/agent/prompts.py
mini_claw/reliability/failure.py
mini_claw/tracing/replay.py
tests/test_agent_tool_output.py
tests/test_trace_replay.py
examples/bench/runtime_smoke.json
```

设计取舍：

- 我没有把这件事只放在 prompt 里，因为“看到截断后应该回查”本质上是 runtime policy，不应该完全依赖模型自己记住。
- 这一版先拦“重复的 shell inspection”，没有直接阻断 `apply_patch` 或测试命令，目的是先把误伤面收窄，保证策略足够容易解释。
- 当前 policy 还是规则驱动的，还不会自动生成最佳 query，也不会把多次 lookup 组织成更复杂的 evidence plan。

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw run "inspect this repository"
```

测试结果：
```text
43 tests passed
runtime_smoke bench passed: total 4, passed 4, failed 0
lookup_policy_smoke passed
lookup_policy_blocked trace event recorded
replay summary includes lookup_policy_blocks
mock agent run still passed
```

面试表达：
> 我后来发现，只做结果存档和 lookup tool 还不够，因为模型还是可能在看到截断提示后继续重复跑 shell。于是我又补了一层 runtime policy：当 shell 输出被截断后，系统会挂起一个 pending lookup，如果下一步还是重复做读型 shell inspection，就直接拦下来，并给出明确的 `output_id` 和 lookup hint。这样“结果回查”就从一个可选能力，变成了一个可执行的运行时约束。

### 2026-04-19：Auto Focus 回查计划

实现内容：

- 新增 `mini_claw.memory.lookup_plan`，在 tool output 持久化阶段为每条结果生成 `lookup_plan`。
- `lookup_plan` 会抽取高信号 token、错误行、quoted value、路径片段和 task overlap，形成可序列化的 query / line range / reason 列表。
- `ToolOutputHandle` 新增 `lookup_queries`，observation 会直接把建议 query 注入给模型。
- `tool_output_lookup` 新增 `focus='auto'`，可以直接消费已存档的 `lookup_plan`，无需模型自己拼 query。
- `tool-output show` 新增 `lookup_plan` 展示，方便人工 review 和面试时演示。
- `lookup_policy_smoke` 已经切到 `focus='auto'` 路径，说明从 policy block 到 auto lookup 的闭环已经打通。

相关文件：
```text
mini_claw/memory/lookup_plan.py
mini_claw/memory/store.py
mini_claw/tools/base.py
mini_claw/tools/tool_output_lookup.py
mini_claw/agent/prompts.py
mini_claw/cli.py
tests/test_memory_store.py
tests/test_tool_output_lookup.py
tests/test_agent_tool_output.py
tests/test_cli_tool_output.py
examples/bench/runtime_smoke.json
```

设计取舍：

- 这版没有做复杂的 embedding retrieval，而是先用规则型 planner 提取错误词、token、路径和任务相关词，优点是便于解释、容易测试、适合面试讲清楚。
- `focus='auto'` 不是替代显式 query，而是给 agent 一个低摩擦默认路径；需要精细控制时仍然可以显式传 `query` 或行范围。
- planner 目前更偏文本型输出，不适合二进制 artifact；现在已经支持基于 `intent` 和 `exclude_queries` 的轻量多跳 refinement，但还没有更强的学习型 query optimizer。

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw tool-output show 1
python -m mini_claw run "inspect this repository"
```

测试结果：
```text
50 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
lookup_policy_smoke passed with focus=auto
tool_output_lookup auto focus test passed
tool-output show lookup plan passed
mock agent run still passed
```

面试表达：
> 我后面又补了一层 auto focus 机制。不是只告诉模型“你应该回查”，而是系统会在结果持久化时提前抽一份 lookup plan，把高信号 token、错误行和路径片段结构化下来。这样 agent 真要回查的时候，可以直接用 `tool_output_lookup(ref='latest_truncated', focus='auto')`，不用每次都靠模型自己想 query。

### 2026-04-19：Intent-aware 多跳证据规划

实现内容：

- `lookup_plan` 里的 hint 现在带 `kind`，例如 `error_token`、`traceback`、`path`、`symbol`、`task_term`。
- 新增 `select_lookup_hint(...)`，支持基于 `intent`、`exclude_queries` 和 `hint_index` 从同一份 plan 中继续挑选下一条证据。
- `tool_output_lookup` 新增 intent-aware auto focus，支持 `intent='error' | 'path' | 'symbol' | 'task'`，并把 `hint_kind`、`hint_index`、`remaining_hints` 写回结果 metadata。
- Replay 新增 `lookup_auto_focus_calls` 和 `lookup_refinement_calls` 指标，用来区分“用了 auto focus”和“真的做了 refine”。
- 新增 `multi_hop_lookup_smoke`，验证 agent 先读 path clue，再 refine 到 import error clue 的完整链路。

相关文件：
```text
mini_claw/memory/lookup_plan.py
mini_claw/tools/tool_output_lookup.py
mini_claw/tracing/replay.py
mini_claw/agent/prompts.py
mini_claw/agent/tool_output_policy.py
mini_claw/cli.py
tests/test_tool_output_lookup.py
tests/test_agent_tool_output.py
tests/test_trace_replay.py
examples/bench/runtime_smoke.json
```

设计取舍：

- 这一版仍然是规则驱动 planner，不依赖向量库或额外模型调用，优点是稳定、可解释、容易离线评测。
- refine 逻辑刻意做成显式参数，而不是偷偷在 runtime 里自动跳第二条 hint，这样 trace 更清楚，也便于面试讲“系统做了什么”和“模型自己决定了什么”。
- 当前还没有做跨多次 lookup 的学习式 query 改写，但已经把 evidence planner 的使用结果反馈回 `task_finished.evidence_summary` 和 `evidence_lookup_strategy` memory candidate。

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw replay
```

测试结果：
```text
50 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
multi_hop_lookup_smoke passed
lookup_refinement_calls metric added
intent-aware auto focus tests passed
mock agent run still passed
```

面试表达：
> 我后来发现，只做 auto focus 还不够，因为复杂输出里常常同时有路径线索、错误线索和符号线索。所以我又把它做成一个轻量 evidence planner：先把长输出拆成 typed hints，再让 agent 用 `intent` 和 `exclude_queries` 去做第二跳、第三跳的证据细化。这样它不只是“会回查”，而是开始具备“怎么继续找下一条证据”的能力。

### 2026-04-19：Evidence Summary 反馈

实现内容：

- 新增 `mini_claw.agent.evidence`，把成功的 `tool_output_lookup` 结果抽象成 `EvidenceSelection`。
- `AgentLoop` 在每次成功 lookup 后写入 `evidence_selected` trace 事件，并在任务结束时汇总 `evidence_summary`。
- `build_success_memory_candidate(...)` 现在会附带 evidence lookups / refinements / queries。
- 新增 `build_evidence_strategy_candidate(...)`，当任务成功且实际使用了 evidence planner 时，额外生成 `evidence_lookup_strategy` memory candidate。
- Replay 新增 `evidence_selected_events`、`tasks_with_evidence_summary` 和 `distinct_evidence_queries`，用于观察 evidence planner 是否真正沉淀成任务级信号。

相关文件：
```text
mini_claw/agent/evidence.py
mini_claw/agent/state.py
mini_claw/agent/loop.py
mini_claw/memory/candidates.py
mini_claw/tracing/replay.py
tests/test_agent_tool_output.py
tests/test_trace_replay.py
```

设计取舍：

- 这版先做 candidate-first，不直接把 evidence pattern 写入长期 project memory，避免一次成功任务的局部策略过早污染长期记忆。
- 我保留了独立的 `evidence_lookup_strategy` candidate，而不是只改原来的 success candidate，目的是把“任务完成结果”和“证据搜索策略”区分开。
- 当前 evidence summary 还是任务级摘要，没有进一步反馈到 routing policy 或 skill patch 生成。

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
```

测试结果：
```text
50 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
successful evidence lookup creates strategy candidate
replay includes evidence_selected_events / tasks_with_evidence_summary / distinct_evidence_queries
mock agent run still passed
```

面试表达：
> 之前 evidence planner 只停在单次 lookup tool 的层面，能看出 agent 查了什么，但还没有沉淀成可复用经验。后面我又补了一层 evidence summary 反馈：每次成功 lookup 都会记成结构化 evidence record，任务结束时汇总成 `evidence_summary`，如果这次任务真的依赖了 evidence planner，还会额外生成一个 `evidence_lookup_strategy` memory candidate。这样系统不只是会找证据，还能把这次“证据是怎么找到的”沉淀下来。

## 2026-04-19：Evidence Strategy 检索回流

目标：把已经 promote 的 `evidence_lookup_strategy` 从“候选记忆”推进成“后续任务可直接复用的运行时策略信号”。

这轮实现：
- `MemoryStore.read_memory_candidates(...)` 增加 `kind_filter`、`status_filter`、`query` 和 `limit`，允许按类型、状态和任务 query 做轻量筛选。
- 新增 `MemoryStore.read_evidence_strategies(query, limit)`，只返回已经 promoted 的 `evidence_lookup_strategy`。
- promote `evidence_lookup_strategy` 时不再写入 `project_memory.md`；这类内容保持独立，避免把一次性的证据搜索路径混入长期事实记忆。
- `ContextManager.build_packet(...)` 新增 `Evidence Strategies` section，会按当前 task query 检索最相关的 promoted strategy，并与 `Project Memory` 分开注入 `ContextPacket`。

关键取舍：
- `project_memory.md` 继续承载稳定事实和项目约束；evidence strategy 本质上是“如何找证据”的操作经验，不适合和长期事实混写。
- 我没有在这一步把 evidence strategy 直接并入 routing policy，而是先让它进入上下文，原因是这样更容易验证，也更适合在面试里讲清楚 retrieval feedback 的链路。
- 这里仍然采用轻量字符串召回，而不是先上向量索引；目标是先把 candidate -> promote -> retrieval -> context injection 这条链路做闭环。

新增测试：
- `tests/test_memory_store.py`
- `tests/test_context_manager.py`

验证命令：
```bash
python -m unittest tests.test_memory_store -q
python -m unittest tests.test_context_manager -q
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
```

测试结果：
```text
tests.test_memory_store passed
tests.test_context_manager passed
52 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
```

面试表达：
> 我把 memory 继续分层了。`project_memory.md` 只放稳定事实，`evidence_lookup_strategy` 这类运行时策略记忆即使 promote 了，也不会直接写进长期项目记忆，而是作为独立策略记忆存放。后续任务构造 `ContextPacket` 时，会按当前 task query 检索最相关的 promoted strategy，注入 `Evidence Strategies` section。这样系统复用的是“怎么查证据”的经验，而不是把一次性的搜索路径永久污染项目事实。

## 2026-04-19：Candidate-first Skill Patch Suggestions

目标：把 evidence planner 的成功经验继续反馈回 skill 系统，但保持人工审核边界，不让 agent 直接重写 `SKILL.md`。

这轮实现：
- 新增 `mini_claw/skills/evolution.py`，提供 `build_skill_patch_candidate(...)`。
- 当任务成功、实际使用了 evidence lookup、并且当前任务命中了相关 skill 时，`AgentLoop` 会额外生成 `skill_patch_candidate`。
- candidate 内容会带 `target_skill`、`skill_path`、evidence queries / intents / hint kinds、建议补充的 triggers、verification，以及显式的 instruction patch。
- `skill_patch_candidate` 即使被 promote，也不会写入 `project_memory.md`；这类内容和 `evidence_lookup_strategy` 一样，保持独立，避免把运行时演进建议污染长期项目事实记忆。
- runtime trace 新增 `skill_patch_candidate_suggested` 事件，Replay 新增 `skill_patch_candidates` 指标。
- `memory candidates` CLI 新增 `--kind`、`--status`、`--query` 和 `--limit`，便于单独查看 skill patch 建议。

关键取舍：
- 我没有让 agent 直接改 skill 文件，而是坚持 candidate-first。因为 skill 属于行为边界和工程约束，自动落盘风险比普通 memory 更高。
- 这版 patch candidate 只对“相关 skill 已存在但指导缺失”的场景生成，不在这一步直接生成全新的 skill 文件，避免自进化范围扩得太快。
- skill patch 的信号来自成功任务中的 `evidence_summary`，而不是失败归因；这样先把“成功经验沉淀”链路跑通，后续再接失败驱动 patch 验证。

新增测试：
- `tests/test_agent_tool_output.py`
- `tests/test_memory_store.py`
- `tests/test_cli_memory.py`
- `tests/test_trace_replay.py`

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
```

测试结果：
```text
55 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
skill patch candidate suggestion passed
memory candidate CLI filters passed
replay includes skill_patch_candidates
```

面试表达：
> 我把“自进化”做成了 candidate-first 的 skill patch suggestion。系统不会直接改自己的 `SKILL.md`，而是在成功任务结束后，根据 evidence summary 和相关 skill 命中情况，生成一个 `skill_patch_candidate`，里面写清楚目标 skill、缺失的 lookup 指导、建议补充的 triggers / verification 和 instruction patch。这样既体现了 agent 能从成功经验里长出新规则，又把最终落盘权保留给人工审核或后续 eval。

## 2026-04-19：自动 Context Compact

目标：补上长任务里的自动上下文压缩链路，让系统不只是“能裁剪 section”，还会在运行时把更早的步骤结构化压缩成可注入摘要。

这轮实现：
- 新增 `mini_claw/agent/compaction.py`，提供 `refresh_compact_summary(...)`。
- `TaskState` 新增 `compact_summary`、`compacted_steps` 和 `compaction_count`。
- `AgentLoop` 在每次记录 step 后，会检查是否需要 compact；如果触发，会写入 `context_compacted` trace 事件。
- `ContextManager.build_packet(...)` 新增 `Working Summary` section；一旦有 compact summary，较早步骤会进入摘要，`Execution Trace` 只保留最近几步完整记录。
- `Replay` 新增 `context_compactions` 指标，用于观察一次运行里压缩发生了多少次。

关键取舍：
- 这版 compact 是 deterministic 的，不依赖额外模型调用。先解决“长任务 trace 失控膨胀”的基础问题，再考虑模型主动触发 compact 或分层摘要树。
- compact 只压较早步骤，最近几步仍保留完整 `Execution Trace`，避免把正在进行的推理上下文压得过早。
- 我没有引入新的 compact tool，而是把 compact 作为 runtime 内部机制处理，保持底层执行接口稳定。

新增测试：
- `tests/test_compaction.py`
- `tests/test_context_manager.py`
- `tests/test_agent_compaction.py`
- `tests/test_trace_replay.py`

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
```

测试结果：
```text
58 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
context compact summary passed
agent loop emits context_compacted
replay includes context_compactions
```

面试表达：
> 我没有把 compact 做成一个只在文档里存在的概念，而是直接补进了 runtime。步骤数超过阈值后，系统会自动把较早步骤压成 `Working Summary`，保留最近几步完整 trace，同时把 compact 事件写进 runtime trace。这样长任务里上下文不是一味累加，而是有一层可观测、可解释的自动压缩机制。

## 2026-04-19：Signal-aware Routing

目标：把模型路由从“静态按阶段切换”推进成“显式消费 runtime 状态信号”的路由。

这轮实现：
- `ModelRouter` 新增 `RouteDecision`，统一输出 `role`、`model`、`reason`、`signals` 和 `guidance`。
- 当 `pending_lookup` 存在时，router 会优先切到 `reviewer`，reason 为 `pending_tool_output_lookup`。
- 当新的 compact 已发生、而压缩后的历史还没被 summarizer 消费时，router 会切到 `summarizer`，reason 为 `new_context_compaction`。
- `AgentLoop` 现在会把 `Current role` 和 `Role guidance` 注入 prompt，并把 `route_reason` / `route_signals` 写入 `context_build` trace。
- `TaskState` 新增最近一次 context budget 和记忆的 compact 消费状态，给 router 提供最小但可解释的状态输入。

关键取舍：
- 这版 router 仍然是规则驱动，不依赖额外模型推断或离线学习参数。目的是先把“路由决策吃 runtime 信号”这件事做实。
- 我没有把所有信号都接进 router，只接了当前最关键的两类：工具证据状态和上下文压力状态。这样更容易验证，也更容易解释。
- `summarizer` 不是独立 tool，而是独立 role；它的作用是让模型先消费 compact 后的历史，再继续往下走，而不是把 compact 做完却仍按普通 coder 模式推进。

新增测试：
- `tests/test_router.py`
- `tests/test_agent_compaction.py`

验证命令：
```bash
python -m compileall mini_claw tests
python -m unittest discover -s tests -q
python -m mini_claw bench examples\bench\runtime_smoke.json
```

测试结果：
```text
60 tests passed
runtime_smoke bench passed: total 5, passed 5, failed 0
pending lookup routes to reviewer
new compaction routes to summarizer
context_build trace includes route_reason=new_context_compaction
```

面试表达：
> 我没有把模型路由停留在“第一步 planner，失败了 reviewer”这种很薄的层面，而是让 router 真正读取 runtime 状态。比如工具结果被截断且挂起 `pending_lookup` 时，下一步会切到 reviewer，避免模型盲目重跑 shell；而当更早步骤已经被 compact 成 `Working Summary` 后，下一步会切到 summarizer，先消费压缩后的历史。这样路由就不是拍脑袋切角色，而是开始有状态地做决策。

## 2026-04-19：Routing Policy Compare

目标：把 signal-aware routing 从“有一套规则”推进成“能和 baseline 做离线对比”。

这轮实现：
- `ModelRouter` 新增 `policy`，当前支持 `basic` 和 `signal-aware`。
- `run` / `eval` / `bench` 都支持显式指定 `--routing-policy`。
- 新增 `bench-routing` CLI，可以在同一组 offline bench 上对比多套 routing policy。
- `Replay` 新增 `route_reason_counts`，可以统计一次运行里各类 route reason 的分布。
- `BenchReport` 和 `BenchRoutingComparisonReport` 会展示 route reason 分布，让 scripted bench 也能看出不同策略的行为差异。

关键取舍：
- 这版 compare 先比较 route behavior，而不是强行声称成功率已经有显著差异。因为 scripted bench 主要用于验证 runtime 行为，不是最终模型效果对比。
- 我没有把 policy 配置塞进模型层，而是直接挂在 `ModelRouter`，保持职责清晰。
- `basic` policy 保留了最初的阶段式路由逻辑，作为 ablation baseline。

验证命令：
```bash
python -m unittest discover -s tests -q
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：
```text
62 tests passed
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

## 2026-04-19：Skill Patch Artifact 审阅流

目标：把 `skill_patch_candidate` 从“候选建议”推进成“可审阅、可归档、可追踪”的 artifact 流，同时继续避免 runtime 直接修改 `SKILL.md`。

这轮实现：
- 新增 `mini_claw/skills/patches.py`，提供 `parse_skill_patch_candidate_content(...)` 和 `render_skill_patch_artifact(...)`，把候选内容拆成 metadata、contract patch 和 instruction patch。
- `MemoryStore.promote_memory_candidate(...)` 在 promote `skill_patch_candidate` 时，会生成 `.mini_claw/skill_patches/<artifact_id>.md`。
- 新增 `.mini_claw/memory/skill_patch_artifacts.jsonl`，记录 artifact id、candidate id、target skill、skill path、promote reason 和 artifact 路径。
- `read_memory_candidates(...)` 会把已生成 artifact 的元数据回填到 candidate 结果里，便于 CLI 或后续评审流程展示。
- CLI 新增 `memory skill-patches` 和 `memory skill-patch-show`，用于列出和查看 promote 后生成的 skill patch artifact。
- runtime trace 新增 `skill_patch_artifact_created` 事件，Replay 新增 `skill_patch_artifacts_created` 指标。
- `mini_claw/skills/__init__.py` 导出 skill evolution 和 patch artifact 相关 API，保持 skill 包边界清晰。

关键取舍：
- 我仍然没有让 agent 直接改 `SKILL.md`。skill 是行为边界，一旦自动写坏，后续所有任务都会被错误规则影响，所以这里采用 candidate -> promote -> artifact 的审阅流。
- artifact 与 project memory 分离。`project_memory.md` 继续只放稳定项目事实，skill 演进建议进入 `.mini_claw/skill_patches/`，便于人工 review、后续 eval gate 或手动合入。
- 这一步先生成 markdown artifact，而不是自动应用 patch。这样能在面试里讲清楚“自主进化不是不受控自改，而是有审计和人工确认边界的演进闭环”。

新增测试：
- `tests/test_memory_store.py`
- `tests/test_cli_memory.py`
- `tests/test_trace_replay.py`
- `tests/test_skill_patches.py`

验证命令：

```bash
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
64 tests passed
compileall passed
bench-routing passed
```

面试表达：

> 我没有把“自主进化”做成让 agent 直接改自己的 `SKILL.md`，而是做成 candidate-first 的审阅链路。成功任务会先生成 `skill_patch_candidate`，promote 后才会物化成 `.mini_claw/skill_patches/<artifact_id>.md`。这个 artifact 里包含目标 skill、建议修改的 contract、instruction patch、来源 candidate 和 review checklist，同时 trace 会记录 `skill_patch_artifact_created`。这样系统能沉淀经验，但最终是否固化进 skill，仍然可以交给人工或 eval gate。

## 2026-04-19：Skill Patch Eval Gate

目标：把 skill patch artifact 从“可审阅文档”推进到“可验证建议”，让自进化链路具备最小可用的 eval gate。

这轮实现：
- 新增 `.mini_claw/memory/skill_patch_eval_results.jsonl`，记录每次 artifact 验证的 `eval_id`、命令、状态、exit code 和输出。
- `MemoryStore.record_skill_patch_eval_result(...)` 会把验证结果写入 JSONL，同时追加到对应 `.mini_claw/skill_patches/<artifact_id>.md` 的 `Eval Gate Result` section。
- `read_skill_patch_artifacts(...)` 会回填最近一次 `eval_status`、`eval_command`、`eval_exit_code` 和 `eval_created_at`，CLI 列表中可以直接看到 artifact 是 pending、passed 还是 failed。
- CLI 新增 `memory skill-patch-verify <ref> --command "<cmd>"`，在当前 workspace 下执行验证命令，并把结果绑定到 artifact。
- runtime trace 新增 `skill_patch_eval_recorded` 事件，Replay 新增 `skill_patch_eval_runs` 和 `skill_patch_eval_passed` 指标。
- `Skill Patch Artifact` 的 review checklist 更新为先跑 `skill-patch-verify`，再决定是否人工合入 `SKILL.md`。

关键取舍：
- 这一步仍然不自动应用 patch。验证通过只能说明“这个演进建议没有打破指定验证命令”，不等于可以无审查合入行为边界。
- eval gate 先接受显式命令，而不是自动推断所有测试命令。这样更符合当前项目阶段：我们先把记录链路和可观测性做实，再逐步补命令推荐和多任务 benchmark。
- 验证结果直接追加到 artifact 文件里，方便面试展示时从单个文件看到完整链路：candidate 来源、建议内容、review checklist 和 gate 结果。

新增测试：
- `tests/test_memory_store.py`
- `tests/test_cli_memory.py`
- `tests/test_trace_replay.py`

验证命令：

```bash
python -m unittest tests.test_memory_store tests.test_cli_memory tests.test_trace_replay -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted tests passed
64 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我把 skill 自进化拆成了四步：先由成功任务生成 `skill_patch_candidate`，人工 promote 后生成独立 artifact，再通过 `skill-patch-verify` 绑定验证命令和结果，最后才考虑人工合入 `SKILL.md`。这样系统不是“自动改自己”，而是一个带证据、带审阅、带 eval gate 的演进流程。

## 2026-04-19：Skill Patch Dry-run Preview

目标：把通过 eval gate 的 skill patch artifact 推进到“可审阅合入预案”，但仍然不自动改写 `SKILL.md`。

这轮实现：
- 新增 `build_skill_patch_apply_preview(...)`，从 artifact 中提取 `Proposed Contract Patch` 和 `Proposed Instruction Patch`，生成追加到目标 `SKILL.md` 末尾的预览内容。
- 预览结果以 unified diff 输出，`fromfile` 是原始 skill path，`tofile` 是 `<skill_path> (skill patch preview)`。
- CLI 新增 `memory skill-patch-preview <ref>`，读取 artifact 中的 `skill_path`，校验目标路径不能逃出 workspace，然后只打印 dry-run diff。
- `skill-patch-preview` 不写入 `SKILL.md`，只写一条 `skill_patch_apply_previewed` trace 事件。
- Replay 新增 `skill_patch_apply_previews` 指标，用于统计有多少 skill patch 已经进入合入预览阶段。
- `mini_claw.skills` 导出 `SkillPatchPreview` 和 `build_skill_patch_apply_preview(...)`。

关键取舍：
- 这一步仍然不提供真正的 apply。原因是 skill 是 agent 行为边界，直接自动写入可能把一次局部经验变成全局错误规则。
- preview 采用“追加 Runtime Learning Proposal”的保守策略，而不是试图自动编辑 YAML metadata。这样 diff 更稳定，也更容易人工 review。
- 路径校验放在 CLI 层，确保 artifact 里的 `skill_path` 不能通过 `..` 指向 workspace 外部文件。

新增测试：
- `tests/test_skill_patches.py`
- `tests/test_cli_memory.py`
- `tests/test_trace_replay.py`

验证命令：

```bash
python -m unittest tests.test_skill_patches tests.test_cli_memory tests.test_trace_replay -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted preview tests passed
65 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我把 skill patch 的最后一步也做成了安全预览，而不是自动落盘。artifact 通过验证后，可以运行 `skill-patch-preview` 生成对目标 `SKILL.md` 的 unified diff，但原文件不会被写入。这样自进化链路有了 candidate、artifact、eval gate 和 apply preview 四层，但每一层都保留人工或评测确认点。

## 2026-04-19：Read-before-write Guard

目标：补强安全编辑机制，引入“read-before-write”约束，避免 agent 在没读过目标文件或读后文件已漂移的情况下直接 patch。

这轮实现：
- `MemoryStore` 新增 `.mini_claw/memory/read_snapshots.jsonl`，用于记录文件读取快照。
- `ShellTool` 在成功执行 `cat`、`type`、`Get-Content` / `gc` 这类文件读取命令后，会捕获目标文件的 `sha256`、存在状态和字符数，并写入 read snapshot。
- `PatchTool` 新增 `require_read_snapshot` 选项；开启后，修改已有文件前必须存在对应 read snapshot。
- 如果目标文件未读过，`apply_patch` 会返回 `READ_BEFORE_WRITE_REQUIRED`。
- 如果文件读过但当前 hash 和 read snapshot 不一致，`apply_patch` 会返回 `STALE_READ_SNAPSHOT`，要求重新读取并基于最新内容重建 patch。
- `mini_claw run` 新增 `--enforce-read-before-write`，用于在真实 agent 运行时开启该 guard。
- Failure Attribution 新增 `READ_BEFORE_WRITE_REQUIRED` 和 `STALE_READ_SNAPSHOT` 两类根因。
- Prompt 中补充 read-before-write 行为约束，指导模型在 patch 前先读取目标文件。

关键取舍：
- 该机制做成可选开关，而不是直接改掉所有底层 patch 行为。原因是离线 scripted bench 和内部 merge flow 有些场景已经有其他锁机制，比如 `expected_sha256` 或 workspace manifest；先作为 runtime guard 开启更稳。
- 只对已有文件的修改/删除强制 read snapshot，新文件创建不需要 read-before-write。
- 这版先识别显式文件读取命令，不把所有 `rg` / `dir` / `ls` 都当成 read snapshot。因为搜索结果不等于完整文件内容，不能作为可靠写入依据。

新增测试：
- `tests/test_patch_tool.py`
- `tests/test_failure_attribution.py`

验证命令：

```bash
python -m unittest tests.test_patch_tool tests.test_failure_attribution -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted read-before-write tests passed
70 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我把安全编辑从“patch 事务和 hash 预条件”继续推进到了 runtime 级 read-before-write。agent 通过 shell 读取文件时，系统会记录 read snapshot；开启 guard 后，`apply_patch` 修改已有文件前必须能找到对应 snapshot，而且当前 hash 必须和读取时一致。否则会返回 `READ_BEFORE_WRITE_REQUIRED` 或 `STALE_READ_SNAPSHOT`，并进入 Failure Attribution。这样可以明确防止模型基于过期上下文误改代码。

## 2026-04-19：Git Worktree 任务隔离

目标：把任务级隔离从 `workspace_copy` 升级为同时支持 `git-worktree`，提升项目作为真实 CLI Coding Agent 的生产感，并增强并行任务隔离能力。

这轮实现：
- `TaskWorkspace` 新增 `mode` 字段，当前支持 `copy` 和 `git-worktree`。
- `TaskWorkspaceManager.create(task_id, mode)` 支持两种创建模式：
  - `copy`：继续写入 `.mini_claw/task_workspaces/<task_id>`。
  - `git-worktree`：写入 `.mini_claw/task_worktrees/<task_id>`，并通过 `git worktree add -B mini-claw/<task_id> <path> HEAD` 创建独立分支工作区。
- `workspace create` CLI 新增 `--mode copy|git-worktree`，默认仍为 `copy`。
- `workspace list` 会展示每个任务工作区的 `mode`。
- `workspace diff` / `workspace merge` 会自动解析 copy 或 git worktree 路径，继续复用 base manifest、conflict detection 和 `PatchTransaction`。
- manifest 新增 `mode` 字段，便于后续 replay 或 integrator 统计任务隔离方式。

关键取舍：
- `copy` 模式保留为默认值，因为它不要求 git 仓库，适合测试、临时目录和非 git 项目。
- `git-worktree` 模式只在当前 workspace 是 git repo 时可用；不是 git repo 会直接报错，而不是静默 fallback，避免用户误以为自己获得了 worktree 级隔离。
- worktree 仍放在 `.mini_claw` 下，便于项目内统一管理；后续如果要做更接近生产的隔离，可以把 worktree root 放到 repo 外部缓存目录。

新增测试：
- `tests/test_task_workspace.py`
- `tests/test_cli_workspace.py`

验证命令：

```bash
python -m unittest tests.test_task_workspace tests.test_cli_workspace -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted workspace tests passed
71 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我最开始先实现了 `workspace_copy`，因为它更容易验证任务隔离、diff 和 merge flow。后面我又把隔离层升级为双模式：非 git 项目继续使用 copy，真实 git 仓库可以用 `git-worktree` 创建任务级独立分支工作区。无论哪种模式，最终 diff 和 merge 都回到同一套 manifest conflict detection 和 PatchTransaction，避免隔离层绕过安全编辑机制。

## 2026-04-19：基础多 Agent 编排闭环

目标：把多 Agent 从 ACP-like 数据结构和任务隔离基础，推进到一个可运行的 `planner -> coder -> tester -> integrator` 顺序编排闭环。

这轮实现：
- 新增 `mini_claw/task_graph/orchestrator.py`。
- 新增 `RoleStep` 和 `OrchestrationReport`，用于记录每个角色对任务的处理结果。
- `run_task_graph_orchestration(...)` 会读取 `TaskGraph.ready()`：
  - `planner` 选择 ready task，并设置为 `in_progress`。
  - `coder` 创建或复用任务级 workspace。
  - `tester` 在任务 workspace 下执行 `verification_command`。
  - `integrator` 在测试通过后调用 `TaskWorkspaceManager.merge(...)` 合回主工作区。
- 每次角色移交写入 `multi_agent_handoff` trace，复用已有 `HandoffPacket.to_acp()`。
- 每个角色步骤写入 `orchestration_step` trace。
- CLI 新增 `orchestrate`：

```bash
python -m mini_claw orchestrate --limit 1 --mode copy
python -m mini_claw orchestrate --limit 1 --mode git-worktree
python -m mini_claw orchestrate --dry-run
```

关键取舍：
- 这版先做顺序多角色编排，而不是并发 swarm。原因是当前最重要的是把任务状态、workspace、verification 和 integrator merge 串成闭环。
- `coder` 阶段暂时不主动调用模型，而是消费已有任务工作区改动。这样可以先测试 integrator 和 tester 的职责边界，后续再把 coder 替换成真实 `AgentLoop`。
- Integrator 复用已有 `workspace merge`，所以多 Agent 编排不会绕过安全合并机制。

新增测试：
- `tests/test_orchestrator.py`
- `tests/test_cli_workspace.py`

验证命令：

```bash
python -m unittest tests.test_orchestrator tests.test_cli_workspace -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted orchestration tests passed
74 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我没有一上来做复杂并发多 Agent，而是先把多角色职责做成一个可运行闭环：planner 选 ready task，coder 准备隔离工作区，tester 在任务工作区跑验证，integrator 通过安全 merge flow 合回主工作区。每次 handoff 和角色步骤都会进入 trace。这样多 Agent 不是文档里的概念，而是已经能驱动 TaskGraph 和 workspace 的 runtime 编排。

## 2026-04-19：Orchestrator Coder Agent 接入

目标：把基础多 Agent 编排里的 `coder` 阶段从“只消费已有 workspace 改动”推进到“可选在任务工作区运行 AgentLoop”。

这轮实现：
- `orchestrator.py` 新增 `CoderRunResult` 和 `CoderRunner` 抽象。
- `run_task_graph_orchestration(...)` 新增 `coder_runner` 参数；如果提供，会在任务 workspace 准备好之后调用。
- coder runner 成功后继续进入 tester / integrator；失败则任务置为 `failed`，不进入 tester。
- `orchestrate` CLI 新增 `--run-coder-agent`。
- 开启 `--run-coder-agent` 后，CLI 会为任务 workspace 构造独立 `AgentLoop`，工具执行 cwd 指向任务 workspace，但 trace / memory 仍写入主工作区 `.mini_claw/memory`。
- `orchestrate` 透传 `--provider`、`--model`、`--routing-policy`、`--max-steps`、`--timeout` 和 `--enforce-read-before-write` 给 coder agent。

CLI 示例：

```bash
python -m mini_claw orchestrate --limit 1 --mode copy --run-coder-agent
python -m mini_claw orchestrate --limit 1 --mode git-worktree --run-coder-agent --provider openai-compatible --model your-coder-model
```

关键取舍：
- 默认不自动跑 coder agent，保持原来的“消费已有任务工作区改动”路径，方便测试 integrator 和 workspace merge。
- coder agent 在任务工作区执行，避免直接污染主工作区；合回仍由 integrator 统一走 `workspace merge`。
- trace / memory 暂时统一写回主工作区，方便 replay 一次看到完整 orchestration 和 coder agent 轨迹。

新增测试：
- `tests/test_orchestrator.py`
- `tests/test_cli_workspace.py`

验证命令：

```bash
python -m unittest tests.test_orchestrator tests.test_cli_workspace -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
targeted coder-agent orchestration tests passed
76 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 我把多 Agent 编排里的 coder 阶段做成可插拔 runner。默认可以只消费已有任务工作区改动，用来测试 integrator；开启 `--run-coder-agent` 后，coder 会在任务 worktree/copy workspace 里运行完整 AgentLoop。这样模型写代码的风险被限制在任务工作区，最终仍由 tester 和 integrator 统一验证、合并。

## 2026-04-19：Orchestration Replay Metrics

目标：让多 Agent 编排不仅能执行，还能在 Trace Replay 中量化复盘。

这轮实现：
- `ReplaySummary` 新增多 Agent 相关指标：
  - `multi_agent_handoffs`
  - `orchestration_steps`
  - `orchestration_role_counts`
  - `tester_failures`
  - `integrator_merges`
  - `integrator_failures`
- `replay_trace(...)` 会统计 `multi_agent_handoff` 和 `orchestration_step` 事件。
- `to_markdown()` 新增 `## Orchestration Roles` section，展示 planner / coder / tester / integrator 等角色分布。
- tester 角色失败会计入 `tester_failures`。
- integrator 角色成功会计入 `integrator_merges`，失败会计入 `integrator_failures`。

关键取舍：
- 这版先做角色级统计，不分析每个 handoff 的上下文质量。原因是当前最需要证明的是多 Agent 流程是否真的跑到了 tester / integrator 阶段。
- integrator success 当前按 `orchestration_step.status == "ok"` 统计。后续如果 integrator 增加仲裁细分，可以再拆出 `merged / dry_run / conflict / rejected`。

新增测试：
- `tests/test_trace_replay.py`

验证命令：

```bash
python -m unittest tests.test_trace_replay -q
python -m unittest discover -s tests -q
python -m compileall mini_claw tests
python -m mini_claw bench examples\bench\runtime_smoke.json
python -m mini_claw bench-routing examples\bench\runtime_smoke.json --policies basic signal-aware
```

测试结果：

```text
trace replay orchestration metrics passed
76 tests passed
compileall passed
runtime_smoke bench passed: total 5, passed 5, failed 0
bench-routing passed
basic route_reasons: continue_execution=7, initial_planning=5, recent_failure=4
signal-aware route_reasons: continue_execution=4, initial_planning=5, pending_tool_output_lookup=4, recent_failure=3
```

面试表达：

> 多 Agent 如果只有 handoff 文档，很难证明它真的在工作。所以我把 `multi_agent_handoff` 和 `orchestration_step` 接进 Trace Replay，能统计一次运行里发生了多少次 handoff、各角色执行了多少步、tester 失败多少次、integrator 成功合并多少次。这样多 Agent 编排也进入了可观测和可评测闭环。

面试表达：
> 我没有只做一套 routing 规则，然后主观说它更好，而是保留了 `basic` baseline，并做了 `bench-routing` 对比入口。即使在 scripted bench 里成功率还一样，我也能先比较 route reason 分布，证明 signal-aware router 确实在消费 `pending_lookup`、compact 这些 runtime 信号，而不是表面换个名字。
