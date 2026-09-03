# mini-SWE-agent 架构与运行机制初读

## 项目第一印象

mini-SWE-agent 的目标不是做一个功能很多的 Agent 框架，而是保留软件工程 Agent 最基本的循环：模型看任务，给出 Bash 命令，环境执行命令，再把结果返回给模型。一直重复，直到任务完成或达到限制。

从代码量和目录来看，项目有意把不同职责拆开：

```text
src/minisweagent/
├── agents/          Agent 循环和交互方式
├── models/          模型调用、动作解析、消息格式转换
├── environments/    Bash 命令在哪里以及怎样执行
├── config/          默认提示词和各组件配置
├── run/             CLI 和其他运行入口
├── utils/           日志、序列化等通用代码
├── exceptions.py    流程中使用的异常
└── __init__.py      核心 Protocol 和全局路径
```

第一次读时，最重要的不是每个模型供应商有什么差别，而是先抓住 Agent、Model、Environment 三个对象。

## 三个核心组件

### Agent：控制循环

Agent 负责维护消息历史，并决定什么时候调用模型、什么时候执行动作、什么时候结束。核心实现是 `DefaultAgent`。

它并不知道某个 API 的具体请求格式，也不直接调用 `subprocess`。它只依赖 Model 和 Environment 提供约定的方法。因此它更像应用层的流程控制器。

### Model：把语言模型接进循环

Model 主要负责：

- 把消息历史发送给模型服务；
- 从模型响应中解析 Bash tool call；
- 把命令执行结果格式化成模型能继续理解的消息；
- 记录调用费用和原始响应等信息。

默认使用的是 `LitellmModel`，它通过 LiteLLM 兼容不同模型供应商。项目也提供 OpenRouter、Portkey 等其他实现。

### Environment：执行动作

Environment 接收解析好的动作并执行。最容易理解的是 `LocalEnvironment`，它直接在本机通过 shell 执行命令。

项目同时提供 Docker、Singularity、bubblewrap 等环境。换 Environment 的意义是改变命令“在哪里执行”和“隔离到什么程度”，不需要因此改写 Agent Loop。

三个组件的关系可以简单写成：

```text
                 ┌──────────────┐
任务和配置 ─────>│    Agent     │
                 │  保存历史并循环 │
                 └──────┬───────┘
                        │ messages
                        v
                 ┌──────────────┐
                 │    Model     │
                 │ 推理并产生动作  │
                 └──────┬───────┘
                        │ action
                        v
                 ┌──────────────┐
                 │ Environment  │
                 │ 执行 Bash 命令 │
                 └──────┬───────┘
                        │ output
                        └──────────> 回到 Agent，再进入下一轮
```

## 从 `mini` 命令到 Agent 运行

项目在 `../../../pyproject.toml` 中把 `mini` 映射到 `minisweagent.run.mini:app`。因此默认入口是 `../../../src/minisweagent/run/mini.py`。

入口大致做了这些事：

1. Typer 读取模型名称、任务、运行模式、配置文件和输出路径等参数。
2. 加载默认的 `config/mini.yaml`，再把命令行参数合并进去。
3. 如果命令行没有任务，就在终端询问用户。
4. 通过 `get_model()` 创建 Model。
5. 通过 `get_environment()` 创建 Environment，默认是 local。
6. 通过 `get_agent()` 创建 Agent，默认是 interactive。
7. 调用 `agent.run(task)`。

这里的 `get_model`、`get_environment` 和 `get_agent` 都支持短名称到类路径的映射，也支持传入完整类路径。因此 CLI 负责的是对象装配，而不是 Agent 的核心逻辑。

`run/hello_world.py` 更适合第一次阅读。它直接写出了下面的关系：

```python
agent = DefaultAgent(
    LitellmModel(model_name=model_name),
    LocalEnvironment(),
    ...
)
agent.run(task)
```

这几行基本就是整个项目的骨架。正式的 `mini.py` 主要是在这个骨架外面增加配置、交互和实现选择。

## Agent Loop

