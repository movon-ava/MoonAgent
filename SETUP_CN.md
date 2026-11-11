# ctf-agent 本机配置说明（Windows 11 + WSL2 + Docker Desktop）

仓库：F:\ctf_agent（origin: https://gitcode.com/gh_mirrors/ct/ctf-agent）
上游：verialabs/ctf-agent —— 协调器 LLM 调度多个 solver，每个 solver 跑在独立 Docker 沙箱里。

## 一、已完成

| 项目 | 状态 |
| --- | --- |
| 仓库 | 已修复 .git 层级问题，`git status` 干净，main @ 3366d56 |
| Python | uv 0.13.6 + Python 3.14.10，`.venv` 已 `uv sync` |
| 依赖修复 | `pyproject.toml` 中 pydantic-ai 固定为 `>=1.107.9,<2`（2.x 删除了 `OpenAIModel`，会直接 ImportError） |
| DeepSeek 接入 | 新增 `deepseek` provider 与 `--coordinator deepseek`，`.env` 已写入官方 key，solver/协调器均可跑 |
| CLI 依赖 | 全局 npm 装好 `@openai/codex` 0.166.0、`@anthropic-ai/claude-code` 2.1.317 |
| Docker Desktop | 4.97.0 已安装（`--backend=wsl-2`），用户已加入 docker-users，引擎已正常启动 |
| WSL2 | 曾处于半安装状态（只有 Store 壳包、缺 WSLService），已用官方 `wsl.2.7.10.0.x64.msi` 修复；`wsl --version` 正常，默认版本 2 |
| 沙箱镜像 | `ctf-sandbox:latest` 已构建（约 10GB），SageMath 9.5 / angr 9.2 / pwntools 4.15 / radare2 6.2 / torch / CADO-NFS 均已验证可用 |
| 端到端验证 | DeepSeek solver 在真实沙箱中解题成功（`ctf-solve --challenge challenges\smoke-deepseek`），协调器 backend 亦可运行 |
| Ret2Shell 适配器 | 新增 `backend/ret2shell.py` + `backend/platform.py`：自动拉题（列表/详情/附件）、自动提交并轮询异步 checker，`--platform ret2shell --round N` 一轮结束即退出 |
| DASCTF 适配器 | 新增 `backend/dasctf.py`：羊城杯 AI Agent API（`X-Agent-AccessKey`），自动拉题/起环境/下载附件/提交 flag，`--platform dasctf --round N` |
| 性能/网络 | `.wslconfig`（8GB/8 核）、`~/.docker/daemon.json`（国内镜像加速）、Dockerfile 改用中科大 apt 源（实测 7.9MB/s，阿里云仅 0.7MB/s） |

## 二、WSL 修复与沙箱镜像（已完成）

Windows 11 家庭版上首次启用 WSL2 虚拟化组件后必须重启。本机已重启，但重启后 WSL 仍不可用
（现象：`wsl --version` 卡住、`C:\Program Files\WSL` 为空、没有 `WSLService` 服务）。
原因：Store 的 WSL 包只有壳、缺运行时；已用官方 MSI 修复：

```powershell
# 管理员执行（脚本会自动安装 MSI 并检查服务）
powershell -ExecutionPolicy Bypass -File F:\ctf_agent\scripts\fix-wsl.ps1
```

修复后：`WSLService` 自动运行、`wsl --version` 输出 2.7.10.0、`wsl --status` 默认版本 2。
以后若 WSL 再坏，重跑上面这条即可。

沙箱镜像已构建完成（ctf-sandbox:latest，约 10GB）。如需重建：

```powershell
cd F:\ctf_agent
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .
```

## 三、凭据

已写入 `F:\ctf_agent\.env`（该文件已被 git 忽略）：

```ini
CTFD_URL=https://你的比赛地址
CTFD_TOKEN=ctfd_xxxxxxxx        # CTFd → Settings → Access Tokens
# 或 CTFD_USER / CTFD_PASS

DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEFAULT_MODELS=deepseek/deepseek-flash

# 西电 CTF 终端（Ret2Shell）平台
PLATFORM=auto
RET2SHELL_URL=https://ctf.xidian.edu.cn
RET2SHELL_TOKEN=                 # 浏览器 F12 → Console: localStorage.account.token
RET2SHELL_GAME=37                # 留空 = 自动选当前进行中的比赛
CHALLENGE_CATEGORIES=web,misc,pwn,re,crypto   # 只拉这些方向，all = 不过滤
CHALLENGE_DIFFICULTY=            # 只拉这些难度：入门/简单/中等/困难（逗号分隔，留空 = 全部）
ROUND_SIZE=0                     # >0 时启用"一轮 N 题"模式
ROUND_ORDER=random               # random | score | name
ROUND_COOLDOWN_HOURS=6           # 跳过最近 N 小时做过的题（0 = 关闭）
ROUND_INCLUDE_SOLVED=0           # 1 = 把平台已解的题也放进候选池
INSTRUCTIONS_FILE=INSTRUCTIONS.md

# DASCTF / 羊城杯（AI Agent API）：玩家控制台 → 平台接入凭证
DASCTF_URL=https://pro.dasctf.com
DASCTF_ACCESS_KEY=ak_live_xxx     # 用 --platform dasctf 指定平台
```

DeepSeek 模型规格写法是 `provider/model/effort`（effort 可省略，默认 `high`）：

| 规格 | 说明 |
| --- | --- |
| `deepseek/deepseek-flash` | 1M 上下文、支持图片，性价比最高（默认） |
| `deepseek/deepseek-flash/low` | 低思考强度，最快最省 |
| `deepseek/deepseek-flash/max` | 最高思考强度 |
| `deepseek/deepseek-v4-pro` | 纯文本、推理更强，价格约为 flash 的 4 倍 |

只配 DeepSeek 时，协调器会自动切到 `--coordinator deepseek`（也可显式指定）。
以后若还有 Anthropic / OpenAI 凭据，可继续使用 `claude-sdk/*`、`codex/*`
（这两类走各自 CLI 的登录态，不是 pydantic-ai 的 provider）。

## 四、日常使用

```powershell
cd F:\ctf_agent
# 全自动打比赛（协调器 + DeepSeek swarm，默认配置）
uv run ctf-solve --ctfd-url https://xxx --ctfd-token ctfd_xxx --challenges-dir challenges --max-challenges 5 -v
# 单题调试（目录里要有 metadata.yml，可用 pull_challenges.py 拉取）
uv run ctf-solve --challenge challenges/xxxx --no-submit -v
# 换模型：更强 / 更省
uv run ctf-solve --models deepseek/deepseek-v4-pro --models deepseek/deepseek-flash/low
# 显式指定协调器（默认会自动选择）
uv run ctf-solve --coordinator deepseek --coordinator-model deepseek/deepseek-v4-pro
# 一轮 N 题：自动拉取未解题目 → 解题 → 提交 flag → 本轮结束退出
uv run ctf-solve --platform ret2shell --round 3 --max-challenges 1
```

给运行中的协调器发消息：`uv run ctf-solve-msg "提示内容" --port 9400`

### 运行输出：思考过程与解题动作

加 `-v` 后，控制台会实时打印每个 solver 的动作和思考摘要，行首是 `题目/模型`：

