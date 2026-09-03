# mini-SWE-agent Harness 核心扩展与优先级

## 核心结论

针对扩展上下文管理和退出验证

当前 mini-SWE-agent 已经具备最小执行闭环：

```text
Task → Model 决策 → Environment 执行 → Observation → 下一次 Model 调用
```

但它目前更接近一次性的任务执行器，还缺少两项最重要的用户能力：

1. **持续会话与上下文管理**：用户能够在同一个会话中持续提出新要求；随着历史增长，系统仍能稳定地组织模型上下文；
2. **验证式退出**：模型只能申请结束，必须通过测试或其他验收规则后，任务才能被判定为成功。

最终目标是把 mini-SWE-agent 从一次性执行闭环扩展成一个**能够长期协作、上下文可控、完成结果可信**的 Coding Agent Harness。

| 优先级 | 核心能力             | 当前痛点                   | 用户最终获得什么                      |
| --- | ---------------- | ---------------------- | ----------------------------- |
| P0  | 持续会话与上下文管理       | 会话不能持续，历史增长后也缺少上下文组织能力 | 可以在同一个会话中持续工作，长会话也不会因为历史过多而失控 |
| P1  | 验证式退出 `Verifier` | 模型可以错误地宣布任务完成          | 只有通过测试或验收规则后，任务才能成功结束         |

P0 是一个父能力，内部只包含两个子能力：

```text
P0 持续会话与上下文管理
├── P0.1 会话持久化：完整保存发生过的事实
└── P0.2 上下文压缩：活动历史超出预算时，用摘要替换较早历史
```

两者共同组成一个完整链路：

```text
完整保存历史
→ 在预算内，将规范化后的活动历史发送给模型
→ 超出 token 预算时，生成交接摘要
→ 用 replacement history 替换较早活动历史
→ 继续追加后续对话和工具记录
```

这里不单独建设“上下文选择”或语义检索。参考 Codex 的实现，第一版 `ContextManager` 在预算内使用当前活动历史，只负责消息规范化、工具调用协议完整性、长输出截断和 token 预算；达到阈值后才触发压缩。

会话持久化与上下文压缩属于同一个产品能力，但工程上仍应先保证完整历史可持续保存，再加入有损压缩。否则，压缩摘要可能成为唯一记录，原始事实一旦丢失便无法追溯。

## P0：持续会话与上下文管理

### 要解决的问题

当前 [`DefaultAgent.run()`](../../../src/minisweagent/agents/default.py) 每次开始都会执行：

```python
self.messages = []
```

同一次 `run()` 内，模型能够看到前面的消息和工具结果；但一次运行结束后，下一次交互不能自然地接着原来的会话继续。

现有 `save()` 虽然能够保存 trajectory，但 trajectory 主要是一次运行的结果记录。项目还缺少稳定的会话身份、持续追加的新轮次，以及从持久化记录重建活动历史的机制。

我们要实现的不是抽象的“恢复功能”，而是用户可以直接理解的体验：

> 用户能够在同一个会话中持续对话和工作。即使关闭程序后再次打开这个会话，也可以继续提出新的要求，Agent 能够接着之前的任务状态继续处理。

### 目标体验

```text
创建一个会话
→ 用户提出第一个任务
→ Agent 分析、修改代码并运行测试
→ 第一轮完成
→ 用户继续提出补充要求
→ Agent 理解前面已经做过什么并继续工作
→ 用户关闭程序
→ 再次打开同一个会话
→ 用户继续提出新要求
```

这里的“继续”表示在同一个会话中开始新一轮交互。它不表示恢复模型生成到一半的回复，也不表示自动把文件系统回滚到某个历史时刻。

## P0.1：会话持久化

### 它负责什么

会话持久化负责完整保存会话中已经发生的事实：

- 用户说了什么；
- 模型回复了什么；
- 模型提出了哪些 action；
- Environment 执行了什么；
- 命令返回了什么结果；
- 验证是否通过；
- 发生过哪些上下文压缩。

推荐使用三层会话模型：

```text
Thread：一个可以持续对话的完整会话
└── Turn：用户的一次输入及 Agent 对它的完整处理
    └── Item：Turn 内发生的一条事实
```

例如：