核心循环在 `DefaultAgent.run()` 中。去掉保存和异常处理后，可以粗略理解为：

```python
messages = [system_message, task_message]

while True:
    model_message = model.query(messages)
    actions = model_message["extra"]["actions"]
    outputs = [environment.execute(action) for action in actions]
    observation_messages = model.format_observation_messages(model_message, outputs)
    messages.extend(observation_messages)

    if last_message_is_exit:
        break
```

真实代码把一轮拆成了几个较小的方法：

- `run()`：初始化并反复执行 step；
- `step()`：先 query，再 execute_actions；
- `query()`：检查限制并调用模型；
- `execute_actions()`：执行动作并追加 observation；
- `save()`：把当前状态保存为 trajectory。

这个循环没有工作流图、任务 DAG 或复杂状态机。它的状态主要就是 `self.messages`、调用次数、累计费用和开始时间。

## 一轮数据是怎么流动的

### 初始消息

运行开始时，Agent 会根据配置中的 `system_template` 和 `instance_template` 生成两条消息：

```text
system：说明 Agent 的角色和基本行为
user：放入当前任务以及执行要求
```

模板使用 Jinja 渲染。模板变量来自 Agent 配置、Model、Environment、环境变量以及本次任务。这使提示词可以使用操作系统类型、任务文本、累计费用等运行信息。

### 模型响应

`LitellmModel.query()` 把历史消息交给模型，同时声明一个 Bash 工具。模型返回 tool call 后，Model 把它解析成统一的动作字典，放在消息的 `extra.actions` 中。

`extra` 还保存原始模型响应、费用和时间戳。这些内容不直接发回模型，但会写进 trajectory，方便之后排查。

### 命令执行结果

Environment 执行动作后返回一个字典，主要包含：

```text
output          标准输出和标准错误合并后的内容
returncode      进程退出码
exception_info  超时或执行异常等附加信息
```

Model 再把这个结果格式化为 observation/tool message，追加到消息历史中。下一轮模型调用就能看到刚才命令执行的结果。

## Bash 命令怎样被执行

`LocalEnvironment` 最终使用 `subprocess.Popen` 启动 shell 子进程。它有几个比较明确的行为：

- 使用 `shell=True`，所以动作内容是普通 shell 命令；
- 标准错误合并到标准输出；
- 默认超时为 30 秒；
- 超时后尽量终止整个进程组，避免遗留子进程；
- 每个动作启动一个新的 shell，不保留上一次 shell 的临时状态。

最后一点会直接影响模型写命令。例如一轮执行 `cd /tmp`，下一轮不会自动留在 `/tmp`。需要写成一条完整命令，或者每次显式指定目录。

本地环境的风险也比较直接：模型产生的命令会在本机执行，并拥有当前用户的权限。默认的 `InteractiveAgent` 使用 confirm 模式，就是为了在执行未放行的命令前让用户确认。如果切成 yolo，使用者需要自己承担更大的安全风险。

## Agent 怎么结束

默认提示词要求模型在完成任务后单独执行：

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

`LocalEnvironment._check_finished()` 会检查输出第一行是不是这个标记。如果命令成功，就抛出 `Submitted`，并把后续输出作为提交内容。

这里使用异常不是因为程序出错，而是为了从 Environment 的深层调用快速跳回 Agent Loop。项目中几种重要的流程异常包括：

- `Submitted`：任务完成；
- `LimitsExceeded`：达到步数或费用限制；
- `TimeExceeded`：达到墙钟时间限制；
- `FormatError`：模型没有按要求产生合法动作；
- `UserInterruption`：用户中断、拒绝或补充了任务。

它们都继承自 `InterruptAgentFlow`。`DefaultAgent.run()` 会把异常携带的消息追加到历史中，再根据最后一条消息是否为 exit 判断退出还是继续。

真正没有预期到的普通异常会被记录后再次抛出。这类情况才更接近程序故障。

## DefaultAgent 和 InteractiveAgent

`DefaultAgent` 只包含最小循环。`InteractiveAgent` 继承它，增加终端输出、人工确认和中断处理。

