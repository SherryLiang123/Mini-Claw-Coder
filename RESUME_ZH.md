# 简历项目描述：Mini Claw-Coder

## 项目名称

**Mini Claw-Coder：可验证的代码智能体运行时**

## 一句话介绍

设计并实现一个面向真实代码仓库的轻量级 Coding Agent Runtime，通过最小工具集、上下文管理、模型路由、记忆系统、Skill 机制、执行追踪和评测闭环，提升代码智能体在多步开发任务中的可控性、可观测性和可持续改进能力。

## 简历项目经历版本

**Mini Claw-Coder：可验证的代码智能体运行时**  
个人项目 / Python / LLM Agent / Coding Agent / Agent Runtime

- 设计并实现轻量级 Coding Agent Runtime，支持从自然语言任务到代码搜索、文件修改、命令执行、测试验证和结果总结的基础闭环。
- 采用最小工具集设计，将 `shell`、`apply_patch` 和只读的 `tool_output_lookup` 收敛为核心行动接口，将搜索、修改、验证和结果回查能力统一纳入 runtime，降低工具选择复杂度和安全审计成本。
- 新增 Tool Output Lookup Policy、Auto Focus Lookup Plan 与 intent-aware evidence refinement，在工具结果被截断后挂起 `pending lookup`，对重复的 shell inspection 做 runtime 级拦截，并为 agent 自动生成高信号 query / 行范围建议，支持按 `error/path/symbol/task` 意图和 `exclude_queries` 做多跳证据细化。
- 将 evidence planner 的使用结果沉淀为 `evidence_summary` 和 `evidence_lookup_strategy` memory candidate，把一次成功任务中的证据搜索路径结构化记录到 trace 与候选记忆中；promote 后不直接污染 `project_memory.md`，而是按任务 query 检索并回流到 `ContextPacket` 的 `Evidence Strategies` section，支撑后续复盘与经验复用。
- 实现 Agent Loop，抽象 observe-think-act 执行流程，支持模型输出结构化 action、工具执行、结果观测、失败重试和最终总结。
- 设计上下文管理模块，将用户任务、工作区快照、项目记忆、Skill 内容和执行轨迹统一组织进上下文，并支持轻量压缩，减少长任务中的上下文污染。
- 实现 `ContextPacket` / `ContextCompiler`，将上下文构造从简单拼接升级为结构化编译，并在 trace 中记录 token/字符预算、压缩状态和被截断的上下文区域；进一步补充自动 `Working Summary` compact 机制，在长任务中保留最近步骤完整轨迹、压缩更早步骤并输出 `context_compacted` 运行时信号。
- 实现 FileIndex / 渐进式披露机制，按文件路径、语言、大小、关键符号和预览行构建索引，并根据任务 query 进行轻量打分，避免将完整文件内容无差别注入上下文。
- 实现 signal-aware 模型路由策略，将 `pending_lookup`、失败次数、compact 状态和上下文预算接入角色选择；在 planner、coder、reviewer、summarizer 之间切换，并把 `route_reason` / `route_signals` 写入 trace，同时提供 `basic` vs `signal-aware` 的离线 bench 对比入口，为后续低成本模型和强推理模型协同提供可观测基础。
- 实现 Memory Store，持久化项目级记忆和 JSONL 执行轨迹，用于记录项目约束、常用命令、用户偏好和 agent 行为链路。
- 实现基于 `SKILL.md` 的 Skill Contract 机制，支持 triggers、inputs、outputs、allowed_tools、forbidden_paths 和 verification 等 metadata，并根据任务 query 进行相关性召回，将可复用开发经验沉淀为有边界的能力模块。
- 实现 Skill Guardrail，将 active skill 的 `allowed_tools` 和 `forbidden_paths` 接入 Agent Loop 工具调用前校验，使 Skill Contract 从声明式提示升级为 runtime 硬约束。
- 基于成功任务中的 `evidence_summary` 和相关 skill 命中结果，生成 candidate-first 的 `skill_patch_candidate`，并在 promote 后落盘为 `.mini_claw/skill_patches/<artifact_id>.md` 审阅 artifact，再通过 `skill-patch-verify` 记录验证结果、通过 `skill-patch-preview` 生成 `SKILL.md` dry-run diff，把 `tool_output_lookup`、`focus='auto'` 和多跳 refine 流程沉淀为可审计、可验证、可预览的 skill 演进建议，而不是直接修改 `SKILL.md`。
- 设计 ACP-like handoff 消息结构，并实现 `planner -> coder -> tester -> integrator` 最小多 Agent 编排闭环；`coder` 阶段可选在任务工作区内运行 AgentLoop，将任务选择、隔离执行、验证命令和安全 merge 串成可运行流程，并在 Replay 中统计 handoff、角色步骤、tester failure 和 integrator merge 指标。
- 实现 JSONL Eval Runner 和离线 EvalBench，支持 scripted actions、临时工作区、verification commands、expected_success 和运行指标报告，为后续 prompt、skill、model routing 和工具策略优化提供评测基础。
- 实现 Patch Transaction，将 `apply_patch` 升级为带文件快照、`sha256` 预条件、read-before-write guard、stale-read blocking、diff 摘要、verification 绑定、事务 journal 和失败回滚的安全编辑机制，降低基于过期内容误改代码的风险。
- 实现 Failure Attribution，根据工具错误、模型输出异常、patch 冲突、未读先写、stale snapshot、命令超时、依赖缺失和测试失败等模式生成结构化失败报告，为 eval-driven self-improvement 提供可分析信号。
- 实现 Trace Replay，支持将 `task_trace.jsonl` 回放为结构化报告，统计 context build、tool call、失败工具调用、patch transaction 和 failure report 等运行时指标。
- 实现统一 Tool Output Protocol，将工具原始结果存档到 `tool_outputs/<output_id>.json`，在上下文中仅保留预览、截断状态和 lookup hint，并提供 `tool-output list/show` 回查入口，降低长命令输出对上下文的污染。
- 实现 memory candidate-first 策略，成功任务先生成带 source、confidence、evidence 和 tags 的候选记忆，并支持 promote/reject 决策日志；将项目事实记忆、evidence strategy 和记忆候选式 skill patch 分层管理，skill patch promote 后生成独立 artifact，绑定 eval gate 结果，并支持 dry-run 合入预览，避免未经确认或一次性的运行时策略直接污染长期 `project_memory.md`。
- 实现基础 TaskGraph / Todo，支持任务节点持久化、依赖关系、状态流转、上下文引用和验证命令，为复杂任务拆解、多 Agent handoff 和任务级隔离预留编排基础。
- 实现任务级隔离工作区，支持 `workspace_copy` 和 `git-worktree` 两种模式；可在 `.mini_claw/task_workspaces/<task_id>` 或 `.mini_claw/task_worktrees/<task_id>` 下创建独立工作区，并将隔离工作区路径自动挂接到 `TaskGraph`，支持任务并行、差异回看和 integrator 合并流程设计。
- 实现任务工作区安全合并流程，基于 base manifest 检测主工作区漂移，在无冲突场景下复用事务化 patch 将任务工作区改动安全合回主工作区，并支持绑定验证命令，避免“隔离修改”最终退化成不受控的文件覆盖。