```text
Thread：修复登录功能
├── Turn 1：修复登录超时
│   ├── user_message
│   ├── assistant_message
│   ├── action
│   ├── observation
│   └── verification_result
└── Turn 2：把错误提示改成中文
    ├── user_message
    ├── assistant_message
    ├── action
    └── observation
```

第一版至少需要：

```python
@dataclass
class Thread:
    id: str
    cwd: Path
    created_at: str
    status: str


@dataclass
class Turn:
    id: str
    thread_id: str
    status: str


@dataclass
class Item:
    id: str
    thread_id: str
    turn_id: str
    type: str
    payload: dict
```

ThreadStore 应完整、追加式地保存 Item。后续压缩只替换模型使用的活动历史，不能删除或覆盖 ThreadStore 中的原始事实。

## P0.2：上下文压缩

### Codex 的核心做法

这里不再设计一个从完整历史中挑选相关消息的“选择器”。参考 Codex，系统维护两份不同用途的数据：

```text
ThreadStore
    完整、追加式地保存会话事实

ActiveHistory
    当前真正用于调用模型的活动历史
```

在还没有发生压缩时，`ActiveHistory` 就是当前 Thread 中所有模型可见的历史。每次调用模型前，`ContextManager` 只做确定性处理：

- 过滤不应发送给模型的内部事件；
- 截断特别长的工具输出；
- 保证 tool call 与 tool result 协议完整；
- 移除模型不支持的输入类型；
- 估算当前 token 使用量。

如果没有达到压缩阈值，规范化后的 `ActiveHistory` 整体发送给模型，不做语义检索，也不让模型逐条判断哪些历史与当前问题相关。

### 压缩触发

每次模型调用前或一次模型响应完成后，检查活动历史的 token 使用量：

```text
估算 ActiveHistory token
→ 未达到阈值：发送完整 ActiveHistory
→ 达到阈值：执行 Compaction
```

压缩阈值应低于模型的硬上下文上限，为压缩请求和下一次模型输出预留空间。如果压缩请求本身仍然超过窗口，可以从最早的活动历史开始移除 Item，优先保留近期内容，直到压缩请求可以执行。

### 生成交接摘要

触发 Compaction 后，Harness 使用专门的压缩提示词调用模型，要求它为“接下来继续任务的模型”生成交接摘要。摘要至少包含：

- 当前进展和关键决策；
- 重要上下文、约束和用户偏好；
- 尚未完成的工作和明确下一步；
- 继续任务所需的关键数据、示例和引用；
- 重要文件修改和最近验证结果。

这里模型的职责是总结已经发生的活动历史，而不是从完整 ThreadStore 中逐条选择相关消息。

### Replacement History

压缩完成后，构造一份新的 replacement history：

```text
必要的初始上下文和 Harness 规则
+ 最近的若干用户消息
+ Compaction Summary
```

然后用 replacement history 替换原来的 `ActiveHistory`。后续用户消息、模型回复、action 和 observation 继续追加到它后面：

```text
压缩前 ActiveHistory
    Turn 1 → Turn 2 → ... → Turn 20

压缩后 ActiveHistory
    初始上下文
    + 最近用户消息
    + Turn 1～20 的交接摘要

继续执行后
    初始上下文
    + 最近用户消息
    + Turn 1～20 的交接摘要
    + Turn 21
    + Turn 22
```

ThreadStore 中的原始 Item 不因压缩而删除。Compaction 需要额外持久化：

```json
{
  "type": "compaction_created",
  "covers_through_item_id": "item-120",
  "summary": "...",
  "replacement_history": [
    "..."
  ]
}
```

### 再次打开同一个会话

再次打开 Thread 时，不需要重新把全部原始历史塞进模型：

```text
找到最近一次 compaction_created
→ 使用其中的 replacement_history 作为 ActiveHistory 基线
→ 按时间顺序追加该 checkpoint 之后的新 Item
→ 规范化 tool call / tool result
→ 开始新的 Turn
```

如果 Thread 从未发生压缩，则从全部模型可见 Item 重建 `ActiveHistory`。

因此，上下文压缩是有损的模型输入优化；ThreadStore 仍然是完整事实源，replacement history 只是当前模型上下文的新起点。

## P0 第一版验收标准

