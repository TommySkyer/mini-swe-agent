# Python CLI 终端基架：从 `print()` 到 `mini`

这篇只走一条主线：用户在终端输入 `mini` 后，代码到底怎样被找到、解析和执行。

## 先看全链路

```text
用户输入 mini -t "修复问题"
        ↓
pyproject.toml 注册了 mini 命令
        ↓
Python 找到 minisweagent.run.mini:app
        ↓
Typer 解析 -t、--model、--yolo 等参数
        ↓
调用开发者写的 main(...)
        ↓
Rich 负责漂亮地输出
prompt_toolkit 负责多行输入、历史记录、快捷键
        ↓
main() 调用真正的业务代码
```

关键点：**不是 Typer 把函数名变成了 `mini`**。`mini` 这个终端命令由 `pyproject.toml` 注册，Typer 负责接管这个命令的参数和帮助页面。

## 第一层：从 `print()` 开始

Python 自带最基础的终端输入输出：

```python
name = input("你的名字：")
print(f"你好，{name}")
```

这已经是一个 CLI，但参数、帮助、类型校验都要自己处理。

例如用户想运行：

```bash
python app.py --name 小明 --age 18
```

如果只用标准库，就要自己解析 `--name`。Typer 帮我们省掉这部分。

## 第二层：Typer 负责“命令和参数”

最小例子：

```python
import typer

app = typer.Typer()


@app.command()
def main(
    name: str = typer.Option(..., "--name", "-n", help="你的名字"),
    age: int = typer.Option(18, "--age", help="你的年龄"),
) -> None:
    print(f"你好 {name}，你今年 {age} 岁")


if __name__ == "__main__":
    app()
```

现在可以直接运行文件：

```bash
python app.py --name 小明 --age 20
python app.py --help
```

Typer 根据函数签名自动完成：

- 把终端字符串转换成 `str`、`int`、`bool` 等类型；
- 检查必填参数；
- 识别短参数 `-n` 和长参数 `--name`；
- 根据 `help=` 生成 `--help` 页面；
- 参数不合法时显示错误。

`@app.command()` 是装饰器，意思是“把下面这个函数登记为 CLI 命令”。真正的业务逻辑仍然写在函数体里。

### 一个命令和多个子命令

只有一个命令时，可以这样使用：

```bash
mytool --name 小明
```

登记多个命令后，函数名通常成为子命令名：

```python
@app.command()
def hello(name: str) -> None:
    print(f"hello {name}")


@app.command()
def config(key: str, value: str) -> None:
    print(key, value)
```

使用方式变成：

```bash
mytool hello 小明
mytool config api_key abc
mytool --help
mytool hello --help
```

## 第三层：怎样得到 `mini` 这种命令名

当前项目在 `pyproject.toml` 中写了：

```toml
[project.scripts]
mini = "minisweagent.run.mini:app"
mini-extra = "minisweagent.run.utilities.mini_extra:main"
```

语法是：

```text
终端命令名 = "Python模块路径:模块中的对象"
```

因此：

```text
mini
  ↓
导入 minisweagent.run.mini
  ↓
取得其中的 app
  ↓
调用 app，由 Typer 接管
```

自己的项目可以这样搭：

```text
my-cli/
├── pyproject.toml
└── src/
    └── my_cli/
        ├── __init__.py
        └── cli.py
```

`pyproject.toml`：

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "my-cli"
version = "0.1.0"
dependencies = ["typer", "rich", "prompt-toolkit"]

[project.scripts]
mytool = "my_cli.cli:app"

[tool.setuptools.packages.find]
where = ["src"]
```

安装项目后才会生成 `mytool` 命令：

```bash
uv sync
uv run mytool --help
```

激活 `.venv` 后也可以直接运行 `mytool`。本质上，安装工具在 `.venv/bin/` 下生成了一个很小的启动脚本。Shell 能在 `PATH` 中找到它，才可以直接输入命令名。

## 第四层：Rich 负责“显示得好看”

项目中：

```python
from rich.console import Console

console = Console(highlight=False)
console.print("[bold green]Got that, thanks![/bold green]")
```

`print()` 只负责普通文本；`console.print()` 额外支持：

- 颜色和粗体；
- 表格、进度条、分割线；
- 状态动画；
- 更友好的异常和布局。

例如：

```python
from rich.console import Console

console = Console()
console.print("[bold green]成功[/bold green]")

with console.status("处理中..."):
    do_work()
```

Rich 不负责解析 `--model`，也不负责执行业务；它只是显示层。

## 第五层：`_multiline_prompt()` 负责更强的输入体验

最基础的输入是：

```python
task = input("请输入任务：")
```

但 `input()` 主要适合单行。当前项目用 `prompt_toolkit` 做了一个多行输入器：

```python
_history = FileHistory("interactive_history.txt")
session = PromptSession(history=_history, multiline=True)


def multiline_prompt() -> str:
    return session.prompt("")
```

于是它能够提供：

- 多行编辑；
- 上下键查看历史；
- `Ctrl+R` 搜索历史；
- 底部快捷键提示；
- 把历史保存到文件。

`run_task = _multiline_prompt()` 没有神秘机制：它就是等待用户在终端输入一段多行文字，然后把最终字符串赋给 `run_task`。

## `mini` 中实际发生了什么

从下面几个锚点顺着读：

1. `pyproject.toml` 的 `[project.scripts]`：注册终端命令 `mini`。
2. `src/minisweagent/run/mini.py` 的 `app = typer.Typer(...)`：创建 CLI 应用。
3. 同文件的 `@app.command(...)`：登记主命令。
4. `main(...)` 参数里的 `typer.Option(...)`：定义选项、默认值和帮助。
5. `console.print(...)`：用 Rich 输出。
6. `agents/utils/prompt_user.py`：用 prompt_toolkit 实现多行输入。
7. `main()` 后半段：拿到参数后调用 Model、Environment、Agent 等业务代码。

一句话概括：

```text
Typer 搭命令骨架 → Rich 做输出 → prompt_toolkit 做输入 → 你写业务逻辑
```

## 哪些是框架给的，哪些必须自己写

| 能力 | 谁提供 |
|---|---|
| `--help` 页面、参数解析、类型转换、必填校验 | Typer |
| 终端命令名 `mini` 的安装入口 | `pyproject.toml` + setuptools/uv |
| 颜色、粗体、表格、状态动画 | Rich |
| 多行编辑、历史记录、快捷键 | prompt_toolkit |
| 参数叫什么、默认值是什么、帮助文案写什么 | 开发者 |
| 输入之后做什么 | 开发者 |
| 配置如何读取和合并 | 开发者 |
| Agent、Model、Environment 如何装配 | 开发者 |

注意“提示”有三种不同含义：

```text
help 文案       用户执行 --help 时看到的说明
终端 prompt     等待用户键盘输入的问题或输入框
大模型 prompt   发给模型的 system/user 模板
```

它们在中文里都可能被叫作“提示”，但属于完全不同的层。

## 以后自己搭 CLI，只按这个顺序

1. 先写一个普通 `main()`，用 `print()` 验证业务能跑。
2. 用 Typer 把函数参数变成命令行参数。
3. 在 `pyproject.toml` 的 `[project.scripts]` 注册命令名。
4. 执行 `uv sync`，再用 `uv run 命令名 --help` 验证入口。
5. 需要颜色、进度条时再加 Rich。
6. 需要多行输入和历史记录时再加 prompt_toolkit。

最后记住：CLI 不是一个特殊世界。它只是“Shell 找到 Python 入口 → 框架整理输入 → 普通函数执行业务 → 把结果输出到终端”。