```
ez_BASE_revenge/deepseek-flash › bash {'command': 'cat flag5.txt ...'}
ez_BASE_revenge/deepseek-flash ‹ moectf...（工具输出，截断成一行）
ez_BASE_revenge/deepseek-flash 💭 44 distinct offsets, max 74. 试试 base100...
ez_BASE_revenge/deepseek-flash › submit_flag {'flag': 'moectf{...}'}
ez_BASE_revenge/deepseek-flash ‹ CORRECT —  "moectf{...}" accepted. 解题成功!
ez_BASE_revenge/deepseek-flash 💭 Flag: moectf{...} Submit.
```

- `›` = 调用的工具与参数；`‹` = 工具返回；`💭` = 模型思考摘要；其余文字是模型边做边说的话。
- `-v` 只放开本项目的 DEBUG 日志；`httpx`、`openai` SDK 的 HTTP 噪音（`Building HTTP request` /
  `request_id` 之类）已统一压到 WARNING，不会再刷屏。
- **思考已改为中文**：system prompt 中要求模型用简体中文推理（命令/代码/flag 保持原样），
  所以 `💭` 行现在基本是中文。
- **运行中给提示（类似 Codex 底部输入框）**：round / `--challenge` 模式启动后，
  直接在终端里输入一行文字并回车，就会排队注入正在解题的 agent：

  ```
  ↵ 提示已排队 先看看 note.ko 的 ioctl 参数，别急着写 exploit
  ```

  注入的内容会附在 agent 下一次工具返回的末尾（`[操作员提示 / OPERATOR HINT …]`），
  模型当步就能看到并按提示调整方向；trace 里也会记录一条 `hint_injected` 事件。
  多个 solver 并发时提示会先到先得，建议配合 `--max-challenges 1`。
- **中文防漂移**：长时间跑题时模型可能慢慢切回英文。现在每次请求都带
  `instructions` 里的「始终用简体中文思考」，并且每个工具结果后面都会追加一句
  「继续用简体中文思考」的提醒，不需要人工干预。
- **网页观察台**（两个题同时跑时推荐）：

  ```powershell
  uv run python scripts/webui.py        # 打开 http://127.0.0.1:8099
  ```

  每道题一个面板，实时显示 `💭` 思考、`›` 工具调用、`‹` 结果和提交状态；
  配置页的「方向」和「难度」都是**勾选框**：只勾要跑的，全部不勾 = 不限；
  保存后写回 `.env` 的 `CHALLENGE_CATEGORIES` / `CHALLENGE_DIFFICULTY`。
- 左侧列表每项和顶部标题都会显示**方向、分值和难度**（如 `misc · 100 分 · 简单`），
  侧栏与日志之间那条竖线可以拖动调宽（双击恢复，宽度记在浏览器里）。
  面板底部有输入框，发出去的提示写进 `logs/hints/<题目>.jsonl`，
  正在跑的 solver 会自动读取并注入——效果和终端里手打一样，但不用盯着控制台。
  `--port 8100` 可换端口。左侧列表**只显示本次启动之后的 solver**：重启网页后
  旧的记录不会再出现；跑完的题会自动从列表消失，勾选「显示已结束」才会保留
  （且只保留本次会话的），每项后面带 `· 时:分` 便于区分同一道题的多次运行。
- **并发数可以运行中改**：「解题观察」页的开始/停止按钮下面有「并发数（运行中可改）」，
  填数字点「应用」即可（也会写回 `.env` 的 `MAX_CONCURRENT_CHALLENGES`，下次打开配置页
  显示的就是这个值）。命令行运行时后台每 2 秒读一次 `logs/runtime.json`，日志里会出现
  `concurrency -> N`；调小不会打断已经在跑的题，只是不再启动新的。
- 配置页「模型配置」按**供应商分组**（DeepSeek 在最前，自定义供应商各自一组），
  每个模型一行：勾选 = 启用，右侧可填 **USD 限额**（`0` 或留空 = 不限）。
  花费按模型 spec 累加进 `config/model_quotas.json`；额度用完的模型 CLI 会自动跳过，
  面板在启动前也会直接拒绝并提示去调高限额。整组可用「全选 / 清空」。
- 完整细节（每次工具调用的完整参数和输出、每一步的思考摘要、耗时与 token）在
  `logs/trace-<题目>-<模型>-<时间>.jsonl`，可以 `Get-Content logs\trace-xxx.jsonl -Wait` 实时跟。
- 不加 `-v` 时只显示 INFO 级别：拉题、启动沙箱、找到 flag、费用汇总。
- **每题花了多少钱**：轮末汇总里每道题后面会带 `($0.0123)`，同时按花费从高到低
  打一段 `cost by challenge` 日志；面板「继续上次未完成的轮次」提示里也会显示
  这一轮已花的钱（如 `上次未完成：20261106-140022（3/10 已解，$0.184）`）。
  数据来源是 solver 写到 trace 里的 `usage` 事件（同题多模型会合并，`coordinator`
  单列），不额外调用模型；快照 `logs/runs/<id>/state.json` 每道题也记了 `cost_usd`，
  所以 `--resume` 之后仍能看到上次的花费。


## 五、注意

- 沙箱容器申请 16GB 内存上限，但 WSL 只分配 8GB（容器内可见约 7GB）；如需更大，改 `C:\Users\weich\.wslconfig` 后 `wsl --shutdown`。
- `backend/sandbox.py` 的 loop 设备映射已改为自动判断：宿主没有 `/dev/loop-control`（Docker Desktop 的 WSL2 VM 就没有）时自动跳过，无需手改。
- `sandbox.py` 里设置了 `CapAdd SYS_ADMIN/SYS_PTRACE` 与 `seccomp=unconfined`，用于挂载 / 调试类题目，勿在共享宿主机上跑不可信镜像。
- 镜像很大（SageMath + angr + torch + CADO-NFS），构建缓存默认保留 20GB，
  空间紧张时：`docker builder prune -f`。
- 首次 `docker pull` 走的是国内镜像源；若某镜像源失效，改 `C:\Users\weich\.docker\daemon.json` 后重启 Docker Desktop。
- **磁盘位置（2026-11-03 已迁移）**：Docker 的 WSL 数据（原 `C:\Users\weich\AppData\Local\Docker\wsl`，23.6GB）
  已移到 `F:\Docker\wsl-data` 并在原路径建了 junction；沙箱工作目录改到 `F:\ctf_agent\workspaces`
  （大附件解压不再占 C 盘，可用 `CTF_WORKSPACE_ROOT` 覆盖）；uv/pip/npm/HuggingFace 缓存已用 `setx`
  指到 `F:\ctf_agent\cache\*`。C 盘从 8.9GB 空闲回到 51GB。
  注意：`setx` 只对新开的终端生效，已开着的窗口要重开。

## 六、Ret2Shell 平台（西电 CTF 终端 / MoeCTF）

### 1. 原理

- `backend/platform.py` 按 `PLATFORM`（`auto` / `ctfd` / `ret2shell`）选择客户端；`auto` 时只要 `.env` 配了
  `RET2SHELL_TOKEN` 就走 Ret2Shell，否则走 CTFd。
- `backend/ret2shell.py` 与 `CTFdClient` 接口完全兼容（`fetch_challenge_stubs` / `fetch_all_challenges` /
  `fetch_solved_names` / `submit_flag` / `pull_challenge` / `close`），所以 poller、协调器、swarm 以及
  solver 的 `submit_flag` 工具都不用改。
