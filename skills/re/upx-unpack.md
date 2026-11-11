---
name: re/upx-unpack
description: 加壳/混淆：UPX、自解压 stub、魔改壳的手工脱壳路线
when_to_use: 二进制熵高、节区名异常、strings 里看到 UPX! 或解压循环
categories: [re]
keywords: [upx, unpack, packer, 壳, 脱壳, stub]
---
## 先探

```bash
file ./chal; strings -n 6 ./chal | head -20
readelf -S ./chal | head -30        # 节区名 UPX0/UPX1 = 标准 UPX
```

## 标准 UPX

```bash
upx -d ./chal -o unpacked
```
失败时（魔改 magic）：把 `UPX0`/`UPX1` 字符串改回去，或手工 patch magic `UPX!` → `upx!`。

## 自解压 stub（不是 UPX）

1. IDA/Ghidra 找入口附近的循环：`rep movsb` + 写 `0x401000` 之类，典型特征是两个常量相减得到 OEP。
2. 直接在调试器里跑到 OEP（`gdb ./chal`，`b *0x<oep>`），然后 `dump memory`。
3. 或写 unicorn 脚本模拟（沙箱里有 `unicorn`）：从入口单步到 `jmp` 目标，把内存落盘。

## 常见辅助

- `r2 -A ./chal` → `afl` 看函数；`/R push`、`/R pop reg` 找 OEP 跳转。
- `pyghidra` 打开后 `getFunctionAt` 找入口函数体，看是否在解密 `.text`。
- 脱壳后 dump 出的文件要修 ELF 头：`objcopy --set-section-flags` 或直接用 `lief`（沙箱已装）重建。