- 一个 Thread 可以包含至少两个连续 Turn；
- 关闭程序后再次打开同一个 Thread，可以继续提出新的要求；
- 用户消息、模型回复、action 和 observation 都能持续追加；
- 新 Item 不覆盖旧记录；
- 每次模型调用都经过统一的 `ContextManager`；
- 未压缩时，规范化后的 `ActiveHistory` 整体进入模型输入，不进行语义选择；
- 未达到阈值时不会无意义压缩；
- 达到阈值后，模型输入能够回到 token 预算范围；
- tool call 和 tool result 始终成组保留；
- 压缩摘要包含当前进展、约束、关键决策、未完成事项和下一步；
- `compaction_created` 保存摘要、覆盖边界和 replacement history；
- 再次打开 Thread 时，可以从最近 replacement history 加后续 Item 重建 `ActiveHistory`；
- 压缩不修改或删除原始 Thread 记录；
- cwd 不匹配、记录损坏或 schema 不兼容时给出明确错误；
- 未启用持续会话时，原有最小运行方式仍然可用。

## P0 第一版边界

- 不做跨 Thread 的长期记忆或自动检索；
- 不使用 embedding 从全部历史中做语义检索；
- 不建设独立的“上下文选择器”；
- 不要求每个 Turn 都生成或维护一份任务状态清单；
- 不承诺恢复执行到一半的 Shell 进程；
- 不自动回滚或重放已经修改本地文件的命令；
- 不先引入数据库或复杂事件总线，JSONL 追加式存储即可。

## P1：验证式退出 `Verifier`

### 要解决的问题

当前 Agent 遇到提交哨兵后就可以结束。这个机制只能说明“模型想结束”，不能证明“任务已经完成”。

例如模型可能在以下情况下错误宣布完成：

- 修改了代码，但没有运行测试；
- 只修复了表面错误，引入了回归；
- 测试已经失败，但模型忽略失败结果；
- 任务要求没有全部满足。

### 目标体验

```text
模型请求结束
→ Verifier 执行预先配置的验收项
→ 全部通过：Turn 成功完成
→ 验证失败：把结果写入当前 Turn
→ 失败结果重新进入模型上下文
→ Agent 继续修复
```

例如：

```yaml
agent:
  verification_commands:
    - pytest -q
    - ruff check src tests
```

核心原则是：

> 模型只能申请结束，不能单方面决定任务成功；任务是否完成由 Harness 配置的验收规则决定。

### 第一版能力与验收标准

- 定义可替换的 `Verifier` 协议和结构化 `VerificationResult`；
- 支持成功、失败、超时和无法执行等明确状态；
- 验证结果与当前 `turn_id` 关联；
- 验证失败的输出进入 Thread，并作为下一次模型调用的上下文；
- 模型不能在准备退出时自行删除或降低验收标准；
- 模型虚假声明完成时，失败的验收命令能够阻止退出；
- 所有验收项通过后，Turn 才标记为成功；
- 没有配置 Verifier 时保持原有兼容行为；
- 文档、调查等不适合自动测试的任务，可以使用可替换 Verifier 或人工确认。

## 支撑核心功能的工程基架

P0 和 P1 是用户能够感知的核心能力。下面这些是实现核心能力需要配备的工程基架，不应与核心能力平铺介绍。

| 工程基架                               | 主要作用                                      | 支撑的核心能力 |
| ---------------------------------- | ----------------------------------------- | ------- |
| Thread / Turn / Item 领域模型          | 明确会话、轮次和事实边界                              | P0、P1   |
| 稳定 ID 与关联关系                        | 跨进程定位 Thread，并关联 Turn、action 和验证结果        | P0、P1   |
| `ThreadStore` 追加式存储                | 保存完整事实源                                   | P0      |
| 最小结构化生命周期事件                        | 表达发生了什么，并支持状态重建                           | P0、P1   |
| `ActiveHistory` / `ContextManager` | 维护、规范化并估算当前模型可见历史                         | P0      |
| `Compactor`                        | 生成交接摘要和 replacement history               | P0      |
| `RolloutReconstructor`             | 从最近 replacement history 和后续 Item 重建活动历史   | P0      |
| Schema 版本                          | 保证未来仍能读取旧 Thread                          | P0      |
| 工作区一致性检查                           | 避免在错误 cwd 或仓库状态中继续会话                      | P0      |
| 协议化组件边界                            | 让 Store、ContextManager 和 Verifier 可替换、可测试 | P0、P1   |
| 确定性测试基架                            | 不依赖真实模型 API 验证保存、投影、压缩和退出                 | P0、P1   |

