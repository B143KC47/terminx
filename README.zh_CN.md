<div align="center">

# 🖥️ termiX

**一个终端，纵览所有。**

为你的 CLI 编程智能体打造的实时仪表盘 —— **Codex、OpenCode、Claude Code、Kimi** —— 在一个终端里看清每个智能体此刻正在做什么。

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-blueviolet)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-0.1.0-orange)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ termiX — open terminals  1 working · 0 blocked · 2 running                  │
└─ scan: 15:43:07 · refresh 3s · ↑↓ select · ←→ view · Enter pop · n note · c ─┘
                                                                               
        agent      status                 model              directory        
 ───────────────────────────────────────────────────────────────────────────── 
 ▸      opencode   ● working              deepseek-v4-flas   C:\Users\you  \…
        codex      ■ blocked (waiting     gpt-5.6-sol        …\diffusion_rese…
                   423s)                                                       
        kimi       ○ idle                 kimi-k2-0711       …\site_rebuild    
```

</div>

**语言 / Languages:** [English](README.md) · 简体中文

---

## ✨ 功能特性

- **实时终端总览** —— 列出你机器上当前打开的每一个智能体会话：
  状态（`● working` / `■ blocked` / `○ idle`）、所用模型、工作目录、git 分支
- **一键跳回真实终端** —— 按 `Enter` 将所选会话的终端窗口
  提到前台（Windows Terminal），继续原来的对话
- **账户配额一目了然** —— 直接来自服务商官方 API 的订阅额度
  （5 小时 / 每周 / 每月）：`OK` / `NEAR` / `HIT` + 重置倒计时
- **按终端记笔记** —— 记下每个智能体在做什么；笔记会持久保存
- **按智能体配色** —— 自动分配调色板，也可按 `c` 循环切换并保存
- **国际化** —— 内置 English 与 简体中文；语言自动从系统区域设置检测，
  也可随时在配置中覆盖
- **可插拔适配器** —— 新增一个 CLI 智能体只需约 30 行代码

## 📦 环境要求

- Windows（推荐 Windows Terminal）—— macOS/Linux：状态检测可用，
  「跳回终端」会退化为打开一个新窗口
- Python 3.10+
- 以下其一或多个：[Codex](https://github.com/openai/codex)、
  [OpenCode](https://opencode.ai)、[Claude Code](https://docs.claude.com)、
  [Kimi Code](https://www.kimi.com/code)

## 🚀 安装

```powershell
pip install rich
git clone https://github.com/B143KC47/terminx.git
cd terminx
pip install -e .
```

然后即可在任意位置运行：

```powershell
terminx              # 实时仪表盘（q 退出）
terminx --once       # 渲染一帧后退出
```

## 🎮 按键操作

| 按键 | 功能 |
|---|---|
| `↑` / `↓` | 在会话之间移动光标 |
| `←` / `→` | 在**终端**视图与**账户用量**视图之间切换 |
| `Enter` | 将所选终端提到前台（聚焦已有窗口，或新开窗口并恢复会话） |
| `n` | 为所选终端写笔记（Enter 保存 · Esc 取消） |
| `c` | 循环切换所选智能体的颜色 |
| `d` | 开关详情面板 |
| `q` | 退出 |

## 📊 各视图显示内容

### 打开的终端

只显示**此刻真正在运行**的会话 —— 通过将每个会话的工作目录与
存活进程逐一匹配，过滤掉过期的会话文件。

| 列 | 含义 |
|---|---|
| agent | 名称，按智能体着色；`✎` = 有笔记 |
| status | `● working`（会话文件最近有更新）· `■ blocked`（正在运行，等待你操作 —— 包括权限确认提示）· `○ idle` |
| model | 从智能体自己的会话文件中解析 |
| directory | 工作目录（+ 品红色显示 git 分支） |

### 账户用量

**仅**显示官方订阅配额 —— 不做本地估算，你的本地模型配置
（例如路由 / 代理方案）也不会对其产生影响。

| 状态 | 含义 |
|---|---|
| `OK` | 用量低于窗口额度的 80% |
| `NEAR` | 80–90% |
| `HIT` | ≥90%（在重置之前会被限流） |

各智能体的数据来源：

| 智能体 | 来源 | 额外配置 |
|---|---|---|
| codex | `chatgpt.com/backend-api/wham/usage`（读取 `~/.codex/auth.json`） | 无 —— `codex login` 后即可用 |
| claude | `api.anthropic.com/api/oauth/usage` | 仅当通过 OAuth 登录（`claude login`）时可用；代理 / 路由方案会显示「无官方配额数据」 |
| kimi | `api.kimi.com/coding/v1/usages` | 设置 `kimi_api_key`（在 [Kimi Code 控制台](https://www.kimi.com/code/console) → API Keys 创建） |
| opencode | 无（自带服务商密钥） | — |

## ⚙️ 配置

创建 `~/.terminx.json`（或 `~/.config/terminx/config.json`）。完整示例见
`terminx/config.example.json`。

```json
{
  "lang": "auto",
  "refresh_sec": 3,
  "working_threshold_sec": 60,
  "blocked_threshold_sec": 600,
  "show_recent_hours": 24,
  "max_rows_per_agent": 6,
  "colors": { "codex": "yellow", "claude": "magenta" },
  "kimi_api_key": "sk-kimi-...",
  "paths": {}
}
```

- `lang` —— 界面语言：`"auto"`（从系统区域设置检测）· `"en"` · `"zh_CN"`。
  也可以单次强制指定：`set LANG=en_US && terminx`
- `colors` —— 固定各智能体颜色（否则自动分配；`c` 可实时切换）
- `kimi_api_key` —— 可选，启用 Kimi 官方配额
- `paths` —— 覆盖某智能体的数据目录，例如 `{"codex": "D:/codex-data"}`

## 🌐 添加新语言

翻译文件位于 `terminx/locales/<code>.json`，是简单的 键→文本 映射，
键为英文原文。添加新语言的步骤：

1. 将 `terminx/locales/zh_CN.json` 复制为 `terminx/locales/<code>.json`
2. 翻译各个值（保留 `{placeholders}` 与 rich 标记如 `[bold]…[/]`）
3. 在 `terminx/i18n.py` 的 `SUPPORTED` 中加入该语言代码
4. 在配置中设置 `"lang": "<code>"` 即可试用

文档方面，将 `README.md` 翻译为 `README.<code>.md`（例如
`README.zh_CN.md`），并将其加入各 README 顶部的语言链接中。

## 🔐 隐私

- API 令牌仅从本地认证文件读取，且**只用于 HTTP 请求头** ——
  termiX 不会打印、记录、显示或存储它们
- 笔记与颜色选择保存在 `~/.config/terminx/state.json`
- 无遥测；除你启用的官方配额接口外没有任何网络请求

## 🧩 添加新智能体（开发者）

创建 `terminx/agents/<name>.py`，继承 `AgentAdapter`：

```python
from .base import AgentAdapter, SessionInfo, Quota

