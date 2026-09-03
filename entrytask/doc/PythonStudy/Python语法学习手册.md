# Python 语法学习手册

这份笔记只记录阅读当前项目时遇到的、对 Java/Go 开发者不够直观的 Python 写法。普通的变量、`if`、`for`、函数调用等通用概念不重复讲；以后遇到新的 Python 特有写法，再继续追加。

## 1. 类型标注不是 Java 式强制类型

项目代码：

```python
def get_model(
    input_model_name: str | None = None,
    config: dict | None = None,
) -> Model:
```

含义：

```text
str | None    可以是字符串，也可以是 None
dict | None   可以是字典，也可以是 None
-> Model      预期返回一个 Model
= None        调用时不传，默认值为 None
```

Python 的类型标注主要服务于 IDE、静态检查器和代码阅读，运行时通常不会像 Java 编译器一样严格阻止错误类型：

```python
def double(value: int) -> int:
    return value * 2


double("a")  # 运行时可以得到 "aa"，类型标注本身没有拦截
```

因此阅读时把它理解为“接口契约”，不要理解成强制类型转换。

## 2. `None` 使用 `is` 判断

```python
if config is None:
    config = {}
```

`None` 类似 Java/Go 中的 `null`/`nil`。Python 惯用 `is None`，因为这里要判断的是唯一的 `None` 对象，而不是普通的值相等。

```python
value is None
value is not None
```

普通值比较仍然使用 `==`：

```python
name == "gpt-5"
count == 3
```

## 3. 字典的 `[]`、`get()`、`pop()`

Python 的 `dict` 类似 Java 的 `Map`、Go 的 `map`：

```python
config = {
    "model_name": "openai/gpt-5",
    "model_class": "litellm",
}
```

### `config["key"]`：必须读到

```python
name = config["model_name"]
```

key 不存在会抛出 `KeyError`。适合“缺少这个配置就是程序错误”的场景。

### `config["key"] = value`：写入或覆盖

```python
config["model_name"] = "anthropic/claude-sonnet"
```

方括号在等号左边时是写入，类似：

```java
config.put("model_name", "anthropic/claude-sonnet");
```

### `config.get("key", default)`：可选读取

```python
config.get("model_name")       # 存在则返回 value，否则返回 None
config.get("model_name", "")   # 存在则返回 value，否则返回 ""
```

类似 Java：

```java
config.getOrDefault("model_name", "");
```

### `config.pop("key", default)`：取出并删除

```python
model_class = config.pop("model_class", "")
```

执行前：

```python
config == {
    "model_name": "openai/gpt-5",
    "model_class": "litellm",
}
```

执行后：

```python
model_class == "litellm"
config == {"model_name": "openai/gpt-5"}
```

项目使用 `pop()` 是有意的：`model_class` 只供工厂选择实现类，不应该继续传给具体模型的构造函数。

## 4. 真假值与 `:=`

项目代码：

```python
if from_config := config.get("model_name"):
    return from_config
```

`:=` 是赋值表达式：右边先求值，结果赋给左边变量，然后这个结果继续参与 `if` 判断。

完全展开就是：

```python
from_config = config.get("model_name")
if from_config:
    return from_config
```

这里还利用了 Python 的真假值规则。以下常见值会被当成 `False`：

```python
None
False
0
""
[]
{}
```

所以这段代码不只是判断 key 存不存在，还要求 `model_name` 不是 `None` 或空字符串。

Java/Go 通常不能直接把字符串放进条件判断；这是阅读 Python 时需要特别留意的地方。

## 5. 类可以像普通值一样放进变量

项目代码：

```python
model_class = get_model_class(...)
return model_class(**config)
```

`model_class` 保存的不是模型对象，而是某个类本身，例如：

```python
model_class = LitellmModel
```

类后面加括号才会创建对象：

```python
model = model_class(model_name="openai/gpt-5")
```

等价于：

```python
model = LitellmModel(model_name="openai/gpt-5")
```

最小示例：

```python
class Dog:
    pass


animal_class = Dog       # 类本身
animal = animal_class()  # Dog 对象
```

