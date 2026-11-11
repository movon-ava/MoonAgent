---
name: re/pyc-and-dotnet
description: Python 字节码与 .NET 程序：反编译、恢复符号、绕过校验
when_to_use: 文件是 .pyc / .exe（.NET）/ 有 zip 打包的 python 程序
categories: [re]
keywords: [pyc, python, dotnet, .net, ilspy, dnspy, decompile]
---
## .pyc

```bash
file a.pyc                  # 看 magic，对应 Python 版本
python3 -c "import importlib.util;print(importlib.util.MAGIC_NUMBER.hex())"
```
版本对不上时用 `decompyle3` / `pycdc` / `uncompyle6`（3.8 以下）或 `pylingual`。
没有源码时先用 `dis` 看字节码：

```python
import dis, marshal, importlib.util, sys
with open('a.pyc','rb') as f:
    f.read(16); code = marshal.load(f)
dis.dis(code)
```
常见校验：字符串逐字符 XOR / 与固定数组比对 → 直接在字节码里找常量表。

## .NET

```bash
file app.exe                # "Mono/.Net assembly"
ilspycmd -o out app.exe     # 或 dnSpy / ILSpy GUI
```
反编译后找 `Main` 与 `Form1`，常见 `textBox1.Text == "..."` 校验。
被混淆（ConfuserEx）时：`de4dot app.exe` 先去混淆，再反编译。

## 动态验证

.NET 可在沙箱跑（`mono app.exe`），先 `strace`/`procmon` 看它读什么文件；
输入随机串看报错信息，常直接暴露比较逻辑。