- API 前缀 `/api`，认证头 `Authorization: Bearer <token>`；token 就是网页端
  `localStorage.account.token`（HS256 JWT，服务端还要求它存在于登录缓存中，所以必须是刚登录的有效会话）。

### 2. 全自动一轮

```powershell
# 随机抽 3 道未解题（默认随机，解完即退出）
uv run ctf-solve --platform ret2shell --round 3 --max-challenges 1 -v

# 只解名字含 ez_BASE 的题；--min-score 0 表示连 0 分题也要（默认 1，会跳过签到/海报类）
uv run ctf-solve --platform ret2shell --round 1 --only "ez_BASE" --min-score 0 --max-challenges 1 -v

# 想按分值从低到高（原来的行为），或允许重复做最近做过的题
uv run ctf-solve --platform ret2shell --round 3 --order score --max-challenges 1 -v
uv run ctf-solve --platform ret2shell --round 3 --retry --max-challenges 1 -v

# 想重做平台上已经解过的题
uv run ctf-solve --platform ret2shell --round 1 --include-solved --only ez_ --max-challenges 1 -v
```

选题规则：

- 默认 **分层随机抽**（`--order random`）：先从每个难度档（困难/中等/简单/入门）各抽 1 道、再从每个方向
  （web/pwn/misc/re/crypto）各抽 1 道，剩下的按难度均衡补足，所以一轮 10 题一定同时有多个难度和多个方向，
  不会只抽到简单题、也不会完全没有 web/pwn；`--order hard` 是难度优先，`--order score` 最低分优先，`--order name` 按名字排序。
- **容器自动销毁**：每道题结束（解出 / 放弃 / 超时 / 手动跳过）都会调用平台的 stopChallenge 关掉靶机；
  面板「停止」因为直接 taskkill 进程树，会额外调用 scripts/close_envs.py 兜底；下一次「开始解题」前也会先清一次残留。
  手动排查：uv run python scripts/close_envs.py（打印 closed N target(s)）。
- **容器数上限**：面板「配置 → 平台配置 → 允许同时开启的容器数」（或 .env 的 MAX_ENVIRONMENTS，0 = 按平台配额）。
  超出上限的容器题会排队等待（日志 Target capacity full …），不会去扫 host.docker.internal。
- **断点续跑**：每轮会把进度写进 `logs/runs/<run_id>/state.json`（每题状态 running/solved/timeout/skipped…）。
  面板「运行控制 → 继续上次未完成的轮次」会用 `--resume latest` 只跑上次没跑完的题；
  CLI 等价写法 `uv run ctf-solve --resume latest`，也可以指定某个 run id（目录名）。
  续跑不会重新解已解出的题，跨轮笔记（`logs/memory/`）仍然有效。
- **方向经验清单（知识库）**：`knowledge/<web|pwn|re|crypto|misc>.md`，按题目方向注入 solver 提示词
  （`KNOWLEDGE_ENABLED=1` 控制，关闭用 `--no-knowledge`）。内容是可以直接改的 Markdown：加了新套路就写进去，
  下一轮立即生效，不用改代码。
- **MCP 工具**：`config/mcp.json`（参考 `config/mcp.example.json`）里配置 stdio MCP server，例如
  `{"servers":[{"name":"fetch","command":"uvx","args":["mcp-server-fetch"]}]}`；启动时自动注册成
  `<name>_<tool>`，供 solver 直接调用。文件不存在就不启用，配置坏了只会 warning，不会影响解题。
- **Flag 格式 / 提交格式**：面板「配置 → 平台配置」最上面两项（或 `.env` 的 `FLAG_FORMAT` / `FLAG_SUBMIT_MODE`）。
  `FLAG_FORMAT` 写本场比赛的形态，如 `moectf{}`、`SYC{}`、`DASCTF{}`——它会作为提示写进 solver 提示词，
  并在提交时按前缀做一次软校验（不匹配只记 warning，不会拦提交）。
  `FLAG_SUBMIT_MODE=full` 提交完整 flag；`inner` 只提交花括号内内容（客户端自动去掉 `PREFIX{...}` 外壳，
  适合 DASCTF / 羊城杯这类「仅需提交 {} 内内容」的平台）。
  CLI 对应 `--flag-format 'SYC{}'` 与 `--flag-submit-mode inner`。
- **中文思考**：面板「配置 → 解题配置 → 中文思考」（`.env` 的 `THINK_CHINESE=1`，CLI `--think-chinese/--no-think-chinese`）。
  开启时每次请求都带中文思考指令，并在每个工具结果后追加一句提醒（长跑也不会漂回英文）；
  关闭则用模型默认语言（一般英文），适合想省 token 或看英文推理。
- **拉题跳过已解**：面板「配置 → 解题配置 → 拉题跳过已解」（`.env` 的 `SKIP_SOLVED_PULL=1`，CLI `--skip-solved/--no-skip-solved`）。
  拉题前先向平台核对已解集合，已解出的题直接跳过（日志 `= <题名>: already solved on the platform - skipped`），
  不再起容器、不开 solver；勾了「含已解题」时该开关自动失效（用于复练）。
- **干净模式（测试模型真实水平）**：面板「配置 → 解题配置 → 干净模式」（`.env` 的 `FRESH_SOLVE=1`，
  CLI `--fresh`）。开启后：不把 `logs/memory/<题名>.md` 注入提示词、不提供 `remember`/`recall` 工具、
  解题过程也不写笔记；轮次开始前清掉 `challenges/` 里的旧题目录，单题模式清掉该题的 `workspace/`。
  这样模型只能看附件自己解——同一道题的对照实验（普通模式 8s 秒解 vs 干净模式 3 步推理）就是这么跑出来的。
- **两个「已解」开关的区别**（最容易混淆的一对）：`含已解题`（`ROUND_INCLUDE_SOLVED`）决定
  **已解题要不要进本轮候选池**；`拉题跳过已解`（`SKIP_SOLVED_PULL`）只决定**已解题要不要在拉取时跳过**。
  平台报 10/10 已解时，只关掉「拉题跳过已解」仍然是 0 道候选，必须勾「含已解题」才会开打（勾了前者面板会把后者置灰）。
- **日志脱敏**：`TRACE_MASK=1`（默认，CLI `--trace-mask/--no-trace-mask`）会让 `logs/trace-*.jsonl`
  里的 flag 只留头尾（`flag{abcd…wxyz}`），`sk-...` / `ak_live_...` / JWT / `SessionStore=` 一律替换成
  `<api-key>`、`<jwt>` 之类的占位符——面板「解题观察」读的就是这些文件，所以界面上同样看不到明文。
  复盘需要原文时用 `TRACE_MASK=0` 重启一轮；发布仓里的 `logs/` 本来就不入库。
- **跨轮笔记（challenge memory）**：同一道题可能先后被多个 solver 做（额外轮数、超时重建、换模型重跑）。
  解出的 flag、被拒绝的 flag、以及 solver 用 `remember` 记下的关键结论，都会写到 `logs/memory/<题名>.md`；
  下一轮启动时会把摘要注入提示词（`## 队友之前的分析`）。所以重开一轮不用从零再来，
  也避免反复提交同一个错误 flag。`recall` 工具可以随时查看笔记，删掉这个文件即可重置该题记忆。