Java 中一般通过工厂、`Class<?>` 或反射做动态选类；Python 中函数和类本来就是可以传递、保存和返回的对象。

当前项目的选择过程是：

```text
"litellm" 字符串
    ↓ 映射或动态导入
LitellmModel 类
    ↓ 调用类
LitellmModel 对象
```

## 6. 关键字参数与 `**` 字典解包

普通关键字参数：

```python
LitellmModel(
    model_name="openai/gpt-5",
    set_cache_control="default_end",
)
```

如果参数已经存放在字典中：

```python
config = {
    "model_name": "openai/gpt-5",
    "set_cache_control": "default_end",
}
```

可以使用 `**` 解包：

```python
LitellmModel(**config)
```

两种写法完全等价。规则是：

```text
字典 key   → 参数名
字典 value → 参数值
```

因此：

```python
return model_class(**config)
```

表示“调用前面选出的类，把配置字典拆成构造参数，创建并返回对象”。如果字典中含有构造函数不接受的 key，通常会抛出 `TypeError`。

### `**kwargs` 是反方向的收集

调用处的 `**config` 是把字典拆开；定义处的 `**kwargs` 是把多余的关键字参数收进字典：

```python
def __init__(self, model, env, **kwargs):
    print(kwargs)


Agent(model, env, step_limit=10, cost_limit=3)
# kwargs == {"step_limit": 10, "cost_limit": 3}
```

## 7. 单独的 `*`：后面的参数必须写名字

项目代码：

```python
def get_agent(model, env, config, *, default_type=""):
    ...
```

参数列表里的单独 `*` 不接收值，它只是规定：后面的参数只能按名字传递。

正确：

```python
get_agent(model, env, config, default_type="interactive")
```

错误：

```python
get_agent(model, env, config, "interactive")
```

这叫 keyword-only parameter。它能避免调用者看到一个孤立的字符串，却不知道这个字符串代表什么。

## 8. 生成器表达式：先把它还原成普通循环

项目代码：

```python
any(
    s in resolved_model_name.lower()
    for s in ["anthropic", "sonnet", "opus", "claude"]
)
```

先不要研究生成器。整段代码实际只是在判断：模型名称是否包含任意一个关键词。

用最普通的 Python 循环写就是：

```python
keywords = ["anthropic", "sonnet", "opus", "claude"]
lower_name = resolved_model_name.lower()
found = False

for keyword in keywords:
    if keyword in lower_name:
        found = True
        break
```

Go 基本也会这样写。Java Stream 可以写成：

```java
boolean found = keywords.stream()
    .anyMatch(keyword -> lowerName.contains(keyword));
```

Python 把循环中的“每次计算什么”压缩成：

```python
keyword in lower_name for keyword in keywords
```

把变量名换回项目中的 `s`：

```python
s in lower_name for s in keywords
```

它表达的是：

```text
依次从 keywords 取出一个 s
        ↓
计算 s in lower_name
        ↓
产生一个 True 或 False
```

假设：

```python
lower_name = "anthropic/claude-sonnet"
keywords = ["anthropic", "sonnet", "opus", "claude"]
```

每次计算的结果相当于：

```text
"anthropic" in lower_name → True
"sonnet"    in lower_name → True
"opus"      in lower_name → False
"claude"    in lower_name → True
```

如果使用方括号，就是列表推导式，会立即生成整个列表：

```python
results = [s in lower_name for s in keywords]
# [True, True, False, True]
```

如果使用圆括号，就是生成器表达式：

```python
results = (s in lower_name for s in keywords)
```

此时不会立即创建完整列表。`results` 更像一条按需生产数据的流水线：外部每要一个结果，它才计算下一个。这叫惰性求值。

可以手动取值观察：

```python
results = (s in lower_name for s in keywords)

next(results)  # 计算第一个，得到 True
next(results)  # 计算第二个，得到 True
```

列表推导式和生成器表达式的区别：

| 写法 | 结果 | 计算方式 |
|---|---|---|
| `[表达式 for x in 数据]` | 列表 | 立即算完全部结果 |
| `(表达式 for x in 数据)` | 生成器 | 用到一个才算一个 |

