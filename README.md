# CTF Agent

Autonomous CTF (Capture The Flag) solver that races multiple AI models against challenges in parallel. Built in a weekend, we used it to solve all 52/52 challenges and win **1st place at BSidesSF 2026 CTF**.

Built by [Veria Labs](https://verialabs.com), founded by members of [.;,;.](https://ctftime.org/team/222911) (smiley), the [#1 US CTF team on CTFTime in 2024 and 2025](https://ctftime.org/stats/2024/US). We build AI agents that find and exploit real security vulnerabilities for large enterprises.

## Results

| Competition | Challenges Solved | Result |
|-------------|:-:|--------|
| **BSidesSF 2026** | 52/52 (100%) | **1st place ($1,500)** |

The agent solves challenges across all categories — pwn, rev, crypto, forensics, web, and misc.

## How It Works

A **coordinator** LLM manages the competition while **solver swarms** attack individual challenges. Each swarm runs multiple models simultaneously — the first to find the flag wins.

```
                        +-----------------+
                        |  CTFd Platform  |
                        +--------+--------+
                                 |
                        +--------v--------+
                        |  Poller (5s)    |
                        +--------+--------+
                                 |
                        +--------v--------+
                        | Coordinator LLM |
                        | (Claude/Codex)  |
                        +--------+--------+
                                 |
              +------------------+------------------+
              |                  |                  |
     +--------v--------+ +------v---------+ +------v---------+
     | Swarm:          | | Swarm:         | | Swarm:         |
     | challenge-1     | | challenge-2    | | challenge-N    |
     |                 | |                | |                |
     |  Opus (med)     | |  Opus (med)    | |                |
     |  Opus (max)     | |  Opus (max)    | |     ...        |
     |  GPT-5.4        | |  GPT-5.4       | |                |
     |  GPT-5.4-mini   | |  GPT-5.4-mini  | |                |
     |  GPT-5.3-codex  | |  GPT-5.3-codex | |                |
     +--------+--------+ +--------+-------+ +----------------+
              |                    |
     +--------v--------+  +-------v--------+
     | Docker Sandbox  |  | Docker Sandbox |
     | (isolated)      |  | (isolated)     |
     |                 |  |                |
     | pwntools, r2,   |  | pwntools, r2,  |
     | gdb, python...  |  | gdb, python... |
     +-----------------+  +----------------+
```

Each solver runs in an isolated Docker container with CTF tools pre-installed. Solvers never give up — they keep trying different approaches until the flag is found.

## Quick Start

```bash
# Install
uv sync

# Build sandbox image
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .

# Configure credentials
cp .env.example .env
# Edit .env with your API keys and CTFd token

# Run against a CTFd instance
uv run ctf-solve \
  --ctfd-url https://ctf.example.com \
  --ctfd-token ctfd_your_token \
  --challenges-dir challenges \
  --max-challenges 10 \
  -v
```

## Platforms

Two challenge sources are supported, selected with `PLATFORM` / `--platform`:

| Platform | Notes |
|----------|-------|
| `ctfd` | Classic CTFd: `CTFD_URL` + `CTFD_TOKEN` |
| `ret2shell` | 西电 CTF 终端 (`ctf.xidian.edu.cn`, e.g. MoeCTF) |
| `dasctf` | DASCTF / 羊城杯 AI Agent API (`pro.dasctf.com`) |

`auto` (the default) uses Ret2Shell when `RET2SHELL_TOKEN` is set, DASCTF when
`DASCTF_ACCESS_KEY` is set, otherwise CTFd.

### Ret2Shell / MoeCTF

`RET2SHELL_TOKEN` is the web app's session JWT: open DevTools → Console on the
platform and run `localStorage.account.token` (the server also requires the
token to be a live session, so copy it right after logging in).

```env
PLATFORM=auto
RET2SHELL_URL=https://ctf.xidian.edu.cn
RET2SHELL_TOKEN=eyJ...
RET2SHELL_GAME=          # game id or name; empty = the active game
CHALLENGE_CATEGORIES=web,misc,pwn,re,crypto   # only pull these directions; "all" = everything
CHALLENGE_DIFFICULTY=    # only pull these levels: 入门/简单/中等/困难 (easy/medium/hard)
ROUND_SIZE=0             # >0 enables round mode
ROUND_ORDER=random       # random | score | name
ROUND_COOLDOWN_HOURS=6   # skip challenges attempted in the last N hours
INSTRUCTIONS_FILE=INSTRUCTIONS.md
```

```bash
# One round: pull N random unsolved challenges, solve, submit, stop
uv run ctf-solve --platform ret2shell --round 3 --max-challenges 1 -v

# Cheapest-first instead of random, or allow retrying recent challenges
uv run ctf-solve --platform ret2shell --round 3 --order score --max-challenges 1 -v
uv run ctf-solve --platform ret2shell --round 3 --retry --max-challenges 1 -v

# Include challenges already solved on the platform (pair with --only)
uv run ctf-solve --platform ret2shell --round 1 --include-solved --only ez_ -v

# Override the direction filter for one run (or --categories all)
uv run ctf-solve --platform ret2shell --round 3 --categories "web,pwn" -v

# Only easy (简单) challenges, or easy + medium
uv run ctf-solve --platform ret2shell --round 2 --difficulty 简单 -v
uv run ctf-solve --platform ret2shell --round 2 --difficulty "easy,medium" -v
```

Round mode picks challenges at random by default **stratified by difficulty and
category**: it takes one challenge from every difficulty tag present
(`困难`/`中等`/`简单`/`入门`) and one from every category (`web`, `pwn`, `misc`,
`re`, `crypto`, …) before filling the rest tier-balanced, so a 10-challenge
round always mixes difficulties and directions instead of draining whichever
bucket comes first. `--order hard` = hardest first, `score` = cheapest first,
`name` = alphabetical. Attempts are remembered in `logs/round-history.json`,
skipping anything tried in the last `ROUND_COOLDOWN_HOURS` (default 6,
`--retry` / `--cooldown-hours 0` disables) so consecutive rounds keep exploring
new challenges instead of re-picking the same lowest-score ones. Add
`--include-solved` (`ROUND_INCLUDE_SOLVED=1`) to pull **everything** —
already-solved and unsolved challenges — and to ignore the cooldown window
entirely (otherwise a long cooldown can leave only solved candidates).
Re-solving a finished challenge short-circuits to `already_solved` on submit,
so no submission attempts are spent.

`--challenge-timeout MIN` (`CHALLENGE_TIMEOUT_MIN`) puts a wall-clock budget on
each challenge — in round mode *and* in coordinator mode, where each spawned
swarm gets its own timer: when it expires the solve is abandoned
(`status=timeout`) and
the concurrency slot goes to the next challenge — useful when a challenge
stalls on a dead end. In the dashboard, select a running challenge and press
**跳过此题** (skip) to stop it immediately (`status=skipped`); the panel shows
the reason in the log.

**Drill mode** (`--rotate`, dashboard checkbox `刷题模式`) changes the pacing
again: challenges are grouped by direction and handed out one direction at a
time — the first batch is all `misc`, the next all `re`, then `crypto`, and so
on — with each batch size `--rotate-batch` (default = concurrency). Inside a
batch the difficulty tiers are interleaved, so a batch of four or more contains
a `困难`/`中等`/`简单`/`入门` challenge whenever the pool has them (CTF² gives
every challenge 1 point, so score ordering cannot do this). Target challenges
still queue behind the platform's environment quota; when no target is free the
attachment-only work keeps the slots busy.

```bash
# five MISC challenges, then five RE ones, mixing difficulties in each batch
uv run ctf-solve --platform ctf2 --round 10 --max-challenges 5 --rotate --rotate-batch 5 -v
```

`CHALLENGE_CATEGORIES` defaults to the classic `web,misc,pwn,re,crypto`
directions. Ret2Shell category tags are free-form Chinese names, so the filter
maps keywords (`Web 安全与渗透测试`→web, `取证与安全杂项`→misc,
`二进制漏洞审计`→pwn, `软件逆向工程`→re, `现代密码学`→crypto) and skips the
rest (`沙箱逃逸`, `开发与运维`, `策略与博弈`, `AI 安全`, `美工设计`, …).

**Container challenges and WSRX.** web/pwn challenges on Ret2Shell are not
exposed on the public internet: the platform only hands out a `traffic` token
plus container ports, and the browser reaches them through
[WSRX (WebSocketReflectorX)](https://github.com/XDSEC/WebSocketReflectorX),
which tunnels `wss://<site>/api/traffic/<traffic>?port=<port>` to a local port.
The adapter therefore:

1. starts the instance with `POST /api/game/<game>/challenge/<id>/instance`
   (the platform allows **one** instance at a time, so old ones are stopped
   first and container challenges are serialised by the target pool);
2. reads `traffic` from `GET /api/game/<game>/instance`;
3. spawns `wsrx connect <url> --host 0.0.0.0 --port <41000+>` (binary from
   `tools/wsrx/target/release/wsrx.exe`, or `WSRX_BIN`) and writes
   `host.docker.internal:<local>` into `metadata.yml`'s `connection_info`.

Tunnels are registered in `logs/wsrx-tunnels.json` and closed when the round or
the dashboard run stops; `uv run python scripts/check_wsrx.py` lists them. The
`--host 0.0.0.0` flag matters: sandbox containers cannot reach a 127.0.0.1-only
listener, and without the tunnel the solver would guess host ports and get 502s
from the host proxy.


### Live output and operator hints

With `-v`, each solver streams its activity as `题目/模型 › tool {args}`,
`‹ tool output`, and `💭 reasoning`. Reasoning is prompted in Simplified Chinese
(tool arguments, code and flags stay untouched). SDK HTTP noise from `httpx` /
`openai` is muted, so only real activity shows.

While a round or `--challenge` run is going, type a line and press Enter in the
same terminal — it is queued and injected into the running solver's next tool
result as `[操作员提示 / OPERATOR HINT …]`, and the model follows it on the next
step (also recorded as a `hint_injected` event in the trace). With several
solvers in parallel the hint goes to whichever finishes a tool call first, so
`--max-challenges 1` keeps it deterministic.

### Web dashboard

```bash
uv run python scripts/webui.py        # http://127.0.0.1:8099
```

A dependency-free control panel (stdlib HTTP server) with two pages:

* **配置** — model settings (DeepSeek key / base URL / model checkboxes, plus
  **custom providers**), platform settings (DASCTF, Ret2Shell or CTFd **chosen
  explicitly**, plus that platform's URL and token), and solving settings
  (challenges per round, concurrency, categories and difficulty as **checkboxes**,
  order, include-solved, dry-run). Saving writes the values back into `.env`; secret
  boxes left empty keep the value already stored. Models are **grouped by
  provider** (DeepSeek first, then every custom provider) and each row carries a
  **USD budget** (`限额`): spending is accumulated per model spec in
  `config/model_quotas.json`, and a spec that hits its limit is skipped by the
  CLI and refused by the panel before a run starts. `0` or empty means
  unlimited. Use `全选` / `清空` to toggle a whole provider at once.

The header shows the **DeepSeek balance** straight from `GET https://api.deepseek.com/user/balance` (the same number as the official site), refreshed once a minute. Restarting the dashboard clears the solver list: only traces started after the current process begins are listed, and a second instance cannot bind the port.
* **解题观察** — start/stop the run, and pick one solver at a time from a list
  of the concurrently running challenges to watch its `💭` reasoning, tool calls
  and results, with a hint box for that challenge. Each list entry and the pane
  header show the challenge's **category, points and difficulty**; drag the
  vertical bar between the list and the log to resize the sidebar (double-click
  it to reset, the width is remembered per browser). The **并发数** box next to the
  start/stop buttons can be changed while a round is running: the value is
  written to `logs/runtime.json`, the runner re-reads it every 2 s and adjusts
  its semaphore in place (lowering the limit lets already-running solvers finish,
  it never kills them).

The right-hand **challenge board** shows every challenge of the current batch as a small
square, grouped by direction (web / pwn / misc / re / crypto): green = solved on the
platform, blue ring = a solver is working on it right now, hover for the full name,
points and difficulty. With **challenges per round = 0** (coordinator mode) the board
switches to *every* challenge on the platform instead of only the pulled batch.

Hints submitted in the browser are appended to `logs/hints/<challenge>.jsonl`,
which the running solver watches, so they reach the model exactly like terminal
hints. `--port 8100` changes the port.

The solver list only shows runs from **this** dashboard session: traces touched
before it started are ignored (restarting gives a clean list), a finished run
disappears on its own unless “显示已结束” is ticked, and each entry carries a
`· HH:MM` start time so repeated runs of the same challenge stay distinguishable.
Starting a run requires the chosen platform's credential — the panel
refuses `auto` on purpose, since guessing between platforms is how a DASCTF run
can end up pulling MoeCTF challenges.

#### Custom model providers

DeepSeek, Bedrock, Azure and Google are built in. Any other OpenAI-compatible
endpoint (OpenRouter, Moonshot, SiliconFlow, a local vLLM/Ollama gateway) can be
added on the 配置 page: enter a name, the `Base URL` (up to `/v1`) and the API
key, then press **拉取模型** — the panel calls `GET {base_url}/models` and adds
every returned id to the model picker as `provider/model-id`.

Providers live in `config/providers.json` (gitignored, holds API keys):

```json
{"providers": [{"name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-or-...",
                "models": ["qwen/qwen3-235b"]}],
 "extra_models": ["openrouter/qwen/qwen3-235b"]}
```

Selections then work exactly like built-ins, e.g. `--models
openrouter/qwen/qwen3-235b` or `DEFAULT_MODELS=openrouter/qwen/qwen3-235b`.
Model ids may contain slashes — only the first `/` separates provider from
model, and only `deepseek/...` consumes a trailing effort suffix
(`/low`, `/medium`, `/high`, `/max`).

The adapter lists challenges, downloads attachments into
`challenges/<slug>/distfiles/`, writes `metadata.yml`, and submits flags
through the same `submit_flag` solver tool. The platform checks submissions
asynchronously, so the client polls the verdict and respects the
10-submissions-per-5-minutes limit.

`INSTRUCTIONS.md` (edit freely, no code change needed) is injected into every
solver's system prompt as authoritative platform rules: flag format,
submission rules, forbidden placeholders, rate limits and sandbox paths.

### DASCTF / 羊城杯

DASCTF exposes an "AI Agent API" for automated play. The credential comes from
the player console's **平台接入凭证** panel: `SERVER HOST` + `ACCESSKEY`
(`ak_live_...`). It only authorises the competition API — not an LLM gateway.

```env
PLATFORM=dasctf
DASCTF_URL=https://pro.dasctf.com
DASCTF_ACCESS_KEY=ak_live_...
```

```bash
# Pull one challenge, solve it, submit the flag, stop
uv run ctf-solve --platform dasctf --round 1 --max-challenges 1 -v

# Pull every open exercise (no round): same as --round 5 here
uv run ctf-solve --platform dasctf --round 5 -v

# Read-only listing / download helpers
uv run python scripts/list_dasctf.py          # score, difficulty, solved, attachments, endpoints
uv run python scripts/pull_dasctf.py          # download every attachment into challenges/

# Manual mode: one challenge at a time (starts the remote env if needed)
uv run ctf-solve --platform dasctf --challenge challenges/pwn --max-challenges 1 -v
```

Rules handled by the adapter:

- endpoints: `GET /slab-match/api/v1/agent/ctf/exercise-list` and
  `.../ctf/exercise?exerciseId=...`, `POST .../answer-panel/answer`,
  `POST .../ctf/build-exercise-env` (start a target env, then poll the detail
  until `endpoints` is populated);
- the deployed API only accepts a **double-encoded** JSON body (a JSON string
  containing the object) — the client hides that;
- flags are submitted as the **content inside `{}`** (the platform adds
  `DASCTF`/`flag` itself); a wrong answer returns `40001 … 当前还有49次提交机会`
  and the remaining quota is surfaced in the tool result;
- attachments (single object, or `attachment.files[]`) are downloaded from the
  returned `url`, and links embedded in the description are fetched too;
- `connection_info` is rendered from `endpoints` (`exposeIps`, `portMappings`,
  `users`, proxy ports, expiry) so the solver knows where to connect;
- after a correct submission the client calls `recover-exercise-env` to release
  the remote environment.

There are 50 submissions per contestant per stage; the client spaces
submissions (`MIN_SUBMIT_INTERVAL_S = 3`) and retries 429/5xx responses.

### CTF² Agent Arena

[CTF²](https://ctf2.dasctf.com) (DASCTF's agent-arena) gives every agent its
own PAT. Copy `CTF2_AGENT_TOKEN` from the agent's **connect** tab — the same
page also shows the MCP endpoint and the Codex/Claude config snippets.

```env
PLATFORM=ctf2
CTF2_URL=https://ctf2.dasctf.com
CTF2_AGENT_TOKEN=...        # from the connect page
CTF2_GROUND=                # optional practice ground id/slug; empty = all
```

```bash
# Read-only: agent identity, quotas, every practice challenge
uv run python scripts/list_ctf2.py

# Solve one challenge, submit, stop
uv run ctf-solve --platform ctf2 --round 1 --max-challenges 1 -v

# Manual mode on a pulled challenge
uv run ctf-solve --platform ctf2 --challenge challenges/my-task -v
```

How the adapter maps onto the platform:

- REST base `https://ctf2.dasctf.com/api/open/v1/user`, auth
  `Authorization: Bearer <token>`; every response is `{"data": ..., "success": true}`;
- `GET /practice/` → grounds, `GET /practice/{id}/challenges/` → challenges
  (`category`, `difficulty`, `points`, `is_solved`) filtered by
  `CHALLENGE_CATEGORIES` / `CHALLENGE_DIFFICULTY`;
- attachments come from `files[].id` → `GET .../files/{fileId}/download/`
  (a 5-minute signed URL) and are stored in `challenges/<name>/distfiles/`;
- `has_container` challenges get their target via
  `POST .../environment/start/` then polling `GET .../environment/` until
  `access_ready`, and `connection_info` is rendered from `access_url` /
  `access_urls` (`nc_ssl`, remaining seconds);
- `POST .../submit/` always sends `{"flag": <full flag>, "confirmation": true}`
  — CTF² flags are submitted **as-is** (no `{}` stripping), and
  `data.accepted` / `data.is_solved` drive the correct/incorrect verdict, with
  `attempts_left` surfaced in the tool result;
- rate limits (120 reads / 30 writes per minute, one environment by default)
  are respected: the client caches list/detail calls, spaces submissions by
  3 s, and retries 429/5xx with `Retry-After`.

### CTF+ (geek2026.play.ctfplus.cn)

CTF+ is not CTFd: its `/api/v1/*` routes return 404. It authenticates with the
**`SessionStore` cookie** (the same value you can read from DevTools → Application
→ Cookies), and every call is a JSON `POST`:

```dotenv
PLATFORM=ctfplus
CTFPLUS_URL=https://geek2026.play.ctfplus.cn
CTFPLUS_TOKEN=<SessionStore cookie value>
```

```bash
# read-only list (name/category/points/difficulty/solved)
uv run python scripts/list_ctfplus.py
uv run python scripts/list_ctfplus.py --categories web,pwn --difficulty 简单

# one round: pull, solve, submit (flags go in as-is)
uv run ctf-solve --platform ctfplus --round 1 --max-challenges 1 -v

# manual mode on a pulled challenge
uv run ctf-solve --platform ctfplus --challenge challenges/my-task -v
```

- `POST /api/challenge/getChallengeList` (`{page, page_size}`) → challenges with
  `challenge_id`, `challenge_name`, `score`, `difficulty` (0–5), `is_solved`,
  `tags[{tag_name,is_hidden}]`, `runtimeMode`;
- `POST /api/challenge/getChallengeDetailInfo` needs `{"id": "<id as string>"}`
  and returns rich-text `short_des` (editor.js JSON), `attachments`
  (`attachment_path`), `address` and `sum_solves`;
- attachments: `GET /api/file/<attachment_path>`;
- `POST /api/challenge/submitFlag` (`{challenge_id, flag}`): `code 200` →
  `CORRECT`, `code 402` (`你的队伍已解决该题目`) → `PRACTICE`, anything else →
  `INCORRECT`;
- **practice mode** (`--include-solved`): a challenge your team already solved
  cannot be re-submitted, so its flag could never be verified. The adapter
  returns `PRACTICE` (never "correct"), the solver keeps working, and the run
  only finishes when the model reports the flag it derived — it is marked
  *unverified* rather than silently confirmed;
- `runtimeMode != "none"` marks a challenge as needing a target (it takes the
  container slot in the scheduler). Targets are started automatically: when the
  detail has no `address`, the client calls
  `POST /api/challenge/startChallenge {"id": "<id>"}` and writes the returned
  `address` (`host port` or `https://…`) into `connection_info`; the slot is
  released with `POST /api/challenge/stopChallenge` when the challenge ends.

## Run safeguards (ported from the reference agent)

The Go reference agent (`refs/agent`) had a few hard-won behaviours that this
Python version now mirrors:

- **Platform request pacing** — every platform call (and every retry) waits for
  `PLATFORM_REQUEST_INTERVAL` (default `0.8s`) since the previous request. The
  timestamp lives in `logs/.platform-request.state` behind an OS file lock, so
  two runners sharing this checkout also pace each other.
- **Submission de-duplication** — a flag is reserved in SQLite
  (`logs/submissions.sqlite`) *before* it is sent, keyed by
  `(platform+token scope, challenge, normalised flag)`. The same flag is never
  sent twice, even across restarts; the stored verdict is replayed instead.
- **Permanent pauses** — a `40409` on the answer endpoint means the challenge is
  out of attempts, so it is parked in `logs/pauses.json` forever and skipped by
  later rounds. A `40409` on `build-exercise-env` means "target capacity full"
  and does **not** pause anything.
- **Target-env reconciliation** — environments we start are recorded in
  `logs/target-envs.json`; each round closes leftovers (30 s timeout each)
  before dispatching, so a crashed run no longer blocks the quota.
- **Two worker pools** — attachment-only challenges and target challenges queue
  separately (`MAX_ATTACHMENT_WORKERS`, `MAX_TARGET_WORKERS`) under the global
  `MAX_CONCURRENT_CHALLENGES`; a slow target build cannot starve quick work.
- **Target slot is claimed before the pull** — starting a container challenge
  *is* the pull, so the coordinator acquires the target semaphore first and
  only then pulls. Container-ness comes from the platform's challenge list
  (`has_container`), not from the local `metadata.yml` category, so a CTF+
  docker challenge filed under `crypto` still counts against the quota.
- **Longer command budget** — `bash` defaults to 120 s (clamped to 1–3600 s),
  matching the reference agent's `run_command` limits.
- **Target heartbeat** — every `ENV_HEARTBEAT_S` (default 300 s) the runner
  renews the instances of the challenges it is currently solving
  (`PATCH .../instance` on Ret2Shell, `/challenge/delayChallenge` on CTF+,
  `/environment/extend/` on CTF²), so a long solve does not lose its container
  halfway. If a platform/target has no renewal endpoint the heartbeat stays
  quiet.
- **Dead-target fail-fast** — before each `bash` the solver probes the
  `host:port` it was given (once every 30 s). If nothing answers it returns
  `TARGET DOWN …` to the model and pings the coordinator instead of letting the
  model scan `host.docker.internal` for ten minutes.

## Coordinator Backends

```bash
# Claude SDK coordinator (default when Claude credentials are configured)
uv run ctf-solve --coordinator claude ...

# Codex coordinator (GPT-5.4 via JSON-RPC)
uv run ctf-solve --coordinator codex ...

# DeepSeek coordinator (Pydantic AI, needs only DEEPSEEK_API_KEY)
uv run ctf-solve --coordinator deepseek ...
```

## DeepSeek

DeepSeek runs through the Pydantic AI solver path, so no CLI login is required —
just the API key:

```env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEFAULT_MODELS=deepseek/deepseek-flash
```

```bash
# DeepSeek solvers with the DeepSeek coordinator
uv run ctf-solve --models deepseek/deepseek-flash --coordinator deepseek ...

# Stronger reasoning model / cheaper low-effort variant
uv run ctf-solve --models deepseek/deepseek-v4-pro --models deepseek/deepseek-flash/low ...
```

Model specs are `provider/model/effort`. DeepSeek effort maps `low`→low,
`medium`/`high`→high, `max`→max. `deepseek-flash` supports images and a 1M
context window; `deepseek-v4-pro` is text-only and stronger. When every
configured model is a `deepseek/*` spec and `DEEPSEEK_API_KEY` is set, the
coordinator backend defaults to `deepseek` automatically.

## Solver Models

Default model lineup (override with `DEFAULT_MODELS` in `.env`, comma separated,
or with `--models`):

| Model | Provider | Notes |
|-------|----------|-------|
| Claude Opus 4.6 (medium) | Claude SDK | Balanced speed/quality |
| Claude Opus 4.6 (max) | Claude SDK | Deep reasoning |
| GPT-5.4 | Codex | Best overall solver |
| GPT-5.4-mini | Codex | Fast, good for easy challenges |
| GPT-5.3-codex | Codex | Reasoning model (xhigh effort) |

## Sandbox Tooling

Each solver gets an isolated Docker container pre-loaded with CTF tools:

| Category | Tools |
|----------|-------|
| **Binary** | radare2, GDB, objdump, binwalk, strings, readelf |
| **Pwn** | pwntools, ROPgadget, angr, unicorn, capstone |
| **Crypto** | SageMath, RsaCtfTool, z3, gmpy2, pycryptodome, cado-nfs |
| **Forensics** | volatility3, Sleuthkit (mmls/fls/icat), foremost, exiftool |
| **Stego** | steghide, stegseek, zsteg, ImageMagick, tesseract OCR |
| **Web** | curl, nmap, Python requests, flask |
| **Misc** | ffmpeg, sox, Pillow, numpy, scipy, PyTorch, podman |

## Features

- **Multi-model racing** — multiple AI models attack each challenge simultaneously
- **Auto-spawn** — new challenges detected and attacked automatically
- **Coordinator LLM** — reads solver traces, crafts targeted technical guidance
- **Cross-solver insights** — findings shared between models via message bus
- **Docker sandboxes** — isolated containers with full CTF tooling
- **Operator messaging** — send hints to running solvers mid-competition
- **Manual challenge picking** — click the squares in the challenge overview (or pass `--pick NAME`, repeatable) to run exactly those challenges; picking bypasses the sampler and the cooldown
- **Blitz (fast attack)** — `--blitz` sweeps the pool easy first with a short per-challenge budget instead of letting a few hard targets stall the round
- **Dead-target fast abort** — a challenge whose service stopped answering is dropped in seconds (`target down`), not after the 10-minute timeout
- **Per-challenge cost** — the round summary, the snapshot and the dashboard resume hint show what each challenge cost
- **Fresh evaluation mode** — `--fresh` hides cross-round memory and wipes local challenge dirs, so the model has to solve it from the attachments
- **Trace masking** — flags and credentials are masked in `logs/trace-*.jsonl` by default (`TRACE_MASK=0` keeps them for writeups)
- **Skills library** — playbooks live in `skills/<direction>/*.md`; the prompt only carries a one-line index and the solver pulls the full text with `use_skill("pwn/format-string")` when it needs it (`SKILLS_ENABLED=0` disables it)

## Configuration

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
CTFD_URL=https://ctf.example.com
CTFD_TOKEN=ctfd_your_token
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=sk-...
DEFAULT_MODELS=deepseek/deepseek-flash
```

All settings can also be passed as environment variables or CLI flags.

## Requirements

- Python 3.14+
- Docker
- API keys for at least one provider (Anthropic, OpenAI, Google, or DeepSeek)
- `codex` CLI (for Codex solver/coordinator)
- `claude` CLI (bundled with claude-agent-sdk)

## Acknowledgements

- [es3n1n/Eruditus](https://github.com/es3n1n/Eruditus) — CTFd interaction and HTML helpers in `pull_challenges.py`