- 单题卡住时有两个止损开关：`--challenge-timeout 10`（分钟，或 `.env` 的 `CHALLENGE_TIMEOUT_MIN=10`）到点放弃该题、
  把并发位让给下一题（**round 模式与协调者模式都生效**：协调者每 spawn 一道题都会单独计时）；
  Web 面板里选中该题点「跳过此题」会立刻停止（状态记为 `skipped`）。
- **Writeup**（面板「解题配置 → 写 Writeup」，或 `.env` 的 `WRITEUP_ENABLED=1`，CLI `--writeup`）：
  每解出一道题，会再用一次模型把 trace 整理成中文 Writeup，存到 `writeups/<方向>/<题名>.md`
  （round / 协调者 / 单题模式都生效；`--challenge-timeout` 超时或 `--no-submit` 演练解出的题也会写）。
  目录由 `WRITEUP_DIR` 控制（默认 `writeups`，已加入 `.gitignore`）。写 WP 失败只打 warning，不影响解题结果。
- **刷题模式**（`--rotate`，面板「刷题模式」复选框，或 `.env` 的 `ROUND_ROTATE=1`）：把题目按方向分组，
  一批只解一个方向——第一批全是 `misc`，下一批全是 `re`，再下一批 `crypto`……批大小由 `--rotate-batch N`
  （`ROTATE_BATCH`，0 = 等于并发数）决定。**批内难度交错**：批大小 ≥4 时，只要池子里有，就一定有
  困难/中等/简单/入门各一道（CTF² 所有题都是 1 分，靠分值排序没有意义，所以这里按难度标签均衡）。
  需要靶机的题仍然受平台环境配额限制：配额满了就排队等，附件题继续占用并发位。
  ```bash
  # 先 5 道 misc，再 5 道 re，每批内部混合难度
  uv run ctf-solve --platform ctf2 --round 10 --max-challenges 5 --rotate --rotate-batch 5 -v
  ```
- 默认只从**未解**的题里抽；加 `--include-solved`（或 `.env` 里 `ROUND_INCLUDE_SOLVED=1`）后，
  平台上已解的题也会进入候选池，用 `--only` 指定具体题目最稳妥。
- 默认会**跳过 6 小时内做过的题**（`--cooldown-hours 6`，记录在 `logs/round-history.json`），
  连续跑多轮时不会重复抽到刚失败的题；`--retry` 或 `--cooldown-hours 0` 关闭这个限制。
- 如果整个候选池都在冷却期内（题太少时），会退一步允许重做，不会空转。
- 已解出的题再次提交时，客户端会直接返回 `already_solved`，**不会再消耗平台的提交次数**；
  想真正让平台重新校验，目前只能换新题或等平台允许重放。

方向过滤（默认开启）：只拉 `web,misc,pwn,re,crypto` 五个方向，站点上的中文分类按关键字映射——
`Web 安全与渗透测试`→web、`取证与安全杂项`→misc、`二进制漏洞审计`→pwn、`软件逆向工程`→re、
`现代密码学`→crypto；`Python 沙箱逃逸`、`开发与运维基础`、`策略与博弈`、`大语言模型应用安全`、
`从此开始`、`美工设计` 等方向不会拉取。改 `.env` 的 `CHALLENGE_CATEGORIES` 或加 `--categories`
调整，`--categories all` 关闭过滤。当前是 **107/149 道题**在范围内。

难度过滤：站点把难度写成 tag（`入门` / `简单` / `中等` / `困难`），可用 `--difficulty` 指定：

```powershell
# 只做简单题
uv run ctf-solve --platform ret2shell --round 3 --difficulty 简单 --max-challenges 1 -v
# 简单 + 中等（英文别名 easy/medium/hard 也可以）
uv run ctf-solve --platform ret2shell --round 3 --difficulty "简单,中等" --max-challenges 1 -v
```

- 只有打了难度 tag 的题会被选中；没打 tag 的题在指定难度时不参与（默认不指定 = 全部参与）。
- 难度和方向过滤可以叠加，例如 `--categories re --difficulty 困难`。
- 写错难度会直接报错并列出可选项；查看当前难度分布：
  `CHALLENGE_DIFFICULTY="简单,中等" uv run python scripts\list_ret2shell.py`（表格里有 Difficulty 列）。

流程：

1. `GET /api/game` 选比赛（`RET2SHELL_GAME` 可写 id 或名字，留空自动选进行中的）；
2. `GET /api/game/{id}/challenge` 拉题目列表（含题面 markdown、分类 tag、分值），按方向过滤；
3. 对每道题 `GET .../submit` 查是否已解，再用 `--min-score`（默认 1）、`--only`（名字子串，可重复）
   和冷却时间过滤，按 `--order` 抽/排 N 道（N = `--round`）；
4. `GET .../file` 列附件 → 下载到 `challenges/<slug>/distfiles/`，并写 `metadata.yml`；
5. 每道题启动一个 ChallengeSwarm 在沙箱里解题，solver 找到 flag 后通过 `submit_flag` 工具提交；
6. 平台 checker 是异步的：提交后客户端轮询 `GET .../submit?id=<submission_id>`，最多 25 秒拿判定；
7. 所有题跑完（不论是否解出）打印汇总并退出；拉题失败时退出码为 1。

也可以用常驻协调器模式（不设 `--round`）：协调器会自己从平台拉题、起 swarm、提交。

### 3. flag 规则文件 INSTRUCTIONS.md

- 文件内容会被原样注入每个 solver 的 system prompt（`## Platform Rules` 段，声明为最高优先级）。
- 用来固定：flag 格式、提交方式、禁止占位符、平台限流、附件目录与网络说明。
- 换比赛或换 flag 格式只改这个文件，不用改代码；也可用 `--instructions xxx.md` 指定别的文件。

### 4. 注意

- token 会过期（重新登录后旧 token 失效）；遇到 `401 please login first` 就重新复制
  `localStorage.account.token` 到 `.env`。
- 方向过滤默认只保留 web/misc/pwn/re/crypto 五类；要拉"沙箱逃逸""开发运维""AI 安全"等方向时
  用 `--categories all`（或改 `CHALLENGE_CATEGORIES`）。
- 提交限流 10 次 / 5 分钟；客户端最小间隔 6 秒，遇到 429 会停下并提示，不要连续猜 flag。
- 有前置题（prerequisites）未解时提交返回 403；隐藏/未发布题目不会出现在列表里。
- 并发：`--max-challenges` 是并发题数，实际容器数 = 并发题数 × 模型数；WSL 只有约 7GB 可用内存，
  建议 `--max-challenges 1`。
- 目前只实现"拉题 + 附件 + 提交"；远程环境（`/env`、`/instance`）和提示解锁（`/hint/unlock`）尚未接入，
  `connection_info` 来自题面，必要时可手工写进 `metadata.yml`。

### 5. 实测记录（2026-11-03，已跑通）

```
uv run ctf-solve --platform ret2shell --round 1 --only "ez_BASE" --min-score 0 --max-challenges 1 -v
→ Platform: ret2shell (https://ctf.xidian.edu.cn)
→ Ret2Shell game: MoeCTF 2026 (id=37)
→ Challenges: 149 total, 60 solved, 89 unsolved -> this round: 1 (only: ez_BASE)
→ 自动下载 xiaozhitiao.zip → challenges\ez-base\distfiles\
→ DeepSeek 10.6s 解出 moectf{Y0u_h@v3_kn0wn_b@sE64}，submit_flag 返回 CORRECT（解题成功）
→ 平台复查：ez_BASE 变为 solved；Round finished - stopping.
```