它支持三种模式：

- `confirm`：模型给出的非白名单命令需要用户确认；
- `yolo`：模型命令直接执行；
- `human`：由用户输入命令，Agent 负责执行并保留在消息历史中。

这部分采用继承的原因比较直观：核心循环还是同一个，只是在 query、step、execute_actions 和 add_messages 等位置加人机交互。这样 `DefaultAgent` 不需要知道终端提示、快捷命令或确认规则。

## 配置如何进入程序

默认配置是 `../../../src/minisweagent/config/mini.yaml`，主要分成三块：

```yaml
agent:       # 提示词、限制、交互模式
environment: # 环境变量、工作目录、超时等
model:       # 模型参数、观察结果模板等
```

CLI 参数会被转换成相同的嵌套字典，然后和 YAML 配置递归合并。比如：

```bash
uv run mini -c mini.yaml -c model.model_kwargs.temperature=0.5
```

第二个 `-c` 不是文件，而是一条键值配置，它会覆盖默认配置中的相应字段。

各组件的配置最后通过 Pydantic 模型校验。这样 YAML 和命令行依然比较灵活，同时明显的字段错误能在对象创建阶段被发现。

## Trajectory 是什么

Agent 每一轮都会在 `finally` 中调用 `save()`。只要配置了输出路径，就会写出一个 JSON trajectory。

里面主要有：

- 完整的消息历史；
- 模型调用次数和累计费用；
- Agent、Model、Environment 的实际类型和配置；
- 退出状态和最终提交；
- 项目版本和 trajectory 格式版本。

所以 trajectory 不只是日志，更接近一次运行的可检查记录。模型原始响应、动作、命令输出都能沿消息历史找到。任务中途报错时，已经发生的步骤通常也能被保留下来。

## 目前看到的设计特点

### 好理解的地方

- 核心 Loop 很短，调用关系基本是线性的；
- Model 和 Environment 可以独立替换；
- Bash 作为统一动作，避免为每个工具都写一套接口；
- 配置和提示词在 YAML 中，调整行为不一定要改 Python；
- trajectory 贯穿整个运行过程，便于复盘。

### 需要留意的地方

- Bash 很通用，但本地直接执行也意味着较大的安全边界；
- 消息历史线性增长，长任务可能受到上下文窗口限制；
- 动态导入和字典配置很灵活，不过出错时间比静态语言更晚；
- 异常既表示正常流程，也表示错误，阅读时要先看异常类型；
- 默认每条命令是独立 shell，不能假设终端状态持续存在。

这个项目的取舍比较明确：优先让代码少、流程直观，而不是内置复杂的规划、记忆和工作流能力。

## 如果要扩展，先判断改哪一层

可以先按职责判断：

- 想修改循环、增加审核步骤或记忆：改 Agent；
- 想接新模型服务或改变工具调用解析：改 Model；
- 想把命令放进容器、远程机器或沙箱：改 Environment；
- 只是换提示词、限制和默认实现：优先改 Config；
- 想提供一种独立的启动方式：新增 Run Script。

项目使用 Protocol 描述三个核心组件的方法形状，所以自定义类重点是满足协议，而不是一定要继承现有实现。

## 建议的源码阅读顺序

按第一次读项目的节奏，我觉得可以这样看：

1. `run/hello_world.py`：先看最小装配。
2. `agents/default.py`：看最核心的循环。
3. `environments/local.py`：看命令执行和完成判断。
4. `models/litellm_model.py`：看模型响应如何变成动作。
5. `config/mini.yaml`：对照默认提示词和模板。
6. `run/mini.py`：最后看完整 CLI 如何把配置和组件组装起来。
7. `agents/interactive.py`：理解人机确认是在核心循环上怎样扩展的。

目前我对这个项目的概括是：它不是靠复杂框架完成 Agent，而是用普通 Python 循环把模型调用和 shell 执行接起来。理解 `query → action → execute → observation` 这一圈后，其他代码大多是在替换其中某个环节，或者补配置、交互和记录能力。
