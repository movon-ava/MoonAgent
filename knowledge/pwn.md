# PWN 方向经验清单

## 拿到二进制先做什么
- `file`、`checksec --file=./chal`（PIE / NX / Canary / RELRO / Fortify）。
- `strings -n 6` 找提示与格式化串；`readelf -h/-s` 看入口与符号。
- 动态跑一次看交互：`nc host port` 或本地 `./chal`，记录菜单与输入格式。

## 常见题型与入口
1. 栈溢出：找 offset（`cyclic 200` + `gdb`/`pattern offset`），ROPgadget 找 `pop rdi; ret`、`leave; ret`、`syscall`。
2. 格式化字符串：`%p` 泄露、`%n` 写入；先定位参数序号（`AAAA.%p.%p...`）。
3. 堆：`malloc/free/edit` 菜单，看 UAF / double free / tcache poisoning（glibc 版本决定 safe-linking）。
4. kernel：`ioctl` 命令字、`copy_from/to_user` 长度校验；提权常用 `modprobe_path`、`core_pattern`、`commit_creds(prepare_kernel_cred(0))`。

## glibc/环境
- 先确认 libc 版本：`./libc.so.6` 或泄露地址低位；`one_gadget` 需要匹配版本。
- 需要 libc 时可以用 `patchelf --set-interpreter` + `--set-rpath`。

## 调试
- `gdb -q ./chal -ex 'b *main' -ex run`；pwntools `gdb.attach(p, 'b *0x...')`。
- 远程交互用 `pwn remote(host, port)`，注意 `recvuntil` 的提示符。

## 提交前
- 保留能打通并读到 flag 的 exp（`/challenge/workspace/exp.py`）与运行输出作为 `evidence`。