## 9. `any()` 会消费生成器并短路

```python
any(s in lower_name for s in keywords)
```

`any()` 不断向生成器索要下一个布尔值：

```text
取得第一个结果
    ├─ True  → 立即返回 True，不再继续
    └─ False → 再取下一个
```

全部都是 `False`，才返回 `False`。因此它与前面的普通循环完全相同：

```python
for keyword in keywords:
    if keyword in lower_name:
        found = True
        break
```

`all()` 相反：遇到第一个 `False` 就停止；只有全部为真才返回 `True`。

```python
any([False, True, False])  # True
all([True, True, False])   # False
```

项目代码选择生成器而不是列表，是因为 `any()` 找到第一个匹配项后就可以停止，不需要把后续结果全部算出来。

## 10. 为什么先 `deepcopy()` 再修改配置

项目代码：

```python
config = copy.deepcopy(config)
config["model_name"] = resolved_model_name
model_class = config.pop("model_class", "")
```

Python 赋值对象时，默认不会复制对象：

```python
original = {"nested": {"value": 1}}
config = original
config["nested"]["value"] = 2

print(original)  # {'nested': {'value': 2}}
```

`config` 和 `original` 指向同一个字典。函数内部修改 `config`，调用者手中的字典也会变化。

深复制会创建完全独立的嵌套结构：

```python
import copy

original = {"nested": {"value": 1}}
config = copy.deepcopy(original)
config["nested"]["value"] = 2

print(original)  # {'nested': {'value': 1}}
```

这里使用 `deepcopy()` 不是特殊语法，而是一个重要的 Python 对象语义：变量保存对象引用，赋值本身不复制对象。

## 11. 鸭子类型、`Protocol` 和 `ABC`

先记住最核心的区别：

```text
普通类：看有没有继承关系
Protocol：不要求继承，看方法和属性是否齐全
ABC + @abstractmethod：要求继承，而且运行时禁止遗漏抽象方法
```

### 普通类写 `...` 并不会变成接口

```python
class Runner:
    def run(self) -> None:
        ...
```

这是一个可以直接实例化的普通类：

```python
runner = Runner()
runner.run()  # 什么也不做，返回 None
```

`...` 在这里仅仅是占位表达式，不表示 Java 的抽象方法。另一个类即使也有 `run()`，静态类型检查器仍不会因为方法相同就认为它是 `Runner`：

```python
class Dog:
    def run(self) -> None:
        print("running")


def start(runner: Runner) -> None:
    runner.run()


start(Dog())  # 运行时碰巧能跑，静态检查认为 Dog 不是 Runner
```

普通类采用继承关系判断类型；`Dog` 必须写成 `class Dog(Runner)`，才明确是 `Runner` 的子类。

### 鸭子类型：运行时只管“有没有这个能力”

没有类型标注时，可以直接写：

```python
def start(runner):
    runner.run()
```

传入什么类不重要，只要运行到这里时对象有 `run()` 就能执行；没有就抛出 `AttributeError`。这就是鸭子类型：不先检查出身，只在使用时调用所需能力。

它灵活，但 IDE 和静态检查器不知道 `runner` 应该具有什么能力。`Protocol` 正是给这种鸭子类型补一份可检查的正式契约。

### `Protocol`：把“鸭子应该长什么样”写清楚

```python
from typing import Protocol


class Runner(Protocol):
    def run(self) -> None:
        ...
```

实现类不需要继承 `Runner`：

```python
class Dog:
    def run(self) -> None:
        print("running")


def start(runner: Runner) -> None:
    runner.run()


start(Dog())  # 静态检查通过：Dog 具有 Runner 要求的全部成员
```

`class Runner(Protocol)` 中的继承只是在声明：“`Runner` 是一份协议，不是普通业务父类。”`Dog` 没有继承 `Runner`，也不会获得它的方法实现；类型检查器只是比较二者的结构。