- 整轮花费 `$0.0024`；token 有效期内可直接重复跑。
- 第二次实测（带实时思考输出）：`--only ez_BASE` 自动选中未解的 `ez_BASE_revenge`，
  模型可见地连续尝试 emoji 偏移 → Base64 → Base58 → Base32，93.7 秒解出
  `moectf{3m0j1_15_50_cu73_2333333}` 并提交成功，花费 `$0.0194`。
- 题量/分值分布可用 `uv run python scripts\list_ret2shell.py` 查看（含已解状态与前三道未解题的附件列表）。

## 七、DASCTF 平台（羊城杯 / AI Agent API）

### 1. 原理

DASCTF 给参赛 Agent 提供了一个比赛能力 API（`SERVER HOST` + `ACCESSKEY`，
在比赛控制台「平台接入凭证」面板里，只用于比赛接口，不是大模型 key）：

```
GET  {host}/slab-match/api/v1/agent/ctf/exercise-list          # 题目列表（分类 → corpus）
GET  {host}/slab-match/api/v1/agent/ctf/exercise?exerciseId=N  # 题目详情 + 附件 + 远程环境
POST {host}/slab-match/api/v1/agent/ctf/build-exercise-env     # 启动远程环境（需要时）
POST {host}/slab-match/api/v1/agent/answer-panel/answer        # 提交 flag
```

认证头是 `X-Agent-AccessKey: ak_live_...`，响应统一为
`{"code":"00000","message":"","data":{...}}`。

### 1.1 复刻版 / 训练平台（已兼容）

有些复制版平台（例如「AI Agent CTF · 十题测试赛」这种本地复刻）接口一致但有两处差异，
客户端现在会自动适配，不需要改配置：

| 差异 | 生产 DASCTF | 复刻版 | 我们的处理 |
| --- | --- | --- | --- |
| POST body | 双重编码 JSON（JSON 字符串里再套 JSON） | 普通 JSON | 先用双重编码，遇到 `40400 exercise not found` / 参数错误就改用普通 JSON 并记住（`_plain_body`） |
| `build-exercise-env` | 可用 | 常返回 `40400` | 不起环境、不空等；`isNeedInit=false` 的附件题直接跳过 |
| 已解题再提交 | 返回 `ALREADY SOLVED` | 只有真提交才记账 | 勾「含已解题」时 `resubmit_solved=True`，会真的 POST（能验证提交链路） |

提交格式两种平台一致：只交 `{}` 内内容，例如 `m1sc_l4y3rs_b64_hex_rot13`。
成功响应：`{"code":"00000","message":"解题成功!","data":{"isCorrect":true,...}}`；
失败响应会带剩余次数：`40001 提交flag错误，请重新提交（当前还有 N 次提交机会）`。

### 2. 配置

`.env`：

```ini
DASCTF_URL=https://pro.dasctf.com
DASCTF_ACCESS_KEY=ak_live_xxxxxxxx
```

运行时显式指定平台：`--platform dasctf`（`PLATFORM=auto` 时，如果只配了
`DASCTF_ACCESS_KEY` 也会自动选中；同时配了 Ret2Shell token 时优先 Ret2Shell）。

### 3. 全自动一轮

```powershell
# 随机拉 1 道未解题 → 起环境/下附件 → DeepSeek 解题 → 自动提交 → 结束退出
uv run ctf-solve --platform dasctf --round 1 --max-challenges 1 -v

# 只做某一类（题目名里含 CRYPTO / MISC / WEB ...）
uv run ctf-solve --platform dasctf --round 1 --only CRYPTO --max-challenges 1 -v

# 只看题目和附件、不提交（调试拉题）
uv run python scripts\pull_dasctf.py

# 查看列表/附件/环境（只读，不消耗提交次数）
uv run python scripts\list_dasctf.py
uv run python scripts\list_dasctf.py --categories pwn

# 单题模式（自己控制节奏）：先拉题，再随时开一局
uv run python scripts\pull_dasctf.py
uv run ctf-solve --platform dasctf --challenge challenges\pwn --max-challenges 1 -v
```

单题模式会自动检查 `metadata.yml` 里的 `connection_info`，为空时调用
`build-exercise-env` 拉起远程环境并写回 `metadata.yml`。

### 4. flag 规则（已写入 INSTRUCTIONS.md）

- 平台规则：flag 形如 `DASCTF{...}` 或 `flag{...}`，**提交时只提交 `{}` 内的内容**
  （客户端会自动去掉前缀/花括号）；题目另有格式要求的以题面为准。
- 每场共 50 次提交机会；提交错误返回
  `40001 提交flag错误，请重新提交（当前还有49次提交机会）`，剩余次数会显示在工具结果里。
- 提交是同步返回 `isCorrect` 的，客户端直接映射为 `CORRECT` / `INCORRECT`。
- 附件可能是单个对象（`attachment.url`），也可能在描述里给下载链接，客户端两种都会下载。

### 5. 注意

- 平台接口是单场次凭证，比赛结束/刷新后 access key 会失效，需要重新复制。
- `scripts\smoke_dasctf.py` 是最小连通性测试；`scripts\list_dasctf.py` 是只读清单（题目、分值、难度、已解状态、附件、远程环境），排查问题先用它。
- 远程环境（`endpoints`）由 `build-exercise-env` 创建，构建后客户端会轮询详情直到
  `endpoints` 非空；`connection_info` 会自动写进 `metadata.yml`（含 IP:端口、代理端口、过期时间）。
  提交正确后客户端会自动调用 `recover-exercise-env` 回收环境。
- 列表接口没有分值/难度，客户端会逐题拉详情补全（题目少，开销可接受）。
- 并发建议同 Ret2Shell：`--max-challenges 1`（WSL 约 7GB 内存）。

## 八、CTF² Agent Arena（ctf2.dasctf.com）

### 1. 原理

CTF² 给每个 Agent 发一个 PAT（在 Agent 详情页 **connect / 连接** 标签里，
变量名 `CTF2_AGENT_TOKEN`）。同一个页面还会给出 MCP 地址
（`/api/ai/v1/mcp`）和 Codex / Claude 的配置片段；本项目的做法是直接走
**Agent Open API**，不需要 MCP。

```
GET  {host}/api/open/v1/user/agent/me/                      # Agent 身份、配额、规则
GET  {host}/api/open/v1/user/practice/                      # 练习场（grounds）
GET  {host}/api/open/v1/user/practice/{id}/challenges/       # 题目列表
GET  {host}/api/open/v1/user/practice/{id}/challenges/{cid}/ # 详情（files / has_container）
GET  .../files/{fileId}/download/                            # 5 分钟签名下载地址
POST .../environment/start/  |  GET .../environment/         # 起靶机 / 轮询 access_ready
POST .../submit/  {"flag": "...", "confirmation": true}      # 提交
```

认证头 `Authorization: Bearer <token>`，响应统一
`{"data": {...}, "success": true}`。

### 2. 配置

`.env`：