### 最小结构化事件不是完整事件平台

ThreadStore 不能只保存一堆没有边界的 messages。第一版至少要能表达：

```text
thread_started
turn_started
user_message
assistant_message
action_started
action_completed
observation
verification_started
verification_completed
compaction_created
turn_completed
turn_aborted
thread_closed
```

这些事件由 Harness 定义。模型只能产生消息内容或提出 action，不能任意创造新的系统事件类型。

例如：

```text
模型提出命令
→ Harness 持久化 action_started
→ Environment 执行命令
→ Harness 持久化 action_completed 和 observation
```

它们与普通日志的区别是：

| 普通日志      | 结构化生命周期事件             |
| --------- | --------------------- |
| 主要供人阅读和排障 | 表达可持久化的系统事实           |
| 格式可能随时变化  | 需要稳定 schema 和版本       |
| 不保证完整和可重建 | 用于重新构建 Thread 状态      |
| 不一定有关联 ID | 关联 thread、turn、action |

第一版只建设持续会话需要的最小事件集合，不建设通用 Event Bus、SSE、WebSocket 或 React 实时面板。

### 追加式事实存储

建议第一版采用每个 Thread 一个 JSONL 文件：

- 每个 Item 发生后立即追加；
- 已经发生的事实不覆盖；
- 每条记录带 `schema_version`；
- 写入顺序能够用于状态重建；
- 明确哪些命令参数、工具输出和环境信息允许落盘。

完整记录属于 `ThreadStore`。Compaction 摘要和 replacement history 也是可追溯的 Item，但不能覆盖原始事实。

### 活动历史重建

再次打开同一个 Thread 时，不应直接把 JSONL 原样塞给模型，而应该：

```text
ThreadStore.load(thread_id)
→ 找到最近的 compaction_created
→ 使用 replacement_history 作为 ActiveHistory 基线
→ 追加 checkpoint 之后的模型可见 Item
→ ContextManager 规范化历史并检查 token 预算
→ 开始新的 Turn
```

如果没有 compaction checkpoint，则从全部模型可见 Item 重建 `ActiveHistory`。这样可以把“完整保存了什么”和“模型当前使用的活动历史”分开。

### 可替换、可测试的组件边界

建议保持 mini-SWE-agent 现有的简单组合风格：

```text
Agent Loop：决定下一步做什么
Model：产生回复和 action
Environment：执行 action
ThreadStore：保存完整事实
ActiveHistory：保存当前模型可见历史
ContextManager：规范化活动历史并管理 token 预算
Compactor：生成交接摘要和 replacement history
Verifier：判断任务是否真的完成
EventSink：接收最小生命周期事实
```

这些组件应保持职责单一，通过简单协议组合，不把存储、压缩、验证和 UI 全部塞进 `DefaultAgent`。

## 不属于首期核心范围的能力

以下能力有价值，但不属于当前 P0 和 P1。它们应在持续会话、上下文管理和验证式退出稳定后再建设。

| 后续能力                       | 解决的问题                    | 为什么暂不作为核心能力                       |
| -------------------------- | ------------------------ | --------------------------------- |
| Action Checkpoint 与执行中异常恢复 | action 执行时崩溃后，判断是否可以安全继续 | 处理的是更窄的中断窗口，且涉及副作用和幂等性            |
| 完整 Trace 与实时事件流            | 调试、费用统计、流式输出和 React 面板   | 属于可观测性产品化，不是持续会话的前提               |
| `ActionPolicy / Sandbox`   | 限制文件、网络、进程和凭据访问          | 涉及操作系统安全，不能用简单规则宣称完成              |
| 跨 Thread 长期记忆 / RAG        | 新会话复用旧会话经验               | 必须先有稳定 Thread 事实源和 ContextManager |
| 多 Agent 与更多工具              | 并行处理和扩大任务覆盖范围            | 会放大现有状态、恢复、观测和安全问题                |

### Action Checkpoint 到底解决什么

持续会话解决的是：

> 重新打开同一个 Thread，从持久化 Item 或最近 replacement history 重建 `ActiveHistory`，然后开始新的 Turn。

Action Checkpoint 解决的是另一个问题：

