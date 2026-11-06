# REVERSE 方向经验清单

## 静态
- `file`、`strings -n 8`（先找 flag 格式、错误提示、算法名如 AES/RSA/base64）。
- `rabin2 -I`（radare2）、`objdump -d`、`ghidra`（`pyghidra` 可用脚本化）。
- 先找 `main`/入口：`rabin2 -e`，Go 程序看 `runtime.main`，Java 用 `cfr` 反编译。

## 动态
- `ltrace`/`strace` 看库调用与文件访问。
- `gdb` 断在 `strcmp`/`memcmp`/`puts`，对比输入与期望。
- 反调试：`ptrace(PTRACE_TRACEME)`、`/proc/self/status` 检查，用 `LD_PRELOAD` 或 patch 跳过。

## 常见套路
1. 逐字节比较：爆破脚本按字符试（时间差或返回值）。
2. 自写加密/VM：先反汇编成伪代码，再逐指令翻译成 Python，用给定输入验证。
3. 花指令/混淆：`capstone` 逐条反汇编，跳过 `junk` 字节。
4. PyInstaller/pyc：`pyinstxtractor` 解包，`uncompyle6`/`decompyle3` 或 `pycdc`。
5. Android：`jadx` / `apktool`，so 用 `ghidra`。

## 提交前
- 用原程序验证：输入 flag 得到 "correct"，把这条输出作为 `evidence`。
