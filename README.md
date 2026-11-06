# CTF Agent

一个能自己打比赛的多模型 CTF 解题 Agent：多模型并发解题、Docker 沙箱隔离、多平台适配（CTFd / Ret2Shell / DASCTF / CTF² / CTF+），自带 Web 控制台，可观测、可干预、可限额。

> 本项目由 [verialabs/ctf-agent](https://github.com/verialabs/ctf-agent) 改造而来，加入 DeepSeek 支持、多比赛平台适配、Web 面板、靶机生命周期管理、提交去重、限速与额度控制等。

---

## 目录

- [特性](#特性)
- [架构](#架构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
  - [1. 平台配置](#1-平台配置)
  - [2. 模型配置](#2-模型配置)
  - [3. 解题与调度配置](#3-解题与调度配置)
  - [4. 沙箱与靶机](#4-沙箱与靶机)
- [使用方式](#使用方式)
  - [Web 控制台](#web-控制台)
  - [命令行](#命令行)
  - [两种运行模式](#两种运行模式)
- [平台适配细节](#平台适配细节)
- [一键更新](#一键更新)
- [目录结构](#目录结构)
- [安全与脱敏](#安全与脱敏)
- [故障排查](#故障排查)
- [License](#license)

---

## 特性

- **多模型并发**：同一道题可以同时派多个模型（同一模型的不同 reasoning effort 也算不同配置），先解出的那个获胜。
- **两种调度**：`round` 模式按轮次批量做题（方向轮换 + 难度分层 + 冷却），`coordinator` 模式由 LLM 调度器自主决定下一题。
- **Docker 沙箱**：每道题一个隔离容器，内置 pwn / crypto / web / reverse / misc / forensics 常用工具（pwntools、angr、z3、SageMath、radare2、binwalk、volatility3、sqlmap 等）。
- **多平台**：CTFd、Ret2Shell（西电 MoeCTF）、DASCTF / 羊城杯 AI Agent API、CTF² Agent Arena、CTF+。
- **靶机托管**：自动启动容器题靶机、定时续期、失联快速失败、**所有退出路径销毁容器**（含手动跳过与停止）。
- **可观测**：Web 面板实时显示每个 solver 的思考（中文）、工具调用、提交结果；右侧题目总览方块图按方向分组。
- **可干预**：面板上可实时改并发、给某道题发提示、跳过某道题、停止整轮。
- **可控成本**：按 DeepSeek 官网余额口径统计已用额度，支持每模型限额、并发上限、单题超时。
- **稳**：平台请求全局限速（默认 800ms）、提交去重（SQLite）、永久暂停（提交次数耗尽）、容器槽位先占后拉。

---

## 架构

```
                        ┌──────────────────────────┐
                        │  Web 面板 (scripts/webui) │  配置 / 观察 / 提示 / 跳过 / 停止
                        └────────────┬─────────────┘
                                     │ HTTP
             ┌───────────────────────▼────────────────────────┐
             │                ctf-solve (CLI)                 │
             │  round_runner ── 轮次/分层/冷却/双池/超时       │
             │  coordinator  ── LLM 调度（spawn/poll/submit）  │
             └───────┬───────────────────────────┬────────────┘
                     │                           │
        ┌────────────▼───────────┐    ┌──────────▼──────────────┐
        │  ChallengeSwarm        │    │  Platform adapter       │
        │  多个 Solver 并发       │    │  ctfplus / ctf2 / ...   │
        └────────────┬───────────┘    └──────────┬──────────────┘
                     │                           │
        ┌────────────▼───────────┐    ┌──────────▼──────────────┐
        │  DockerSandbox         │    │  Target env / WSRX      │
        │  每题一个容器           │    │  容器题靶机、隧道        │
        └────────────────────────┘    └─────────────────────────┘
```

| 模块 | 作用 |
| --- | --- |
| `backend/cli.py` | 命令行入口，参数解析与调度 |
| `backend/round_runner.py` | 轮次模式：选题、双池并发、超时、清理 |
| `backend/agents/` | solver / swarm / coordinator（claude、codex、deepseek 三种协调器） |
| `backend/sandbox.py` | Docker 沙箱生命周期、容器自愈、孤儿清理 |
| `backend/platform.py` | 平台工厂，按配置构造对应客户端 |
| `backend/ctfplus.py` / `ctf2.py` / `dasctf.py` / `ret2shell.py` / `ctfd.py` | 各平台 API 适配 |
| `backend/{submissions,pauses,targetenv,heartbeat,platformgate,quota,runtime,concurrency}.py` | 提交去重、暂停、靶机登记、心跳、限速、额度、运行时状态、动态并发 |
| `backend/tools/` | solver 可调用的工具（bash、读写文件、看图、提交 flag、web_fetch） |
| `backend/hints.py` | 面板/终端提示注入（按题隔离的队列） |
| `scripts/webui.py` | 零依赖 Web 控制台（标准库 http.server） |

---

## 环境要求

| 组件 | 要求 |
| --- | --- |
| Python | 3.14（用 [uv](https://docs.astral.sh/uv/) 安装与管理，不需要系统 Python） |
| Docker | Docker Desktop（Windows/macOS，WSL2 后端）或 Docker Engine（Linux） |
| 内存 | 建议 ≥ 8GB 可用；每道题容器默认最多 2 CPU / 16GB 上限 |
| 磁盘 | 沙箱镜像约 10–12GB；另需空间存放题目附件 |
| 网络 | 能访问模型 API（默认 `api.deepseek.com`）与比赛平台 |

---

## 快速开始

```bash
git clone https://github.com/movon-ava/MoonAgent.git
cd MoonAgent

# 1. 安装 Python 依赖（uv 会自动下载 Python 3.14）
uv sync

# 2. 配置
cp .env.example .env
#   编辑 .env：至少填 DEEPSEEK_API_KEY + 对应平台的凭据（见下节）

# 3. 构建沙箱镜像（首次约 30–60 分钟，之后可跳过）
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .

# 4. 启动 Web 控制台
uv run python scripts/webui.py --port 8099
#   打开 http://127.0.0.1:8099
```

也可以完全走命令行：

```bash
uv run ctf-solve --platform ctfplus --round 3 --max-challenges 3 -v
```

---

## 配置说明

所有配置都在 `.env`（示例见 `.env.example`）。面板「配置」页会读写同一个文件，两边等价。

### 1. 平台配置

`PLATFORM` 选平台；`auto` 会按已有凭据猜测（**不推荐**，容易拉错比赛）。

| 平台 | `PLATFORM` | 必填 | 凭据从哪来 |
| --- | --- | --- | --- |
| CTFd | `ctfd` | `CTFD_URL`、`CTFD_TOKEN` | CTFd 个人设置页的 API Token |
| Ret2Shell / 西电 | `ret2shell` | `RET2SHELL_URL`、`RET2SHELL_TOKEN`、`RET2SHELL_GAME` | 浏览器控制台 `JSON.parse(localStorage.account).token` |
| DASCTF / 羊城杯 | `dasctf` | `DASCTF_URL`、`DASCTF_ACCESS_KEY` | 选手控制台「平台接入凭证」里的 Server Host + AccessKey |
| CTF² Agent Arena | `ctf2` | `CTF2_URL`、`CTF2_AGENT_TOKEN`、`CTF2_GROUND` | Agent 详情页 Connect 面板生成的 Agent token；Ground 是练习场 UUID（在练习场页面 URL 里） |
| CTF+ | `ctfplus` | `CTFPLUS_URL`、`CTFPLUS_TOKEN` | 登录后浏览器 Cookie 里的 `SessionStore` 值（**不是** mario-token） |

```dotenv
PLATFORM=ctfplus
CTFPLUS_URL=https://example.play.ctfplus.cn
CTFPLUS_TOKEN=MTc5...（SessionStore cookie）
```

> 所有凭据只放在 `.env`，该文件已被 `.gitignore` 忽略。

### 2. 模型配置

内置 DeepSeek（OpenAI 兼容接口）：

```dotenv
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEFAULT_MODELS=deepseek/deepseek-flash
```

模型写法 `provider/model/effort`，例如：

| 写法 | 含义 |
| --- | --- |
| `deepseek/deepseek-flash` | 默认 effort（high） |
| `deepseek/deepseek-flash/low` | 低 reasoning effort，便宜快 |
| `deepseek/deepseek-v4-pro/max` | 最强推理 |

同一道题给多个模型 = 多个 solver 并跑，先解出者胜。

**自定义供应商**在面板「配置 → 模型配置 → 供应商」里加：填名称、Base URL（OpenAI 兼容，通常以 `/v1` 结尾）、API Key，然后「拉取模型」；也可以手填 `provider/model`。供应商信息存在 `config/providers.json`（已忽略，不会上传）。

**额度**：面板按 DeepSeek 官网余额差计算「已用 ¥」，可设置每个模型的上限（CNY）；超限的模型会被跳过，全部超限则不启动。

### 3. 解题与调度配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ROUND_SIZE` | `0` | 一轮做几题；`0` = 不限，走 coordinator 常驻模式 |
| `MAX_CONCURRENT_CHALLENGES` | `10` | 同时解几道题（面板可运行中实时改） |
| `CHALLENGE_TIMEOUT_MIN` | `0` | 单题时间上限（分钟），`0` 不限；超时即放弃并销毁容器 |
| `CHALLENGE_EXTRA_ROUNDS` | `0` | 一题没解出来时额外重试几轮（新上下文重新分析；超时/跳过不重试） |
| `WRITEUP_ENABLED` | `0` | 每题解出后自动生成中文 Writeup 到 `writeups/<方向>/<题名>.md` |
| `FLAG_FORMAT` | 空 | 本场 flag 形态（`moectf{}`/`SYC{}`），作为提示 + 提交前软校验 |
| `FLAG_SUBMIT_MODE` | `full` | `full` 交完整 flag；`inner` 只交 `{}` 内内容 |
| `THINK_CHINESE` | `1` | 是否要求模型用中文思考 |
| `SKIP_SOLVED_PULL` | `1` | 拉题时跳过平台已解出的题 |
| `CHALLENGE_CATEGORIES` | `web,misc,pwn,re,crypto` | 只拉这些方向；`all` = 全拉 |
| `CHALLENGE_DIFFICULTY` | 空 | 只拉这些难度：`入门,简单,中等,困难` 或 `easy/medium/hard` |
| `ROUND_ORDER` | `random` | `random`（按难度加权）/ `hard`（难优先）/ `score` / `name` |
| `ROUND_COOLDOWN_HOURS` | `6` | 多少小时内做过的题不再抽（`0` 关闭） |
| `ROUND_INCLUDE_SOLVED` | `0` | `1` = 已解题也进候选池（练习模式，提交会标 PRACTICE） |
| `ROUND_ROTATE` | `0` | `1` = 刷题模式：一批只解一个方向，下一批换方向 |
| `ROTATE_BATCH` | `0` | 刷题模式每批大小，`0` = 等于并发数 |
| `MAX_ENVIRONMENTS` | `0` | 同时开几个平台靶机；`0` = 按平台配额 |
| `MAX_ATTACHMENT_WORKERS` | `4` | 附件题并发上限 |
| `MAX_TARGET_WORKERS` | `0` | 容器题并发上限（`0` = 按平台配额） |
| `ENV_HEARTBEAT_S` | `300` | 靶机续期间隔，`0` 关闭 |
| `PLATFORM_REQUEST_INTERVAL` | `0.8` | 平台 API 最小请求间隔（秒），防 429 |
| `CTF_WORKSPACE_ROOT` | `./workspaces` | 沙箱工作目录（放大附件，别放 C 盘） |
| `INSTRUCTIONS_FILE` | `INSTRUCTIONS.md` | 注入给 solver 的规则文件 |

### 4. 跨轮记忆（challenge memory）

同一道题可能被多个 solver 先后处理（额外轮数、超时重建、换模型重跑）。solver 用 
emember 工具记下关键结论，
提交成功/被拒绝的 flag 也会自动记录；这些内容写到 logs/memory/<题名>.md，下一轮启动时以「队友之前的分析」注入提示词。

ecall 可随时查看，删除该文件即可重置这道题的记忆。

### 5. 沙箱与靶机

- 镜像名默认 `ctf-sandbox`，可用 `SANDBOX_IMAGE` 覆盖。
- 容器内：`/challenge/distfiles`（只读附件）、`/challenge/workspace`（可写工作区）、`/challenge/metadata.yml`（只读题目信息）。
- 容器带 `SYS_ADMIN`、`SYS_PTRACE`、seccomp unconfined（pwn/内核题需要）；内存上限默认 16g。
- 需要靶机的题：适配器负责启动平台实例，把 `host:port` 写进 `metadata.yml` 的 `connection_info`；solver 第一个 `bash` 会先探测目标，**连不上直接报 `TARGET DOWN` 并提示联系协调器重建，不允许扫端口猜**。
- 每道题结束（解出 / 放弃 / 超时 / 跳过）都会关闭靶机；面板「停止」会额外跑 `scripts/close_envs.py` 兜底。

---

## 使用方式

### Web 控制台

```bash
uv run python scripts/webui.py --port 8099
```

- **解题观察**页
  - 左侧：开始/停止、运行状态、**并发数（运行中可改）**、当前在跑的题目列表
  - 中间：选中题目的实时日志（💭 思考、› 工具调用、‹ 结果、✓ 提交成功），底部可给该题发提示
  - 右侧：**题目总览**方块图，按方向分组，已解绿色，点击方块可选中该题；鼠标悬停看完整题名
- **配置**页
  - 模型配置：勾选模型、填 DeepSeek Key、设置每个模型的额度上限、添加自定义供应商
  - 平台配置：选择平台（**必须明确选**，不支持 auto）、填对应凭据、设置容器数上限
  - 解题配置：本轮题数、并发、方向/难度勾选、选题顺序、刷题模式、单题超时、含已解题、演练模式
  - 「保存配置」只保存；「保存并开始」保存后直接开跑

> 面板只允许一个实例：重启会自动接管端口并清理 5 分钟前的残留 solver。

### 命令行

```bash
uv run ctf-solve --help
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--platform {ctfd,ret2shell,dasctf,ctf2,ctfplus}` | 平台 |
| `--round N` | 本轮做 N 题（做满即退出） |
| `--max-challenges N` | 并发数 |
| `--challenge-dir DIR` | 题目根目录（默认 `challenges`） |
| `--challenge PATH` | 只做这一道（忽略 round） |
| `--models spec,...` | 模型列表，如 `deepseek/deepseek-flash,deepseek/deepseek-v4-pro` |
| `--categories web,misc,...` | 方向过滤；`all` 全开 |
| `--difficulty 简单,中等` | 难度过滤 |
| `--order {random,hard,score,name}` | 选题顺序 |
| `--only TEXT` | 只做名字包含这些子串的题（可多次） |
| `--include-solved` | 已解题也做（练习模式） |
| `--rotate [--rotate-batch N]` | 刷题模式：一批一个方向 |
| `--challenge-timeout MIN` | 单题时间上限（0 不限） |
| `--extra-rounds N` | 没解出来时额外重跑 N 轮 |
| `--writeup` | 解题后生成中文 Writeup |
| `--flag-format 'SYC{}'` | 指定本场 flag 形态 |
| `--flag-submit-mode inner` | 只提交花括号内内容 |
| `--think-chinese/--no-think-chinese` | 中文思考开关 |
| `--skip-solved/--no-skip-solved` | 拉题跳过已解 |
| `--max-env N` | 同时开几个靶机（0 = 平台配额） |
| `--no-submit` | 演练：不真正提交 flag |
| `-v` | 详细日志（含思考与工具输出） |

示例：

```bash
# 刷 3 道 misc，2 并发，单题 10 分钟
uv run ctf-solve --platform ctfplus --round 3 --max-challenges 2 \
  --categories misc --difficulty 简单,中等 --challenge-timeout 10 -v

# 刷题模式：一批一个方向（misc → re → crypto …）
uv run ctf-solve --platform ctfplus --round 12 --max-challenges 4 --rotate --rotate-batch 4 -v

# 只做某一道，自动起靶机
uv run ctf-solve --platform ctfplus --challenge challenges/ez_pop -v
```

### 两种运行模式

| | round 模式（`--round N > 0`） | coordinator 模式（`--round 0`） |
| --- | --- | --- |
| 选题 | 本地按方向/难度/冷却/轮换算法选 | LLM 调度器自己挑 |
| 预算 | 做满 N 题就退出 | 持续运行，直到手动停止 |
| 并发 | 严格按 `--max-challenges` | 由调度器 `spawn_swarm` 决定，仍受并发/靶机上限约束 |
| 适合 | 稳定刷题、无人值守 | 想让它自己规划、多轮探索 |

---

## 平台适配细节

- **CTFd**：标准 `/api/v1` 接口，`--ctfd-url/--ctfd-token`。
- **Ret2Shell**：`POST /api/game/{gid}/challenge/{cid}/instance` 起容器；访问地址不直接暴露，需要 **WSRX 隧道**（见下）。平台同时只允许 1 个实例。
- **DASCTF**：`X-Agent-AccessKey` 认证，POST 需要双重 JSON 编码；只有 5 道题、每题 50 次提交机会，提交次数耗尽会永久暂停。
- **CTF²**：Agent API（`/api/open/v1/user`），每个 agent 默认 1 个靶机；提交必须带 `confirmation: true`。
- **CTF+**：`SessionStore` cookie 认证；`runtimeMode=docker` 的题需要先 `startChallenge` 才有 `address`。

### WSRX（Ret2Shell 专用）

Ret2Shell 的 web/pwn 靶机只能通过 WSRX 隧道访问：

1. 下载 [WebSocketReflectorX](https://github.com/XDSEC/WebSocketReflectorX/releases)，把 `wsrx.exe` 放到 `tools/wsrx/wsrx.exe`（或用环境变量 `WSRX_BIN` 指路径）。
2. 正常情况下 `pull_challenge` 会自动为每道题起实例并建隧道（本地端口 41000+，绑定 `0.0.0.0` 供容器访问）。
3. 自检：`uv run python scripts/check_wsrx.py`。

---

## 一键更新

仓库自带更新脚本：拉取最新代码 → 备份 `.env` → 同步依赖，可选重建沙箱镜像。

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1
# 加 -Rebuild 顺便重建沙箱镜像；-NoDeps 只更新代码
```

**Linux / macOS**

```bash
bash scripts/update.sh
# bash scripts/update.sh --rebuild
```

脚本做的事：

1. 备份当前 `.env` 到 `.env.bak`（只备份，不覆盖你的配置）
2. `git fetch --prune && git pull --ff-only`
3. `uv sync`
4. （可选）`docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .`

如果本地改过源码导致 `git pull` 冲突，脚本会提示你先 `git stash`。

---

## 目录结构

```
ctf-agent/
├── backend/               # 核心代码
│   ├── agents/            # solver / swarm / coordinator
│   ├── tools/             # 工具集（bash、文件、看图、提交 flag…）
│   ├── cli.py             # 命令行入口
│   ├── round_runner.py    # 轮次调度
│   ├── sandbox.py         # Docker 沙箱
│   └── <platform>.py      # 各平台适配
├── sandbox/
│   ├── Dockerfile.sandbox # 解题容器镜像
│   └── sandbox-tools.txt  # 工具清单
├── scripts/
│   ├── webui.py           # Web 控制台
│   ├── update.ps1(.sh)    # 一键更新
│   ├── list_*.py          # 各平台只读题目清单
│   └── test_*.py          # 离线测试（不联网）
├── INSTRUCTIONS.md        # 注入给 solver 的规则（可自定义）
├── .env.example           # 配置模板
└── pyproject.toml
```

运行时生成（不会提交）：`.env`、`logs/`、`challenges/`、`workspaces/`、`config/*.json`、`.venv/`。

---

## 安全与脱敏

提交/发布前请确认：

- `.env` 不提交（模板里只有空值）
- `logs/`（含 trace、运行日志、`submissions.sqlite`）、`challenges/`（题目与附件）、`workspaces/`（解压内容）不提交
- `config/providers.json`、`config/model_quotas.json` 含密钥/额度，不提交
- `SETUP_CN.md` 之类个人笔记不要上传

自查命令：

```bash
git grep -nE 'sk-[A-Za-z0-9]{20,}|ak_live_|ctf2_[0-9a-f]{32,}|SessionStore='
```

---

## 故障排查

| 现象 | 处理 |
| --- | --- |
| Docker 起不来 / WSL 报错 | Windows 需 WSL2：`wsl --install`，确认 `wsl --status` 默认版本为 2，重启后再开 Docker Desktop |
| 平台一直 429 | 调大 `PLATFORM_REQUEST_INTERVAL`（如 1.2），或减少并发 |
| 容器题一直排队 | 平台每账号只允许 N 个靶机，调 `MAX_ENVIRONMENTS` / `MAX_TARGET_WORKERS`，或换附件题先做 |
| `Budget exhausted` | 面板「配置 → 模型配置」把该模型上限调高，或点「已用额度清零」 |
| 提示发错题 | 旧版本 bug，已按题隔离队列；确认是最新代码 |
| 面板打不开 / 端口占用 | 面板会自己接管 8099；手动 `taskkill /F /PID <pid>` 后重启 |
| 沙箱容器残留 | `uv run python scripts/close_envs.py` + `docker ps -aq \| xargs -r docker rm -f` |

---

## License

见 [LICENSE](LICENSE)。

## 新增能力（P1–P5）

- **提交必须带证据**：`submit_flag(flag, evidence)`；无证据本地拦下，不消耗平台次数（`REQUIRE_FLAG_EVIDENCE=1`）。
- **断点续跑**：每轮写 `logs/runs/<id>/state.json`，`--resume latest` 或面板「继续上次未完成的轮次」只跑没跑完的题。
- **上下文手术**：长跑自动裁剪旧回合；检测到死循环时回滚最近几轮（`CONTEXT_LIMIT_CHARS`）。
- **MCP 工具**：`config/mcp.json` 配置 stdio MCP server，自动注册成 `<name>_<tool>`。
- **角色模型路由**：`ROLE_MODELS={"writeup":"deepseek/deepseek-flash"}`，把写 writeup 这类活派给便宜模型。
- **方向知识库**：`knowledge/*.md` 按方向注入提示词，纯 Markdown，随时可改。

## 维护与自检

- 日志清理：uv run python scripts/cleanup_logs.py（默认保留最近 200 个 trace、14 天内的 trace、30 天内的 run 快照；--dry-run 只报告）。面板每次启动也会自动清一次。
- 回归自检：scripts/test_*.py 共 33 个脚本，逐个用 uv run python scripts/test_xxx.py 运行，末行打印 ALL ... CHECKS PASSED 或 ok:。
- 断点续跑：--resume latest 或面板「继续上次未完成的轮次」，快照在 logs/runs/<run-id>/state.json。
- 提交需要证据：REQUIRE_FLAG_EVIDENCE=1 时，submit_flag 不带 evidence 会被本地拦下（返回 SUBMIT BLOCKED），不会消耗平台次数。

- 快速自检（pytest 封装了全部 `scripts/test_*.py`，默认跳过 5 个慢检查）：

  ```powershell
  uv run pytest            # 28 passed / 5 deselected，约 1.5 分钟
  uv run pytest -m slow    # sandbox 镜像、真实模型、联网价格
  ```

- 覆盖率（脚本在子进程里跑，所以用 `coverage run --parallel-mode` 再 combine）：

  ```powershell
  uv run python scripts/coverage_report.py            # 当前约 42%
  uv run python scripts/coverage_report.py --include-slow --fail-under 40
  ```

- 静态检查：`uv run ruff check backend scripts tests`（含 `S110`：禁止 `except: pass` 静默吞异常）。
