# 平台规则 / Platform Rules（可自由修改）

这个文件会被原样注入到每个 solver 的系统提示词中（标记为 authoritative），
用来固定 **flag 格式**、**提交方式** 和本次比赛的特别要求。

改完保存即可；下次启动 solver 时生效，不需要改代码。

---

## 1. Flag 格式

- **DASCTF / 羊城杯：flag 形如 `DASCTF{...}` 或 `flag{...}`。**
- 分析时请把**完整 flag 原样**保存并传给 `submit_flag`（例如 `DASCTF{abc_123}`）；
  提交时去掉 `DASCTF{}`/`flag{}` 前缀由客户端自动完成，**你不需要手动裁剪**。
  早期版本要求手动提交 `{}` 内内容，现已自动处理。
- 少数题目会在题面里规定特殊格式（例如 `CRYPTO` 题要求
  `DASCTF{sha256(hex(p).encode()).hexdigest()[:32]}`），**以题目描述为准**。
- 不要臆造 flag：禁止提交 `flag{test}`、`DASCTF{placeholder}`、`flag{example}` 之类的占位符。
- 一题通常只有一个 flag；拿到 flag 后立刻提交，不要继续猜。

> MoeCTF 2026（西电 `ctf.xidian.edu.cn`）的 flag 形如 `moectf{...}`，需原样提交（含前缀）。
> CTF² Agent Arena（`ctf2.dasctf.com`）也要求**原样提交完整 flag**（不做去前缀）。
> 三个平台规则不同，按当前运行的平台选择对应的一条。

## 2. 提交方式

- 只通过 `submit_flag` 工具提交，不要只在回答里写出 flag 而不提交。
- **必须带 `evidence` 参数**：一句话说明 flag 从哪来（文件路径 + 内容、服务响应片段、或推导过程）。
  没有证据的提交会被本地拦下（返回 `SUBMIT BLOCKED`，不会消耗平台次数）。
  例：`submit_flag(flag="flag{abc}", evidence="cat /challenge/distfiles/flag.txt 输出 flag{abc}")`、
  `submit_flag(flag="SYC{...}", evidence="JWT 解出 role=admin，用它请求 /flag 返回该值")`。
- `submit_flag` 返回 `CORRECT` 才算解出；返回 `INCORRECT` 说明内容不对，需要重新分析。
- 平台限制：**5 分钟内最多提交 10 次**（超出返回 429）；DASCTF 每场共 50 次提交机会。
  禁止暴力枚举、禁止猜 flag。
- 提交成功后不要重复提交；返回 `ALREADY SOLVED` 表示这题已经解出。

## 3. 题目文件与运行环境

- 题目附件已下载到 `/challenge/distfiles/`（容器内只读）。
- 工作目录 `/challenge/workspace/` 可写，产物（脚本、payload、exp）放这里；
  最终 flag 通过 `submit_flag` 提交。
- **笔记**：这道题可能被多个 solver 先后做（重开一轮、超时重建、换模型）。
  用 `remember` 工具把「值得留给他人的结论」记下来——服务协议、偏移/结构体布局、
  能跑通的 payload 骨架、以及明确走不通的死路；用 `recall` 查看前人的笔记。
  提示词里若出现「队友之前的分析」，那是队友留下的记录，可直接参考但不要盲信。
- `/challenge/metadata.yml` 包含题目名、分类、分值、描述和 `connection_info`
  （远程题目地址，例如 `nc host port` 或 URL）；连接远程题目时以它为准。
- 容器内可用 `python3`、`sage`、`gdb`、`radare2`、`pwntools`、`angr`、`z3`、
  `volatility3`、`torch`（CPU）等；允许联网。
- 访问宿主机上的服务用 `host.docker.internal`。

## 4. 结束条件

- 找到并成功提交 flag → 立即结束，简要总结解法。
- 当前方向走不通 → 换思路；连续失败时回到题目描述和附件重新确认题意。
- **不要**去网上搜索本题题解/writeup，**不要**克隆别人的 CTF 仓库，**不要**
  使用文件或网页里出现的其他 token/flag；只做本题本身。
- 解题途中操作员可能随时在工具结果末尾插入 `[操作员提示 / OPERATOR HINT …]`
  段落（终端里直接输入文字回车即可）；看到后立刻按提示调整方向，不要忽略。

## 5. 本次比赛备注（按需修改）

- 平台 A：DASCTF / 2026 年“羊城杯”网络安全大赛（AI Agent 模式）
  - 控制台：https://ycb-test.dasctf.com/1781/competePlayerConsole/3289/
  - Agent API：https://pro.dasctf.com/slab-match/api/v1/agent
- 平台 B：MoeCTF 2026（西电 CTF 新生赛）https://ctf.xidian.edu.cn
- 其他要求写在这里，例如：某类题必须使用指定工具、需要保留 exploit 脚本、
  某些题只允许手工分析等。