## 简历精简版本

**Mini Claw-Coder：可验证的代码智能体运行时**

- 基于 Python 实现轻量级 Coding Agent Runtime，支持自然语言任务驱动的代码搜索、修改、命令执行、测试验证与结果总结。
- 设计最小工具集架构，以 `shell`、`apply_patch` 和 `tool_output_lookup` 作为核心接口，降低 agent 工具选择复杂度，并提升行为可控性和安全审计能力。
- 实现 ContextPacket、FileIndex 渐进式披露、模型路由、项目记忆、Skill Contract、执行追踪、Trace Replay 和离线 EvalBench，形成可观测、可评测、可迭代的 agent 执行闭环。
- 设计 ACP-like handoff 协议和多角色路由策略，实现基于 TaskGraph 的 planner / coder / tester / integrator 顺序编排，为后续并行多 Agent 和模型级 handoff 预留扩展能力。
- 实现事务化编辑、统一 Tool Output Protocol、Auto Focus / 多跳 evidence lookup、TaskGraph、任务级隔离工作区、安全 merge flow、Trace Replay 和失败归因能力，支持文件快照 hash、read-before-write、stale-read block、diff 摘要、verification 绑定、patch journal、失败回滚和结构化 FailureReport，解决 Coding Agent 修改不安全、任务难编排、运行难复盘、失败难分析等问题。

## 面试自我介绍版本

我做了一个叫 Mini Claw-Coder 的项目，它不是简单的代码生成 Demo，而是一个面向代码任务的 Agent Runtime。我的目标是解决 Coding Agent 在真实工程落地时的几个问题：工具过多导致行为不可控、上下文越来越脏、模型成本不可控、代码修改缺少安全边界、失败后难以分析原因。

