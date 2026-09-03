# Agent 的工作目录与项目锚点

## 核心结论

mini-SWE-agent 不会自动识别 Git 根目录。默认情况下，**在哪个目录启动 `mini`，Agent 就在哪个目录执行 bash 命令**。

这个目录叫 `cwd`（Current Working Directory，当前工作目录）。它由 Shell 维护，启动 `mini` 时由操作系统继承给 `mini` 进程。

```bash
cd /Users/zhebin.fan/codestore/link-source-track-platform
mini
```

此时 mini-SWE-agent 程序虽然安装在别处，但它的工作目录是：

```text
/Users/zhebin.fan/codestore/link-source-track-platform
```

## 一、mini 如何得到当前目录

执行 `cd` 后，当前 zsh 进程会记住这个目录。zsh 启动 `mini` 子进程时，操作系统自动让 `mini` 继承相同的 cwd。

Python 通过下面的代码读取它：

```python
os.getcwd()
```

因此，可执行文件的位置和工作目录是两回事：

```text
可执行文件：mini-swe-agent/.venv/bin/mini
工作目录：  启动 mini 时 pwd 显示的目录
```

## 二、项目中的 cwd 选择规则

`LocalEnvironment.execute()` 使用下面的代码选择命令执行目录：

```python
cwd = cwd or self.config.cwd or os.getcwd()
```

它表示从左向右选择第一个非空值：

1. 本次调用 `execute()` 时指定的 `cwd`；
2. 配置中的 `environment.cwd`；
3. mini 进程从 Shell 继承的当前目录，即 `os.getcwd()`。

默认运行时，前两项通常为空，因此最终使用 `os.getcwd()`。

选出目录后，项目把它传给子进程：

```python
subprocess.Popen(command, cwd=cwd, ...)
```

所以模型生成的 `ls`、`rg`、`pytest` 等命令都会在该目录执行。

## 三、Agent 如何认识项目

Environment 知道在哪里执行命令，但模型启动时并不知道仓库里有哪些文件。模型需要主动探索，例如：

```bash
pwd && ls -la
```

随后可能继续执行：

```bash
git status
rg --files | head
find . -maxdepth 2 -type f
```

Environment 在 cwd 中执行命令，再把输出返回给模型。模型通过这些结果逐步了解目录位置、项目结构和代码内容，而不是在启动时一次性读取整个仓库。

## 四、cwd 不一定是 Git 根目录

如果在子目录启动：

```bash
cd ~/project/backend
mini
```

那么 cwd 是 `~/project/backend`，即使 Git 根目录是 `~/project`，mini 也不会自动切换到上层目录。

需要确保从 Git 根目录启动时，可以使用：

```bash
cd "$(git rev-parse --show-toplevel)"
mini
```

Agent 某一步执行 `cd backend && pytest`，目录切换也只对这一次 bash 子进程有效；下一次 action 仍从原来的 cwd 开始。

## 最终心智模型

```text
Shell 执行 cd
    ↓
mini 进程继承 Shell 的 cwd
    ↓
LocalEnvironment 用 os.getcwd() 取得 cwd
    ↓
subprocess.Popen(..., cwd=cwd) 在该目录执行命令
    ↓
模型通过 pwd、ls、rg 等命令逐步认识项目
```

因此，mini-SWE-agent 的“项目锚点”不是一个专门的 `project_root` 属性，而是 Environment 执行命令时使用的 cwd。
