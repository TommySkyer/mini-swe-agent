# 从 Python 到 Agent：基于 mini-SWE-agent 的初步认识

## 先说我现在的理解

刚接触一个 Python 项目时，比较容易把 Python、解释器、venv、uv、依赖包混在一起。实际上它们不在同一层：

- Python 是一门语言；
- CPython 是最常见的 Python 实现，也是我们平时所说的 Python 解释器；
- `.py` 文件是源码，要交给解释器执行；
- `.venv` 是当前项目自己的 Python 运行环境；
- `../../../pyproject.toml` 描述项目和依赖；
- `uv` 负责准备环境、安装依赖和运行命令。

因此，一个 Python 项目能跑起来，大致是这条链路：

```text
Python 源码
  + Python 解释器
  + 当前项目安装的依赖
  + 配置、环境变量等运行参数
  = 一个正在运行的 Python 进程
```

这和 Go、Java 的顶层思路并没有完全不同，差别主要是工具的名字和交付方式。

## 当前项目是怎么跑起来的

这个仓库要求 Python 3.10 及以上版本，要求写在根目录的 `../../../pyproject.toml` 中：

```toml
requires-python = ">=3.10"
```

在本地开发时，可以先执行：

```bash
uv sync
```

它会读取 `../../../pyproject.toml` 和 `../../../uv.lock`，准备 `.venv`，并把需要的依赖装进去。之后可以先看一下项目的命令行帮助：

```bash
uv run mini --help
```

这里的 `uv run` 可以理解成“在当前项目对应的 Python 环境里执行后面的命令”。这样不用太操心当前终端到底激活了哪个虚拟环境。

`mini` 不是操作系统自带的命令。它在 `../../../pyproject.toml` 里有明确映射：

```toml
[project.scripts]
mini = "minisweagent.run.mini:app"
```

也就是说，运行 `mini` 时，最后进入的是 `../../../src/minisweagent/run/mini.py` 中的 `app`。这个 `app` 是一个 Typer 对象，Typer 会把 Python 函数和函数参数转换成命令行程序。

项目还支持下面这种启动方式：

```bash
uv run python -m minisweagent
```

这种方式会寻找 `minisweagent/__main__.py` 并执行。两种方式最后都会进入默认的 CLI 装配逻辑，只是入口写法不同。

实际执行 Agent 时还需要模型名称和相应的 API Key，例如：

```bash
uv run mini -m <模型名称> -t "检查当前项目"
```

模型服务是项目之外的依赖。如果解释器和包都正常，但没有配置模型或密钥，项目仍然无法完成模型调用。这属于运行配置问题，不属于 Python 语法问题。

## `.venv` 到底隔离了什么

虚拟环境不是虚拟机，也不是容器。它只是项目目录下的一套 Python 环境，通常包含：

```text
.venv/
├── bin/python
├── bin/pytest
└── lib/python3.x/site-packages/
```

其中：

- `bin/python` 是这个环境使用的 Python 解释器入口；
- `bin` 下还会出现由依赖安装进来的命令；
- `site-packages` 保存当前环境安装的第三方包。

它主要解决依赖冲突。例如项目 A 需要某个包的 1.x，项目 B 需要 2.x，两边各用自己的 `.venv`，互相不会覆盖。

激活虚拟环境常见的写法是：

```bash
source .venv/bin/activate
```

激活以后，终端会优先找到 `../../../.venv/bin/python`。不过使用 uv 时，也可以直接写 `uv run ...`，由 uv 帮忙选择环境。两种方式的目标一样，都是确保命令在本项目环境中运行。

遇到环境问题时，我觉得最有用的不是反复重装，而是先确认“现在到底在用谁”：

```bash
which python
python --version
uv run python -c "import sys; print(sys.executable)"
```

最后一条会明确打印 `uv run` 实际使用的解释器路径。

## `../../../pyproject.toml`、`../../../uv.lock` 和已安装依赖

这三个东西容易混淆，但职责不同。

### `../../../pyproject.toml`

它是项目声明文件，不是 Python 源码。当前项目主要在里面声明：

- 项目名称是 `mini-swe-agent`；
- Python 版本至少为 3.10；
- 运行需要 `pyyaml`、`jinja2`、`pydantic`、`litellm`、`typer` 等依赖；
- `mini` 等命令对应哪个 Python 对象；
- setuptools 怎么从 `src` 目录发现包；
- pytest、Ruff 等开发工具的配置。

它比较像 Go 项目的 `go.mod`，也承担了一部分 Java 项目中 `pom.xml` 或 `build.gradle` 的职责。

### `../../../uv.lock`

`../../../pyproject.toml` 中的版本要求可能比较宽，比如 `pydantic >= 2.0`。为了让不同机器尽量得到相同的依赖组合，uv 会把解析后的具体版本、间接依赖和文件哈希写进 `../../../uv.lock`。

可以先这样记：

```text
pyproject.toml：项目希望使用什么
uv.lock：这次解析后准确使用什么
.venv：本机实际已经安装了什么
```

一般不手动修改 `../../../uv.lock`。依赖声明变化后，由 uv 重新计算它。

### 直接依赖和间接依赖

`../../../pyproject.toml` 里列出的通常是项目直接使用的依赖。但这些依赖还会依赖其他包，所以 `../../../uv.lock` 往往很长。长并不代表这个项目手写了几百个依赖，只是完整的依赖树被记录下来了。

## Python 代码组织里先认识这些就够了

### 模块、包和 `import`

一个 `.py` 文件通常就是一个模块。包含 `__init__.py` 的目录可以作为包的一部分。这个项目采用 `src` 布局：

```text
src/
└── minisweagent/
    ├── agents/
    ├── models/
    ├── environments/
    ├── run/
    └── __init__.py
```