所以我没有选择堆很多工具，而是把工具层压缩到 `shell`、`apply_patch` 和只读的 `tool_output_lookup` 这几个核心接口，再把复杂能力放到 runtime 层，包括 agent loop、上下文管理、模型路由、memory、skill、handoff、trace 和 eval。这样可以更清楚地观察 agent 每一步为什么行动、用了什么上下文、调用了什么工具、修改了哪些文件，以及失败后应该从哪里改进。

这个项目已经加入文件快照 hash、read-before-write guard、stale-read blocking、事务化 patch、统一 Tool Output Protocol、自动结果回查策略、Auto Focus 回查计划、intent-aware 多跳证据规划、evidence summary 反馈、candidate-first skill patch suggestions、skill patch artifact 审阅流、skill patch eval gate、skill patch dry-run preview、自动 context compact、signal-aware routing、diff 摘要、verification 绑定、rollback journal、trace replay、failure attribution、Skill Contract、任务级隔离工作区、基础安全 merge flow 和最小多 Agent 编排闭环。后续会继续补基于失败归因的 skill patch 验证闭环和更完整的 integrator 仲裁流程。我的重点不是复刻一个 Cursor，而是理解并实现 Coding Agent 的底层工程机制。

## 面试亮点回答

### 1. 这个项目解决了什么问题？

它解决的是 Coding Agent 从 Demo 走向真实工程时的可靠性问题。真实代码任务往往需要多步搜索、阅读、修改、测试和修复，如果没有好的上下文管理、工具约束、记忆系统和评测机制，agent 很容易上下文污染、误改代码、重复行动，失败后也很难定位原因。

### 2. 为什么不直接做更多工具？

我希望工具层更像操作系统的 syscall，数量少、边界清晰、容易审计。复杂能力不一定要通过更多工具实现，也可以通过 runtime policy、上下文编译、patch 事务和 eval 反馈来实现。这样 agent 的行动空间更可控，后续也更容易做安全策略。

### 3. 和普通 CLI Code Agent 有什么区别？

普通 CLI Code Agent 更关注“能不能完成任务”，而我这个项目更关注“为什么能完成、失败时为什么失败、如何持续变好”。所以我除了实现 agent loop 和工具调用，还重点设计了 memory、skill、trace、eval、handoff、failure attribution 和 patch transaction。

### 4. 模型路由有什么价值？

Coding Agent 的不同阶段对模型能力要求不同。比如总结上下文可以用小模型，复杂设计需要强推理模型，代码 patch 可以用 coding 模型，失败恢复可以升级到 reviewer 或更强模型。模型路由的价值是平衡成功率、成本和延迟，而不是所有步骤都用同一个模型。

### 5. Skill 系统有什么价值？

Skill 系统让 agent 可以复用经验。现在每个 `SKILL.md` 可以带 metadata 契约，包括触发条件、输入输出、允许工具、禁止路径和验证方式。这样 skill 不只是 prompt 片段，而是有执行边界的能力模块。后续我希望结合失败归因，让失败任务自动生成 skill patch，再通过 eval 验证这个 skill 是否真的提升成功率。

## 技术栈

- Python 3.11+
- LLM Agent Runtime
- OpenAI-compatible Chat Completions API
- CLI
- JSONL Trace
- Skill System
- Model Routing
- Eval Runner
- ACP-like Handoff Protocol

## 项目关键词

```text
Coding Agent
Agent Runtime
Context Engineering
Model Routing
Tool Use
Memory System
Skill System
Runtime Tracing
Eval-driven Improvement
Failure Attribution
Patch Transaction
Multi-Agent Handoff
```

## 后续可量化指标

后续完善评测集后，可以在简历中加入这些量化结果：

- 构建 10-20 个 coding eval tasks。
- 统计任务成功率、平均工具调用次数、平均执行耗时和失败类型分布。
- 对比不同 routing policy 的成功率和成本。
- 对比有无 project memory / skill 的任务完成率。
- 对比普通写文件与事务化 patch 的误改率。

示例写法：

```text
构建包含 bug fix、测试修复、CLI 参数新增、重构和依赖错误排查等场景的 coding eval benchmark，对比不同模型路由和 skill 策略下的任务成功率、工具调用次数和失败归因分布，为 agent 策略优化提供数据依据。
```