Protocol 中声明的成员默认都属于契约。假设它要求 `run()` 和 `stop()`，一个类只有 `run()`，静态检查器就不会认为它符合该 Protocol。Python 运行时通常不检查类型标注，可能要等真正调用缺失的 `stop()` 时才报错。

项目中的：

```python
class Model(Protocol):
    config: Any

    def query(self, messages: list[dict], **kwargs) -> dict: ...
    def format_message(self, **kwargs) -> dict: ...
    def format_observation_messages(self, message: dict, outputs: list[dict]) -> list[dict]: ...
    def get_template_vars(self, **kwargs) -> dict: ...
    def serialize(self) -> dict: ...
```

是一份完整的 Model 能力清单。`LitellmModel` 不继承 `Model`，但它具有这些属性和方法，因此可以传给：

```python
def get_agent(model: Model, env, config):
    ...
```

这和 Go 的隐式 interface 更接近，不像 Java 的显式 `implements`。

### `ABC`：必须继承，并在运行时强制补齐方法

```python
from abc import ABC, abstractmethod


class Runner(ABC):
    @abstractmethod
    def run(self) -> None:
        ...
```

实现类必须继承它：

```python
class Dog(Runner):
    def run(self) -> None:
        print("running")
```

如果遗漏抽象方法：

```python
class BadRunner(Runner):
    pass


BadRunner()  # TypeError：仍有抽象方法 run，禁止实例化
```

注意，单独继承 `ABC` 还不够；真正让方法受到运行时强制的是 `@abstractmethod`。

### 为什么 Python 不新增 `interface` 关键字

Python 原本就是依靠鸭子类型运行的动态语言，类型标注和 `Protocol` 是后来逐步加入的。设计时希望：

- 不破坏原有 Python 语法和老项目；
- 类型检查仍然可选，不改变正常运行方式；
- 不强迫已有实现类修改继承关系；
- 延续“只要能力相同就能使用”的鸭子类型思想。

因此 Python 没有再新增一套 `interface/implements` 语法，而是复用已有的 `class` 和继承语法：

```python
class Model(Protocol):
    ...
```

这里的 `Protocol` 是一个特殊基类，它告诉类型检查器：“请按成员结构判断 `Model`，不要按继承关系判断。”实现类通常不继承它。

### 三者最终对照

| 写法 | 判断标准 | 实现类必须继承吗 | 缺少方法时 |
|---|---|---:|---|
| `class Runner:` | 继承关系 | 是，才算其子类 | 普通 `...` 不阻止实例化 |
| `class Runner(Protocol):` | 方法和属性结构 | 否 | 静态检查不通过，运行时通常不主动拦截 |
| `class Runner(ABC):` + `@abstractmethod` | 继承关系 | 是 | 运行时禁止实例化 |

一句话记忆：

```text
Protocol：你不用认我做父类，能力齐全就符合我。
ABC：你必须继承我，抽象方法没补齐就不能创建对象。
```

## 把 `get_model()` 顺一遍

```python
def get_model(input_model_name: str | None = None, config: dict | None = None) -> Model:
    resolved_model_name = get_model_name(input_model_name, config)

    if config is None:
        config = {}

    config = copy.deepcopy(config)
    config["model_name"] = resolved_model_name

    configured_class = config.pop("model_class", "")
    model_class = get_model_class(resolved_model_name, configured_class)

    keywords = ["anthropic", "sonnet", "opus", "claude"]
    is_anthropic = any(s in resolved_model_name.lower() for s in keywords)

    if is_anthropic and "set_cache_control" not in config:
        config["set_cache_control"] = "default_end"

    return model_class(**config)
```

按照变量形态理解：

```text
resolved_model_name   字符串，例如 "openai/gpt-5"
config                字典，保存具体模型的构造参数
configured_class      字符串，例如 "litellm"
model_class           类，例如 LitellmModel
model_class(**config) 根据类和参数创建出来的模型对象
```

这段代码的核心并不复杂：

```text
确定模型名
  → 从配置里取走用于选类的 model_class
  → 得到真正的 Python 类
  → 把剩余字典解包为构造参数
  → 创建模型对象
```