class MyAgent(AgentAdapter):
    name = "myagent"
    process_names = ["myagent"]

    def find_sessions(self, cfg) -> list[SessionInfo]:
        ...  # -> 返回带 cwd、model、last_activity、resume_cmd 的会话

    def usage_records(self, since, cfg) -> list:
        ...  # 可选，配额展示已不再使用

    def quota(self, cfg) -> Quota | None:
        ...  # 可选 —— 来自服务商 API 的官方配额
```

然后在 `terminx/agents/__init__.py` 中注册。状态检测、git 分支、
PID 解析与配额缓存都由基类免费提供。

## 🏗️ 架构

```
terminx/
├── agents/            # 每个 CLI 智能体一个适配器（codex、claude、opencode、kimi）
│   ├── base.py        # AgentAdapter 抽象基类：会话、状态、resolve_pid
│   └── quota.py       # 官方配额获取器（缓存 120 秒）
├── core/              # 进程（tasklist）、git 分支、win32 窗口聚焦、状态
├── i18n.py            # 语言检测 + 目录加载器
├── locales/           # 翻译目录（zh_CN.json；英文内嵌）
└── ui/
    ├── dashboard.py   # rich Live TUI：按键处理、视图、笔记、配色
    └── colors.py      # 按智能体调色板
```

关键设计点：

- **状态保真** —— 只有当某会话的精确工作目录下存在存活进程时
  才显示该会话（`pid ↔ cwd` 匹配），因此数量始终与 `tasklist` 一致
- **界面响应** —— 扫描在后台线程运行；按键每 50ms 处理一次，
  界面永远不会被磁盘 / 网络扫描阻塞
- **配额只看官方** —— 服务商 API 是唯一可信来源

## 🧪 开发

```powershell
pip install -e . pyflakes
python -m pyflakes terminx   # 代码检查
python -m unittest discover -s tests   # i18n 健全性测试
python -m terminx --once     # 冒烟测试
```

## 📄 许可证

[MIT](LICENSE)