```ini
PLATFORM=ctf2
CTF2_URL=https://ctf2.dasctf.com
CTF2_AGENT_TOKEN=...
CTF2_GROUND=            # 可选：只做某个练习场（id 或 slug）
```

练习场 id 的找法：打开练习场页面，地址栏
`https://ctf2.dasctf.com/dashboard/practice/<练习场id>?tab=overview`
中间那段 UUID 就是 id（例如 BUUCTF =
`b9bbb32f-f186-458f-b90b-12440c0f6aea`）。也可以直接跑
`uv run python scripts\list_ctf2.py`，第一屏 `Grounds:` 会列出全部
`id:名字`；命令行用 `--ctf2-ground <id 或名字>`，Web 配置页填同一字段。
**该字段也接受整条练习场页面 URL**（会自动抽出里面的 UUID），所以从地址栏
直接整段粘贴进配置页也能用；填了但对不上时会直接报错并列出可用的练习场，
不会静默地"0 道题"。
当前 6 个练习场共 **3721 题**（BUUCTF 3244、BUUCTF-Real 277、DASBOOK 92、
N1BOOK 46、BUUCTF-Basic 36、CTF2日常练习场 26）。

### 3. 使用

```powershell
# 只读：Agent 身份/配额 + 全部练习题（分类、分值、难度、是否已解）
uv run python scripts\list_ctf2.py
uv run python scripts\list_ctf2.py --categories pwn --difficulty 困难

# 全自动一轮：随机 1 道未解题 → 下附件 → 起环境 → 解题 → 提交
uv run ctf-solve --platform ctf2 --round 1 --max-challenges 1 -v

# 单题模式（先拉到 challenges\ 再随便开）
uv run ctf-solve --platform ctf2 --challenge challenges\my-task -v
```

### 4. 规则与限制（已写进适配器）

- 提交必须带 `confirmation: true`；`data.accepted` 为真才算正确，
  返回值里的 `attempts_left` 会显示在工具结果中。
- flag **原样提交**（不做 `{}` 去前缀），长度 1..4096。
- 平台限流：每分钟约 120 次读、30 次写；默认只允许 1 个靶机环境。
  客户端会缓存列表/详情、提交间隔 3 秒、429/5xx 按 `Retry-After` 重试。
- 附件用 `files[].id` 换签名 URL 下载；带 `has_container` 的题会自动
  起环境并轮询到 `access_ready`，把 `access_url` / `access_urls` 写进
  `metadata.yml` 的 `connection_info`。
- Web 配置页的「平台配置」里选 `CTF² Agent Arena`，填站点地址和
  Agent Token 即可，不需要命令行参数。
- `.env` 里 `CHALLENGE_CATEGORIES`（默认 `web,misc,pwn,re,crypto`）会
  过滤题目：想跑别的方向（例如 MISC）而当前被设成 `re,crypto` 时，加
  `--categories all`，否则会出现 `this round: 0`。
- 实测：`BigMak`（MISC/简单/100 分）17 秒解出并提交成功
  （`CORRECT — BigMak solved on CTF² (+100 pts)`，平台 stats 变为
  `solved_count=1, total_score=100`）。

## 九、运行保护（借鉴 refs/agent 的 Go 版实现）

这些机制来自 `refs/agent`（用户提供的参考 agent），已经移植进 Python 版：

1. **平台请求限速**：所有平台 API 请求（含重试）之间至少间隔
   `PLATFORM_REQUEST_INTERVAL`（默认 0.8 秒）。时间戳写在
   `logs/.platform-request.state`，用操作系统文件锁保护，所以同一目录下开两个
   runner 也会互相限速。以前一轮里连发详情请求容易吃 429，现在不会。

2. **提交去重**：flag 在发给平台**之前**先写进 `logs/submissions.sqlite`
   （键 = 平台+token 作用域、题目、规范化后的 flag，flag 内部空白会折叠）。
   同一个 flag 永远不会提交第二次，重启也不会；再次遇到时直接复用当时的结果
   （正确 → `ALREADY SUBMITTED`，错误 → `INCORRECT — this exact flag was
   already rejected …; not resubmitted`）。题目、平台或 token 变了就是新作用域。

3. **永久暂停**：答题接口返回 `40409` 表示该题**提交次数已用完**，题目会写进
   `logs/pauses.json` 永久跳过（重启仍生效，轮次不再抽到它）。而
   `build-exercise-env` 返回 `40409` 只是靶机容量满，**不会**暂停题目，只让当前
   worker 失败退出。

4. **靶机对账**：自己开过的靶机记录在 `logs/target-envs.json`；每轮开始前调用
   `reconcile_envs()`，把上次崩溃/结束后遗留的环境逐个关掉（每个 30 秒超时），
   避免占满平台那 1 个环境配额。

5. **双工作池**：附件题和需要靶机的题分成两个池
   `MAX_ATTACHMENT_WORKERS`（默认 4）、`MAX_TARGET_WORKERS`（默认 0 = 用平台配额），
   再叠加全局 `MAX_CONCURRENT_CHALLENGES`。慢的靶机构建不会把快的附件题饿死。

6. **命令超时放宽**：`bash` 默认 120 秒（可传 1–3600 秒），和参考 agent 的
   `run_command` 一致；长时间反编译/编译不会半路被 60 秒掐断。

7. **提交去重与暂停的排查**：
   - 查看暂停名单：`logs/pauses.json`；
   - 清空暂停：删掉该文件或 `POST` 面板无此功能时直接删文件；
   - 查看提交记录：`sqlite3 logs/submissions.sqlite "select challenge,status,created_at from submissions"`（或用 Python `sqlite3`）。

新增环境变量（`.env.example` 已有）：

```ini
PLATFORM_REQUEST_INTERVAL=0.8
MAX_ATTACHMENT_WORKERS=4
MAX_TARGET_WORKERS=0
```
## 十、Ret2Shell 容器题与 WSRX 隧道（已打通）

Ret2Shell 的 web/pwn 题不在公网暴露端口：平台只给一个 `traffic` 令牌 + 容器端口，
浏览器通过 **WSRX（WebSocketReflectorX）** 把

```
wss://ctf.xidian.edu.cn/api/traffic/<traffic>?port=<port>
```

映射到本机端口再访问。适配器现在会自动完成这一整套：

1. `POST /api/game/<game>/challenge/<id>/instance` 启动容器（平台同时只允许 1 个实例，旧实例会先被停掉）；
2. `GET /api/game/<game>/instance` 里取 `traffic`；
3. 为每个端口启动一条隧道：
   `wsrx.exe connect "wss://<站点>/api/traffic/<traffic>?port=<port>" --host 0.0.0.0 --port <41000+>`
4. 把 `host.docker.internal:<local>` 写进 `metadata.yml` 的 `connection_info`，沙箱容器内可直接访问。

要点：

- **不需要**手动开 WSRX 桌面客户端，也不需要它监听 3307；用的是仓库里的
  `tools/wsrx/target/release/wsrx.exe`（可用环境变量 `WSRX_BIN` 指向别处）。
- 必须 `--host 0.0.0.0`：Docker Desktop 的容器无法访问只绑 127.0.0.1 的监听。
- 隧道登记在 `logs/wsrx-tunnels.json`，一轮结束（或面板点「停止」）会全部关闭；
  `uv run python scripts/check_wsrx.py` 可查看当前隧道。
