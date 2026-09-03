# Python 项目基架入门

这份笔记只讲清楚：Python 解释器、标准库、项目源码、第三方依赖和项目命令分别放在哪里，以及 `.venv`、pip、uv、`pyproject.toml`、`uv.lock` 如何把它们组织起来。

## 一张表先看懂

| 名字 | 说人话 |
|---|---|
| Python | 真正运行代码的程序，相当于发动机 |
| 标准库 | Python 自带的代码，例如 `typing`、`json`、`pathlib` |
| PyPI | 网上存放第三方 Python 包的仓库，类似 Maven Central |
| 第三方包 | 别人写好的代码，例如 Pydantic、Requests |
| `.venv` | 当前项目专用的 Python 环境 |
| `site-packages` | 当前虚拟环境安装第三方包实际代码的位置 |
| `.venv/bin` | 当前虚拟环境的 Python 和命令行启动入口 |
| `src/` | 当前项目自己的源码 |
| pip | 传统的第三方包安装工具 |
| uv | 管环境、装依赖、锁版本、运行命令的项目工具 |
| `pyproject.toml` | 项目声明“我需要什么” |
| `uv.lock` | uv 算出的所有精确依赖版本 |

它们这样配合：

```text
pyproject.toml：项目需要 pydantic >= 2
        ↓
uv 解析依赖，把精确结果写入 uv.lock
        ↓
uv 从 PyPI 下载需要的包
        ↓
安装到当前项目的 .venv
        ↓
项目使用 .venv 里的 Python 运行
```

## 一个项目通常长这样

```text
my-project/
├── pyproject.toml   项目信息和直接依赖
├── uv.lock          所有依赖的精确版本
├── .venv/           本机的项目运行环境
├── src/             项目代码
└── tests/           测试代码
```

通常提交到 Git：

```text
pyproject.toml、uv.lock、src/、tests/
```

通常不提交：

```text
.venv/、.env、__pycache__/
```

`.venv` 可以重建；`.env` 经常存放 API Key，不能提交。

## 代码实际来自三个位置

以当前 mini-SWE-agent 为例：

```python
from typing import Protocol
import dotenv
from minisweagent.utils.log import logger
```

三条导入分别来自：

```text
typing.Protocol
    → 基础 Python 的标准库 typing.py

dotenv
    → .venv/lib/python3.11/site-packages/dotenv/

minisweagent.utils.log
    → 当前项目 src/minisweagent/utils/log.py
```

虚拟环境主要隔离第三方包，并不会为每个项目完整复制一套 Python 标准库。当前项目的 `.venv/bin/python` 使用基础 Python 解释器和标准库，同时加载当前 `.venv` 的第三方包与项目源码。

解释器通过 `sys.path` 保存模块搜索目录。执行 `import` 时，它按这些目录查找；模块第一次加载后会缓存在内存的 `sys.modules` 中，不会在每次调用函数时重新搜索磁盘。

```text
同一个 Python 进程
├── 基础 Python 标准库：typing、json、pathlib
├── .venv 第三方包：dotenv、pydantic、litellm
└── 当前项目源码：minisweagent
```

这些文件不会复制、汇聚到同一个磁盘目录；它们由同一个解释器加载到同一个进程中。

## `.venv` 到底是什么

`.venv` 是当前项目自己的 Python 环境，但不是“完整复制一套 Python”：

```text
.venv/
├── bin/
│   ├── python                         当前环境的 Python 入口
│   ├── pytest                         pytest 命令启动脚本
│   ├── mini                           mini-SWE-agent 命令启动脚本
│   └── activate                       修改当前终端 PATH 的脚本
└── lib/python3.11/site-packages/      第三方包的实际代码
```

代码写：

```python
from pydantic import BaseModel
```

编辑器跳到：

```text
.venv/lib/python3.11/site-packages/pydantic/
```

这是正常的，因为 Pydantic 就安装在当前项目的 `.venv` 里。

### `.venv/bin` 中没有后缀的文件是什么

macOS/Linux 不要求命令带 `.exe` 或 `.py` 后缀。文件具有执行权限，并在第一行用 shebang 指定解释器，就可以直接作为命令运行：

```python
#!/项目路径/.venv/bin/python
```

当前项目的 `.venv/bin/mini` 本质上是一个很短的 Python 启动脚本：

```python
#!/项目路径/.venv/bin/python

from minisweagent.run.mini import app

if __name__ == "__main__":
    app()
```

这个脚本不是手工创建的。当前项目在 `pyproject.toml` 中声明：

```toml
[project.scripts]
mini = "minisweagent.run.mini:app"
mini-swe-agent = "minisweagent.run.mini:app"
mini-extra = "minisweagent.run.utilities.mini_extra:main"
```

`uv sync` 安装当前项目时读取这些配置，自动生成 `.venv/bin/mini` 等启动脚本。冒号左边是模块路径，右边是要调用的 Python 对象：