> 如果进程在命令执行后、observation 持久化前崩溃，继续运行时怎样判断这条命令是否应该重跑？

例如：

```text
持久化 action_started
→ 命令修改了本地文件
→ 进程崩溃
→ 没有 action_completed 和 observation
```

再次启动后只能确认命令曾经开始，不能确认它是否完整执行。安全做法是把 action 标记为 `unknown`，检查当前工作区，并根据 action 是否有副作用决定是否允许重试；不能静默重跑。

Action Checkpoint 不是文件系统快照，也不自动回滚本地修改。第一版持续会话只承诺从已经持久化的稳定边界继续，不承诺精确恢复执行到一半的 Shell 进程。

### 完整实时事件流与最小事件的区别

P0 需要的最小结构化事件只服务于会话持久化、状态重建和上下文管理。

后续完整 Trace 才进一步回答：

- 当前执行哪个 Turn 和 action；
- 模型调用次数、token 和费用；
- 命令的实时增量输出；
- 为什么触发压缩、验证或重试；
- Agent 为什么成功、失败或停止；
- 如何通过 SSE 或 WebSocket 驱动前端面板。

因此，不应为了未来 UI 先建设庞大的事件总线。先稳定核心生命周期事实，再扩展可观测性事件。

## 推荐实施拆分

### 阶段 A：持续会话基础

```text
Thread / Turn / Item 数据模型
+ 稳定 ID 和 schema_version
+ 最小生命周期事件
+ JSONL 追加式 ThreadStore
+ ActiveHistory
+ ContextManager 历史规范化
+ 重新打开同一个 Thread 后继续新的 Turn
```

阶段 A 暂时不调用模型压缩。`ContextManager` 只需要从持久化 Item 重建并规范化完整活动历史，保证 tool call / tool result 配对，并截断特别长的 observation。

### 阶段 B：Verification-gated Exit

```text
Verifier 协议
+ VerificationResult
+ 固定验收命令
+ 失败结果返回当前 Turn
+ 全部通过后才允许成功退出
```

### 阶段 C：Context Compaction

```text
token 预算
+ 压缩触发器
+ Codex 风格的交接摘要提示词
+ replacement history
+ compaction_created checkpoint
+ 从最近 replacement history 加后续 Item 重建 ActiveHistory
```

### 后续任务

```text
Action Checkpoint
→ 完整 Trace / React 面板
→ Sandbox / Policy
→ 跨 Thread 长期记忆
→ 多 Agent
```

## 最终目标

这次 Harness 扩展不是为了堆叠更多抽象，而是解决两个明确的用户问题：

```text
长期、可信地协作
├── 同一个会话可以持续工作
│   ├── 完整保存历史
│   └── 历史超过预算时，用摘要替换较早活动历史
└── Agent 不能未经验证就宣布完成
```

对应的架构职责是：

```text
ThreadStore：保存完整事实
ActiveHistory：保存当前模型可见历史
ContextManager：规范化活动历史并管理 token 预算
Compactor：生成交接摘要和 replacement history
Agent Loop：决定下一步做什么
Environment：执行 action
Verifier：判断是否真的完成
EventSink：传播最小生命周期事实
```

在 P0 和 P1 稳定之前，不应把 Action Checkpoint、实时 UI、长期记忆或多 Agent 混入首期目标。

## 参考

以下链接固定到本次调研使用的 Codex 源码提交 `7781f0a5a80c29d23beccda7be027d6032bf31c8`：

- [Codex Thread / Turn 定义](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs)
- [Codex ThreadItem 定义](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/app-server-protocol/src/protocol/v2/item.rs)
- [Codex Turn 构造模型输入](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/session/turn.rs#L365-L390)
- [Codex ContextManager 与历史规范化](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/context_manager/history.rs#L164-L223)
- [Codex token 预算与压缩阈值](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/session/context_window.rs#L23-L90)
- [Codex Compaction 实现](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/compact.rs#L245-L398)
- [Codex Compaction Prompt](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/prompts/templates/compact/prompt.md)
- [Codex Replacement History 构造](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/compact.rs#L644-L733)
- [Codex Rollout Reconstruction](https://github.com/openai/codex/blob/7781f0a5a80c29d23beccda7be027d6032bf31c8/codex-rs/core/src/session/rollout_reconstruction.rs#L114-L187)