- 平台限制同一时间 1 个实例，容器题由 `target` 池串行执行（不会互相抢实例）。

实测（2026-11-04）：MoeCTF「千度网盘」自动拉题 → 起实例 → 建隧道 → 容器内
`http://host.docker.internal:41000/` 访问成功 → 16 分钟解出并提交
`moectf{1dd77a9e-fe83-d4cf-2de5-8e57999cb4d6}`，`Solved 1/1 | cost $0.0230`，
结束时打印 `Closed 1 WSRX tunnel(s).`

## 十一、CTF+（ctfplus / 极客挑战赛）

站点不是 CTFd（`/api/v1/*` 全 404），认证用浏览器 Cookie **`SessionStore`**，
所有接口都是 JSON `POST`（`baseURL=/api`）。

### 1. 配置

```dotenv
PLATFORM=ctfplus
CTFPLUS_URL=https://geek2026.play.ctfplus.cn
CTFPLUS_TOKEN=<浏览器 Cookie 里的 SessionStore 值>
```

取法：登录站点 → F12 → Application/存储 → Cookies → 复制 `SessionStore` 的值。
面板「配置 → 平台配置 → CTF+ / 极客挑战赛」里粘贴也可以。

### 2. 命令

```bash
uv run python scripts/list_ctfplus.py                 # 只看不拉
uv run python scripts/list_ctfplus.py --categories web,pwn --difficulty 简单
uv run ctf-solve --platform ctfplus --round 1 --max-challenges 1 -v
uv run ctf-solve --platform ctfplus --challenge challenges/my-task -v
```

### 3. 接口映射（实测）

| 用途 | 调用 |
| --- | --- |
| 题目列表 | `POST /api/challenge/getChallengeList {"page":1,"page_size":100}` |
| 题目详情 | `POST /api/challenge/getChallengeDetailInfo {"id":"<字符串 id>"}` |
| 附件下载 | `GET /api/file/<attachment_path>` |
| 提交 flag | `POST /api/challenge/submitFlag {challenge_id, flag}` |

- 列表字段：`challenge_id / challenge_name / score / difficulty(0–5) / is_solved / tags / runtimeMode`；
- 详情：`short_des` 是 editor.js 富文本 JSON（适配器会抽成纯文本）、`attachments`、`address`、`sum_solves`；
- `runtimeMode != "none"` 视为需要靶机，走调度器的 target 池；
- **动态靶机会自动启动**：拉题时若 `address` 为空，适配器调用
  `POST /api/challenge/startChallenge {"id":"<id>"}`，把返回的 `address`
  （`nc1.ctfplus.cn 36331` 或 `https://<id>.challenge.ctfplus.cn`）写进
  `metadata.yml` 的 `connection_info`；靶机有数量上限，调度器按 target 池串行，
  轮次结束时 `stop_env` 调 `stopChallenge` 回收。
- flag 原样提交（不做 `{}` 去前缀）。
- 提交判定：`code 200` → `CORRECT`；`code 402`（你的队伍已解决该题目）→ `PRACTICE`；其它 → `INCORRECT`。
- **练习模式（`--include-solved`）**：已解题平台不允许重复提交，flag 无法验证；
  适配器返回 `PRACTICE`（不算正确），agent 必须继续分析并给出自己推导的 flag，
  整轮以「未验证」计入结果，而不是白送一个 ALREADY SOLVED。

### 4. 注意事项

- 如果列表里全部 `is_solved: true`，`--round N` 会显示 `this round: 0` ——
  说明该账号没有未解题，不是接口问题；
- Cookie 会过期：出现 401 时重新登录并更新 `CTFPLUS_TOKEN`；
- 离线自测：`uv run python scripts/test_ctfplus_client.py` → `ALL CTFPLUS CLIENT CHECKS PASSED`。

### 4. 靶机续期与离线自检

- `ENV_HEARTBEAT_S`（默认 300 秒）控制「续期心跳」：每隔这么久，对**正在解**的题重新续一次实例寿命（Ret2Shell 走 `PATCH .../instance`，CTF+ 走 `/challenge/delayChallenge`，CTF² 走 `/environment/extend/`），避免一道题做 40 分钟时容器中途过期。`0` 关闭。
- 每次 `bash` 之前会先探测题目给的 `host:port`（30 秒缓存一次）：连不上就直接返回 `TARGET DOWN: ...` 并通知协调者重建，而不是让模型去 `nmap host.docker.internal` 扫端口。
- 自检：`uv run python scripts\test_heartbeat.py`（解析 / 探测 / 心跳 / 门控四段）。

## 十一又四分之三、手动选题（只跑我点的那几道）

面板右侧「题目总览」的每个方格都可以点：

1. 点右上角 **选择**（或直接点任意方格）进入选择模式，方格会变成橙框；
2. 点要跑的题（可多选，再点一次取消），底部出现 **「已选 N 道 / 清空 / 开始所选」**；
3. 点 **开始所选** → 使用当前「解题配置」的参数，只跑这几道题。

行为细节：

- 选题绕开抽题器和冷却时间（你点名了就立刻跑），但仍受平台配额、单题超时、靶机 slot 限制；
- 如果选中的题**平台已标记已解**，会自动帮你勾上「含已解题」（否则只会立刻回 `ALREADY SOLVED` 不真正重做）；
- 想长期固定只跑某几道，也可以写 `.env`：`PICK_CHALLENGES=Layers,Small e`（逗号分隔，支持名称片段、不区分大小写）；
- 命令行等价写法：`uv run ctf-solve --round 2 --pick "Layers" --pick "Small e"`（`--pick` 可重复）。

日志里会有：

```
Pick: 2/2 requested challenge(s) matched: Layers, Small e
```

没匹配上时不会退回「跑全部」，而是直接结束并提示：

```
Pick: 0/1 requested challenge(s) matched
Not on the platform: No Such Challenge
```

## 十一又半、速攻模式与「并发为什么没用」

### 1. 速攻模式（blitz）

目标：**先把简单题吃干净**，别让几道困难题把整轮进度拖死。

- 面板：配置 → 解题配置 → 勾「开启速攻：先做简单题，单题超时直接换下一道」。
- .env：BLITZ_MODE=1；可选 BLITZ_MAX_CHALLENGES=0（0 = 整个候选池）、BLITZ_TIMEOUT_MIN=0（0 = 6 分钟）。
- 命令行：uv run ctf-solve --round 999 --blitz --blitz-timeout 6。

开启后：
1. 候选池按「入门 → 简单 → 中等 → 困难」排序，同难度按分值升序（便宜的先做）；
2. 不再受「本轮题数」限制，勾选的整个池子都会排在队里；
3. 单题预算用 BLITZ_TIMEOUT_MIN（默认 6 分钟），超时立刻换下一道，而不是等 10 分钟；
4. 平台报「已解」的题照样跳过（除非勾「含已解题」）。

### 2. 靶机已死会立刻放弃（target down）

以前靶机挂了，solver 会一直重试到单题超时（10 分钟），5 道 pwn 就是 50 分钟零产出。
现在靶机探测连续失败 TARGET_DOWN_LIMIT（默认 3）次，solver 立刻收尾、该题标记 target_down 换下一道，
日志会写：

