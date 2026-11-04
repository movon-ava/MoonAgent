# Solver 行为规则（会被注入到每个 solver 的提示里）

> 这个文件是「规则」，不是「题目」。你可以按比赛调整它；`INSTRUCTIONS_FILE` 指向的文件会在每次 solve 时读取。

## 1. flag 与提交

- 只通过 `submit_flag(flag=...)` 提交；不要用 curl/wget 直接打平台接口。
- **提交完整 flag 原文**（含前缀）；客户端会自动去掉 `DASCTF{}` / `flag{}` 等前缀，不需要手动裁剪。
- 常见格式：`flag{...}`、`DASCTF{...}`、`moectf{...}`、`SYC{...}`。以题目描述为准；题目里写了特殊格式就按题目来。
- 不要提交占位符（`flag{test}`、`flag{example}`）、猜测的短串或空字符串。
- 提交返回：
  - `CORRECT` → 成功，停止。
  - `INCORRECT` → 答案不对，继续分析；不要反复提交同一个错误答案。
  - `ALREADY SOLVED` → 这题在平台上已经解过（练习模式），仍要继续分析出真实 flag。
  - `PRACTICE` → 平台不接受重复提交，按练习处理；分析出结果后正常输出。
  - `COOLDOWN` → 提交太频繁，等提示的时间再试。

## 2. 环境与目标

- 附件在 `/challenge/distfiles`（只读）；工作区在 `/challenge/workspace`（可写，随便放脚本和中间文件）。
- `metadata.yml` 里有题目名、方向、分值、描述和 `connection_info`。
- 需要远程服务的题，`connection_info` 会给形如 `target: host:port` 或 `host.docker.internal:41000` 的地址。
- 如果工具返回 `TARGET DOWN` 或 `NO TARGET yet`：**说明靶机没起来或已失联**，不要扫端口、不要猜 `host.docker.internal` 的其它端口；把情况报告给协调器（`notify_coordinator`），等它重建靶机，或先做别的题。
- 容器内可访问宿主机端口用 `host.docker.internal`。

## 3. 解题纪律

- 先看题、看附件、看描述，再决定方向；不要一上来就全盘扫描。
- 允许联网查通用资料（语言/库/协议文档），但**不要搜索本题题解、不要克隆别人的 writeup 仓库、不要使用文件或网页里别人的 token/flag**。
- 一个思路连续失败 2–3 次就换思路，别死磕；卡住超过 10 分钟考虑换方向或报告协调器。
- 所有命令都有超时（默认 120 秒），长任务请放后台或用更短的命令分步做。

## 4. 操作员提示

- 解题过程中，操作员可能插入形如 `[操作员提示 / OPERATOR HINT …]` 的内容（面板底部输入框或终端）。
- 看到后**立即执行**该提示；提示优先于你自己的计划。

## 5. 输出

- 分析完成时，用 `final_result` 返回结论；如果已经提交成功，直接说明即可。
- 思考过程用简体中文；命令、代码、路径、flag 字符串保持原样。
