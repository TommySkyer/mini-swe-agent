# Agent、模型 API 与协议适配

## 核心结论

模型本质上接收 token、生成 token；`role`、`content`、`tool_calls` 等字段不是模型天然拥有的结构，而是模型服务商在模型外部定义的 API 协议。

mini-SWE-agent 不会把所有自然语言和命令输出都“理解”为结构化数据。它采用的主要方法是：

> 把无法统一理解的原始内容放进结构化信封，并只对机器必须处理的字段进行解析和校验。

项目中的责任链是：

```text
厂商定义真实 HTTP API
    ↓
LiteLLM 适配不同厂商的请求和响应
    ↓
LitellmModel 把统一模型响应转换为项目内部 action
    ↓
Environment 执行 action，并包装原始执行结果
    ↓
DefaultAgent 维护消息、状态和运行循环
```

## 一、“结构化”需要分层理解

一次 Agent 交互中同时存在多种结构，不能把它们都统称为“HTTP 返回结果”。

| 层次 | 结构情况 | 结构由谁定义 |
|---|---|---|
| HTTP 响应 | 包含状态码、Header、Body | HTTP 协议 |
| 模型 API Body | 通常是带有 `choices`、`message`、`usage` 等字段的 JSON | 模型服务商 |
| 模型的自然语言 `content` | 通常是自由文本，没有稳定业务结构 | 模型生成 |
| 模型的 `tool_calls` | 包含工具名、调用 ID 和 JSON 参数 | Tool Calling 协议和工具 Schema |
| Shell stdout | 本质是任意字符串 | 被 Environment 包装 |
| Agent 内部消息 | 包含 `role`、`content`、`extra`、`actions` 等字段 | mini-SWE-agent |

HTTP 只规定传输层的状态码、Header 和 Body，并不保证 Body 一定是 JSON，更不保证其中的自然语言具有业务结构。模型服务商在 HTTP 之上额外规定请求和响应 JSON，LiteLLM 再把不同厂商的 JSON 适配为统一对象。

因此：

```text
HTTP 结构
    ≠ 模型 API 结构
    ≠ 模型生成内容的业务结构
    ≠ mini-SWE-agent 内部结构
```

## 二、厂商 API 决定对外格式

不同服务商的请求结构并不完全相同。例如，有的接口使用：

```json
{
  "messages": [
    {"role": "user", "content": "你好"}
  ]
}
```

另一些接口可能使用 `contents`、`parts` 或独立的 `system` 字段。

调用真实服务时，外层 JSON 必须符合该服务的 API 规范；`content` 中的问题文本可以自由编写，但不能随意改变厂商要求的字段结构。