```
! ret2libc: target down - skipped (rebuild it on the platform, then re-run this challenge)
```

平台侧把实例重建（或换一场比赛）后再跑即可。

### 3. 为什么「并发 8」看起来没用

并发只对**能同时跑**的题生效，而入口题的并发上限由平台给：

| 平台 | 同时可开的靶机 | 说明 |
| --- | --- | --- |
| Ret2Shell（西电 MoeCTF） | **1** | max_environments() 直接返回 1，一个账号只能开一个实例 |
| CTF+（极客挑战赛） | 2（可配 MAX_ENVIRONMENTS） | 面板「允许同时开启的容器数」 |
| CTF² Agent Arena | 2 | 平台配额 |
| DASCTF（复刻版） | 0 | 起靶机接口未实现，只能做附件题 |

所以当一轮全是 pwn（都要靶机）时，并发 8 也只有 1 道在跑；其余槽位会等靶机。
本轮实现会：
- 把容器题截断到平台配额，用**附件题回填**空槽（misc/re/crypto 混着选时并发才真的起来）；
- 没有附件题可回填时，日志明确告警：

```
Only 1 container challenge(s) can run at a time on this platform, and this pick has no
attachment-only work to fill the other 7 slot(s) - the extra concurrency stays idle.
Mix in other categories (e.g. misc/re/crypto) or raise the platform quota.
```

想让并发真正生效：勾多个方向（至少含 misc/re/crypto 这类附件题），或者换配额更高的平台。

## 十一又四分之五、模型请求要不要走代理（LLM_TRUST_ENV）

常见事故：关掉 Clash/VPN 之后，`HTTP_PROXY` 还留在环境变量里（`http://127.0.0.1:7890`）。
httpx 默认信任它 → 每个 solver 第一步就 `ModelAPIError: Connection error.`，面板上十几个 solver
全是「0 步 / $0」，日志里出现 `Broken (0 steps, $0) - not bumping` 与 `progress 12/13`。
平台侧不受影响（DASCTF/CTF+ 的客户端本来就用 `trust_env=False`），所以现场表现为
**题能拉下来、但一道也不做**。

`backend/models.py` 现在会先直连探测一次 base_url：

- 直连可用（`status_code < 500`）→ 忽略代理环境变量；
- 直连不通 → 才信任代理；
- 结果按 base_url 缓存在进程内，同一个 base_url 只探一次。

需要强制指定时：

```dotenv
LLM_TRUST_ENV=      # 留空 = 自动探测（推荐）
LLM_TRUST_ENV=1     # 强制走 HTTP(S)_PROXY（公司网络/必须走代理）
LLM_TRUST_ENV=0     # 强制直连（代理常年开着但不稳定时用）
```

自检：`uv run python scripts/test_model_proxy.py`（7 项：可直连/不可直连、0/1 覆盖探测、
探测只跑一次、azure/zen/deepseek/custom 四个 provider 都走同一入口）。

## 十一又六分之五、技能库（skills/，按需加载）

和 `knowledge/*.md` 的区别：knowledge 是"每个方向一段话"，**整段塞进提示词**；
skills 是"每个技术一个文件"，提示词里**只放一行索引**，模型真要用时再
`use_skill("pwn/format-string")` 把全文读进上下文。这样既能装几十个技术，
又不会把上下文撑爆、也不会让模型被无关技巧带偏。

目录结构（`backend/skills.py` 负责解析）：

```
skills/
  pwn/format-string.md        # 名字 = 相对路径去掉 .md
  pwn/ret2libc-leak.md
  pwn/heap-tcache.md
  web/ssti.md
  web/jwt-bypass.md
  web/php-deserialization.md
  re/upx-unpack.md
  re/pyc-and-dotnet.md
  crypto/rsa-classic.md
  misc/stego-and-zip.md
```

每个文件的 frontmatter：

```markdown
---
name: pwn/format-string
description: 一句话说明这个技能解决什么问题
when_to_use: 什么时候该加载它（这句话会进提示词索引）
categories: [pwn]
keywords: [fmtstr, %p, %n]
---
正文：命令、脚本模板、常见坑……
```

要点：

- **索引注入**：`skills.index_text(category)` 生成 `- `name` — when_to_use` 列表，
  同方向的排在前面，总长不超过 1600 字符；没有匹配时退回全部。
- **按需加载**：solver 有一个 `use_skill(name)` 工具，返回该技能正文（上限 8000 字符）；
  名字写错会回一句 `Unknown skill 'x'. Available: ...`。
- **开关**：面板「解题配置 → 技能库」、`.env` 的 `SKILLS_ENABLED=1`、
  CLI `--skills/--no-skills`；目录用 `SKILLS_DIR=skills`（相对仓库根目录）。
- **自己加技能**：在 `skills/<方向>/` 下新建 `.md`，写好 frontmatter 就会自动出现在索引里，
  不需要改代码。写"能直接抄的脚本/命令"比写原理更有用。

自检：`uv run python scripts/test_skills.py`（26 项：解析、索引预算、同方向优先、
`use_skill` 正常/未知名/空目录、提示词注入与关闭、schema/CLI/面板接线）。

## 十二、开发与自检（pytest / 覆盖率 / lint）

- 快速自检（不含 Docker 与模型调用，约 1.5 分钟）：

  ```powershell
  uv run pytest            # 41 个用例，等价于逐个跑 scripts/test_*.py
  uv run pytest -m slow    # 另外 5 个：sandbox 镜像、真实模型、联网价格
  ```

  每个用例在独立进程里执行对应的 `scripts/test_*.py`，失败时会把脚本输出尾部贴进报告。
  其中 `scripts/test_webui_js.py` 会把面板的 `<script>` 抽出来跑 `node --check`（没装 node 则跳过）——
  面板前端一旦出现语法错误，这个用例会立刻失败，而不是等你打开网页才发现按钮全都没反应。
- 覆盖率（脚本是子进程，所以用 `coverage run --parallel-mode` 逐个跑再 combine）：

  ```powershell
  uv run python scripts/coverage_report.py                 # 只跑快检，当前约 42%
  uv run python scripts/coverage_report.py --include-slow --fail-under 40
  ```

- 静态检查：`uv run ruff check backend scripts`（含 `S110`：禁止 `except: pass` 静默吞异常，这正是上次快照 bug 的类型）。
- 日志清理：`uv run python scripts/cleanup_logs.py --dry-run` 先看，再实际删除；面板启动时会自动清一次。

### 跨平台（Linux / macOS 主机）

进程管理已经抽到 `backend/procs.py`：`kill_tree()` 在 POSIX 上走
`killpg(SIGTERM) → 轮询 → SIGKILL`，`list_processes()` 用 `ps -eo pid=,etimes=,comm=,args=`，
面板回收残留 solver / 找端口占用进程都走这一层（POSIX 侧用 `lsof`）。
`backend/wsrx.py` 在 Linux 下会找 PATH 里的 `wsrx`（含 `~/.cargo/bin`），
用 `start_new_session=True` 代替 Windows 的 `creationflags`。

```bash
# Linux 上的等价流程
uv sync
cp .env.example .env       # 填 DEEPSEEK_API_KEY 与平台凭据
uv run python scripts/webui.py --port 8099
```

`WSRX_BIN=/path/to/wsrx` 可以指定二进制位置；Docker 沙箱镜像本身与平台无关。