安装项目后，代码里可以写：

```python
from minisweagent.agents.default import DefaultAgent
```

`src` 只是源码目录，真正的 import 包名是 `minisweagent`。这种布局能避免程序意外从仓库根目录导入一份没有正确安装的代码。

### 动态类型和类型注解

Python 的变量不需要提前声明类型：

```python
task = "修复测试"
```

当前项目仍然写了很多类型注解，例如：

```python
def run(self, task: str = "", **kwargs) -> dict:
```

它说明 `task` 期望是字符串，返回值期望是字典。类型注解主要帮助阅读、编辑器检查和静态分析，Python 运行时默认不会像 Java、Go 编译器那样严格检查所有注解。

### Protocol 与面向接口编程

`minisweagent/__init__.py` 定义了 `Agent`、`Model` 和 `Environment` 三个 Protocol。它们更像“一个对象至少要提供哪些方法”的约定。

比如环境只要能提供 `execute`、`get_template_vars` 和 `serialize` 等方法，就可以被 Agent 使用。具体对象不一定非要继承某个共同父类。这是 Python 的鸭子类型：重点是对象能做什么，而不是它在继承树上叫什么。

对照来看：

- Go 的 interface 由方法集合隐式满足；
- Python 的 Protocol 也强调结构是否匹配，但运行时依然比较动态；
- Java interface 通常需要类显式声明 `implements`。

### 异常

Python 用 `raise` 抛出异常，用 `try/except` 处理。这个项目里异常不只代表程序坏了，也用来表示 Agent 流程发生了变化。

例如 `Submitted` 表示 Agent 已经提交结果，`LimitsExceeded` 表示达到步数或费用限制，`FormatError` 表示模型输出没有满足工具调用格式。`DefaultAgent.run()` 会区分这些情况，决定继续循环、正常退出，还是把真正未处理的错误继续向上抛。

## Python 与操作系统的边界

Agent 本身运行在 Python 进程中，但它执行 Bash 命令时，会通过 `subprocess.Popen` 创建新的子进程。大致关系是：

```text
mini 命令
  └── Python 进程
      ├── 调用远程模型 API
      └── 启动 shell 子进程执行 Bash
```

所以 `ls`、`git`、`pytest` 等命令并不是 Python 语言提供的，而是操作系统环境中已有的程序。Python 只负责启动它们、等待结果，并读取退出码和输出。

当前 `LocalEnvironment` 每次动作都会新建一个 shell 进程。上一次命令里的 `cd`、临时环境变量不会自动保留到下一次，这也是默认提示词中特别强调的一点。

## 为什么 Agent 项目常用 Python

Agent 的主要耗时通常在等待模型网络响应、执行外部命令和读写文件，并不全是在本机做大量 CPU 计算。Python 在这些场景中速度通常够用，而且有几个现实优势：

- 模型 SDK 和数据处理工具比较齐全；
- 写法简短，适合快速调整提示词和控制流程；
- 函数、字典和对象组合灵活；
- 研究代码和工程代码之间迁移方便。

这不等于 Python 在任何方面都更合适。如果是高并发网关、对内存和延迟要求很严的常驻服务，Go 可能更省心；如果要接入成熟的企业系统，Java 的类型体系和生态可能更稳。Agent 也可以采用 Python 负责编排，Go、Java、Rust 或独立服务负责重计算和基础设施。

## 和 Go、Java 放在一起看

| 问题 | Python | Go | Java |
| --- | --- | --- | --- |
| 源码 | `.py` | `.go` | `.java` |
| 主要执行方式 | 解释器运行 | 编译为原生程序 | 编译为字节码后由 JVM 运行 |
| 项目声明 | `../../../pyproject.toml` | `go.mod` | `pom.xml` / `build.gradle` |
| 依赖锁定 | `../../../uv.lock` 等 | `go.sum` | 由构建工具和锁定策略决定 |
| 项目隔离 | `.venv` | module 解析与构建边界 | classpath 与构建工具 |
| 接口习惯 | 鸭子类型、Protocol | interface | interface |
| 错误表达 | 异常 | 显式 `error` 返回值 | 异常 |
| 常见交付物 | 源码、依赖和解释器环境 | 原生二进制 | JAR 与 JVM |

我的直观感觉是：Go 把较多复杂性放到了编译期和单一工具链里；Java 把复杂性放在 JVM、类型系统和构建生态里；Python 则允许运行时更灵活，所以环境和依赖边界需要开发者自己看得更清楚。

## 目前适合的阅读顺序

第一次读这个项目，不需要马上研究 CPython 内存管理、GIL 或所有模型供应商。先把主链路走通更重要：

1. 看 `../../../pyproject.toml`，知道版本、依赖和 CLI 入口。
2. 看 `../../../src/minisweagent/run/hello_world.py`，理解最小的对象组合。
3. 看 `../../../src/minisweagent/run/mini.py`，理解正式 CLI 如何读取配置并组装对象。
4. 看 `agents/default.py`，理解 Agent Loop。
5. 看 `environments/local.py`，理解 Bash 怎么被执行。
6. 看 `models/litellm_model.py`，理解模型调用和动作解析。
7. 最后结合测试，确认异常、退出和边界情况。

这一阶段只要能回答下面几个问题，就算已经建立起第一版认识：

- 当前命令实际使用哪个 Python？
- 依赖声明、锁定和安装分别在哪里？
- `mini` 命令最终进入哪个函数或对象？
- Agent、Model、Environment 各自负责什么？
- 模型给出的 Bash 命令最终由谁执行？

后面再遇到陌生 Python 项目，也可以按同样的顺序先找解释器、项目声明、依赖环境、启动入口和外部配置。具体框架会变，但这几个边界基本不会变。