```text
minisweagent.run.mini:app
        模块路径        对象
```

执行 `mini` 的过程是：

```text
pyproject.toml 声明 mini 命令（安装环境时生成入口）
    ↓
Shell 找到 .venv/bin/mini
    → 第一行指定 .venv/bin/python
    → 导入 src/minisweagent/run/mini.py 中的 app
    → 启动项目
```

同理，`.venv/bin/pytest` 只是 pytest 的命令入口，pytest 的实际代码在 `site-packages/_pytest/`。简单区分：

```text
.venv/bin/                 放“如何启动命令”
.venv/lib/.../site-packages/ 放“第三方包的实际代码”
```

`.venv/bin/python` 通常是基础 Python 解释器的链接或入口。`source .venv/bin/activate` 会把 `.venv/bin` 放到当前终端的 `PATH` 前面，于是输入 `python`、`pytest`、`mini` 时会优先使用当前项目环境中的命令。使用 `uv run mini` 也可以直接在当前项目环境里运行，不必手动激活。

`.venv` 通常可以删除，然后执行 `uv sync` 重新创建。

## pip 和 uv 有什么区别

pip 主要负责安装包：

```bash
python -m pip install pydantic
```

传统流程要自己组合多个工具：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

其中：

```text
venv 创建环境
pip 安装依赖
pytest 运行测试
```

uv 把这些工作整合起来：

```bash
uv sync
uv run pytest
```

简单记：

```text
pip：安装包的工具
uv：管理整个 Python 项目的工具
```

uv 不是 Python 强制要求的，只是现在比较流行、速度也较快。

## `pyproject.toml` 和 `uv.lock`

`pyproject.toml` 写项目的要求：

```toml
[project]
name = "my-project"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "requests",
]
```

它表示需要 Pydantic 2.0 以上，但没有限定具体小版本。

`uv.lock` 保存 uv 最终选中的精确版本，例如：

```text
pydantic == 2.13.4
pydantic-core == 某个精确版本
typing-extensions == 某个精确版本
```

这样你、同事和 CI 执行 `uv sync` 时，会得到同一套依赖。`uv.lock` 不需要手工修改，让 uv 维护。

## 日常只需要记这些 uv 命令

```bash
# 创建或更新 .venv，使它和 uv.lock 一致
uv sync

# 在当前项目环境里运行命令
uv run python
uv run python main.py
uv run pytest

# 添加、删除依赖
uv add requests
uv remove requests
```

`uv run` 和 `uvx` 不一样：

```text
uv run pytest        运行当前项目环境里的 pytest
uvx mini-swe-agent   临时安装并运行一个外部工具
```

## 常见问题

### 1. 每个项目都要有 `.venv` 吗？

不是语言强制要求，但正规开发通常每个项目一个，避免依赖版本互相打架：

```text
项目 B：pydantic 1.x
项目 C：pydantic 2.x
```

### 2. 相同依赖会重复下载吗？

不一定。pip 和 uv 都有机器级缓存，通常不必重新从网络下载。每个项目逻辑上仍有独立环境，uv 会尽量用 Copy-on-Write 或链接减少磁盘重复。

### 3. 为什么不全局安装所有依赖？

因为两个项目可能需要同一个包的不同版本。全局只能放一个版本，升级一个项目可能弄坏另一个项目。

### 4. 一个项目里能混用 pip 和 uv 吗？

能，但容易乱。如果项目已经有 `uv.lock`，优先使用：

```bash
uv sync
uv add xxx
uv remove xxx
uv run ...
```

直接 `pip install xxx` 可能只修改 `.venv`，没有更新 `pyproject.toml` 和 `uv.lock`；下次 `uv sync` 时，这个包可能消失。

### 5. 接手项目时怎么判断用什么？

```text
有 uv.lock             优先使用 uv
有 poetry.lock         优先使用 Poetry
有 Pipfile             可能使用 Pipenv
只有 requirements.txt  通常使用 pip
```

### 6. 当前 mini-SWE-agent 用的是什么？

当前仓库有 `pyproject.toml`、`uv.lock` 和 `.venv`。而且 `.venv/pyvenv.cfg` 记录了 uv 版本，安装包的 `INSTALLER` 也是 `uv`。因此当前环境确实由 uv 创建和安装，不是推测。

日常先用：

```bash
uv sync
uv run pytest
uv run mini
```

## 最后只背七句话

1. Python 是运行代码的程序。
2. 标准库来自基础 Python，项目源码来自 `src/`。
3. `.venv` 是当前项目自己的环境，但通常不会复制整套标准库。
4. 第三方包实际代码安装在 `.venv` 的 `site-packages` 中。
5. `.venv/bin` 主要放 Python 入口和 `pytest`、`mini` 等命令启动脚本。
6. pip 主要负责安装包，uv 负责管理整个项目环境。
7. 看到 `uv.lock`，优先使用 `uv sync` 和 `uv run`。