模型 API 的一次响应可能类似：

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "我先查看项目目录。",
        "tool_calls": [
          {
            "id": "call_123",
            "function": {
              "name": "bash",
              "arguments": "{\"command\":\"rg --files\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

其中 `content` 是自由文本，而 `tool_calls` 是需要被程序解析的结构化数据。

## 三、Agent 内部格式可以自己设计

Agent 内部可以采用任意结构，但发送给厂商之前必须完成协议转换。

mini-SWE-agent 选择了常见的消息形式：

```json
{"role": "user", "content": "请修复这个问题"}
```

`role` 必须由 Agent 指定，因为 Agent 才知道消息来源：

- `system`：系统规则；
- `user`：用户任务或框架反馈；
- `assistant`：模型回复；
- `tool`：工具执行结果；
- `exit`：mini-SWE-agent 内部使用的结束状态，不会作为普通厂商消息发送。

框架无法仅根据一句“文件不存在”判断它来自用户、模型还是 bash，因此不能从文本内容自动推断 `role`。

mini-SWE-agent 还会在消息中保存内部字段 `extra`，例如：

```python
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "...格式化后的执行结果...",
    "extra": {
        "raw_output": "原始 stdout",
        "returncode": 0,
        "timestamp": 1234567890,
    },
}
```

`extra` 用于轨迹记录、费用统计和 Agent 控制，不属于厂商 API。`LitellmModel` 在发送请求前会删除它，只保留厂商认识的字段。

## 四、LiteLLM 是厂商协议适配层

LiteLLM 的开发者根据各厂商公开的 API 规范，为它们编写确定性的 adapter。它不是在运行时智能猜测协议。

上层统一调用：

```python
litellm.completion(
    model="deepseek/...",
    messages=messages,
    tools=tools,
)
```

LiteLLM 根据模型名中的 provider 前缀选择 adapter：

```text
deepseek/...   → DeepSeek adapter
anthropic/...  → Anthropic adapter
openai/...     → OpenAI adapter
```

adapter 负责：

1. 把统一消息转换为厂商请求；
2. 通过 HTTP 调用厂商 API；
3. 把厂商响应转换为统一响应对象。

DeepSeek 默认走 OpenAI-compatible 接口，不是因为 LiteLLM 智能判断这种协议更合适，而是因为 DeepSeek 提供了该接口，LiteLLM 按照其规范实现了对应 adapter。

项目随后可以统一读取：

```python
response.choices[0].message
response.choices[0].finish_reason
response.model_dump()
```

## 五、LitellmModel 把 tool call 转换为 action

LiteLLM 解决“不同厂商协议”的差异；`LitellmModel` 解决“LiteLLM 统一响应”和“mini-SWE-agent 内部 action”之间的差异。

项目向模型声明一个 Bash 工具：

```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "description": "Execute a bash command",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"}
      },
      "required": ["command"]
    }
  }
}
```

这只是告诉模型“可以生成怎样的工具调用”，并不会执行 Bash。模型可能返回：

```json
{
  "id": "call_123",
  "function": {
    "name": "bash",
    "arguments": "{\"command\":\"rg --files\"}"
  }
}
```

`LitellmModel` 按确定规则完成：

1. 使用 `json.loads()` 解析 `arguments`；
2. 检查工具名必须是 `bash`；
3. 检查参数必须是字典并包含 `command`；
4. 组装项目内部 action。

转换结果为：

```python
{
    "command": "rg --files",
    "tool_call_id": "call_123",
}
```

这里没有智能转换。真正具有智能的是模型决定“下一步应该执行 `rg --files`”；框架只负责解析、校验和组装。

如果模型没有产生 tool call、参数不是合法 JSON、工具名称错误或缺少 `command`，项目会抛出 `FormatError`，把格式错误作为新消息反馈给模型并重试。连续格式错误超过 `max_consecutive_format_errors` 时，Agent 以 `RepeatedFormatError` 退出。

这意味着 Tool Calling 提高了可解析性，但不等于模型永远不会产生错误结构。

## 六、Environment 包装无法统一理解的工具输出

Shell stdout 本质上仍然是无结构字符串。例如：

```text
================ test session starts ================
collected 10 items
10 passed
```

`LocalEnvironment` 不会尝试理解每一种命令的输出，而是把它装入统一信封：

```python
{
    "output": "10 passed\n",
    "returncode": 0,
    "exception_info": "",
}
```

这里的 `output` 仍然是自由文本；真正结构化的是外围的执行状态。发生异常时，信封还会携带异常类型和异常信息。

`LitellmModel` 再使用 observation 模板把结果转换为 `role="tool"` 的消息：

```python
{
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "...包含 returncode 和 output 的格式化文本...",
    "extra": {
        "raw_output": "10 passed\n",
        "returncode": 0,
    },
}
```

因此，项目并没有把任意 stdout 都变成可理解的领域对象，而是保留原文并补充可靠的执行元数据。

## 七、Agent 经典循环

```text
Agent 组装 role/content 消息
    ↓
LiteLLM 转换并调用厂商 HTTP API
    ↓
模型返回 content 和/或 tool_calls
    ↓
LitellmModel 解析、校验并生成 action
    ↓
Environment 执行 bash
    ↓
原始 stdout 被包装并格式化为 role=tool
    ↓
结果追加到消息历史，再次询问模型
```

`DefaultAgent` 不关心具体厂商协议，只依赖项目内部的 `Model` 接口。模型或协议可以替换，而控制循环保持稳定。

## 八、任务如何结束

mini-SWE-agent 在提示词中告诉模型：任务完成后，调用 Bash 工具执行：

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

它不是要求模型在普通 `content` 中回复这个字符串。正常链路是：

```text
模型认为整个任务完成
    ↓
生成 bash(command="echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")
    ↓
Environment 执行命令
    ↓
stdout 第一行出现结束标识，且 returncode 为 0
    ↓
Environment 抛出 Submitted
    ↓
Agent 添加 role=exit 消息并停止循环
```

这是一个简单的 in-band signal：结束信号通过普通工具和 stdout 通道传递。它表示模型的“完成意图”，不证明任务真的正确完成。

### `finish_reason` 不等于任务完成

模型 API 可能返回：

```json
{"finish_reason": "stop"}
```

或：

```json
{"finish_reason": "tool_calls"}
```

它们只说明本次模型生成为什么停止：文本自然结束、需要调用工具、达到长度限制等。它们不表示整个软件任务已经完成。

```text
finish_reason="stop"
    = 这一次模型响应结束

Submitted / role="exit"
    = 整个 Agent 运行结束
```

如果把每次 `finish_reason="stop"` 都当作任务完成，模型只要某一轮没有正确调用工具，Agent 就会被错误终止。

## 九、结束协议的可靠性边界

结束命令写在较早的提示词中，模型可能因为上下文过长、指令稀释、上下文截断或自身能力不足而忘记执行它。

如果模型忘记结束协议，但仍持续产生合法 Bash 调用，Agent 不会得到 `Submitted`，只能继续循环。当前框架主要依靠以下机制兜底：

- `step_limit`：限制模型调用步数；
- `cost_limit`：限制费用；
- `wall_time_limit_seconds`：限制运行时间；
- `max_consecutive_format_errors`：限制连续格式错误；
- `InteractiveAgent`：允许用户确认结束或手动中断。

如果步数、费用和时间限制全部为 `0`，这些限制表示禁用；模型又始终产生合法动作但不提交，那么理论上可能持续运行。

还必须区分：

```text
完成意图检测
    模型声明“我做完了”

完成质量验证
    测试、评估器或人类确认“确实做对了”
```

`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 只完成前者。结构正确也只代表“机器能够解析”，不代表命令合理、测试真实通过或任务结果正确。

更可靠的系统可以组合以下措施：

1. 提供独立的结构化 `finish` 工具，而不是通过 Bash stdout 传递暗号；
2. 在靠近上下文末尾的位置周期性刷新结束协议；
3. 压缩上下文时固定保留任务目标、工具规则和结束协议；
4. 始终启用步数、费用或运行时间看门狗；
5. 在接受完成之前运行确定性测试或外部评估；
6. 让控制器维护 `WORKING → READY_TO_FINISH → FINISHED` 等明确状态，而不把全部终止责任交给模型。

即使使用结构化 `finish` 工具，模型仍可能忘记调用或过早调用。因此，Schema 解决的是格式可靠性，外部验证解决的才是结果可靠性。

## 十、协议变化时的影响范围

分层不能让协议永远不变，但可以限制修改范围：

```text
某厂商 API 变化     → 修改 LiteLLM 对应 adapter
LiteLLM 接口变化    → 修改 LitellmModel
项目 action 变化    → 修改 LitellmModel 与相关 Environment
项目内部消息变化    → 才可能修改 DefaultAgent
```

因此，适配层的价值不是消灭变化，而是隔离变化。

## 最终心智模型

```text
模型负责产生决策，但可能犯错或忘记协议
厂商 API 负责 HTTP 之上的请求和响应结构
LiteLLM 负责不同厂商之间的协议适配
LitellmModel 负责校验 tool call 并生成内部 action
Environment 负责执行 action，并包装无结构输出
DefaultAgent 负责消息、限制、异常和循环控制
Submitted 只表达完成意图，测试或评估才验证完成质量
```
