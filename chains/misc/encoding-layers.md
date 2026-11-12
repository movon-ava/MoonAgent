---
name: misc/encoding-layers
description: 多层编码拼接（base64 → hex → rot13 / 反向 / 压缩）的层层剥皮
when_to_use: 附件是小文本或字符串，肉眼像 base64/十六进制，解一层后还是"像编码"的样子
categories: [misc]
keywords: [base64, hex, rot13, 编码, encoding, layers, 多层]
stages: [识别类型, 逐层解码, 校验可读性, 提取 flag]
source: challenges/layers, challenges/misc2
---

## 1. 识别类型

- 动作：`file`；`head -c 200 | xxd | head`；看字符集（`A-Za-z0-9+/=` 是 base64，`0-9a-f` 是 hex，字母轮转是 rot13/凯撒）。
- 判据：给出一句「第一层是 X」，并写出判定依据（字符集 + 长度是否 4 的倍数 + 是否有 `=` 填充）。
- 失败分支：二进制乱码 → 转 `binwalk`/`zsteg`（图片）/`7z l`（压缩包），别硬解。

## 2. 逐层解码

- 动作：写一个循环而不是一条条手敲：
  ```python
  import base64, binascii, codecs
  s = open("distfiles/misc1.txt","rb").read().strip()
  for step in range(10):
      for name, fn in (("b64", base64.b64decode), ("hex", binascii.unhexlify),
                       ("rot13", lambda b: codecs.encode(b.decode(), "rot13").encode())):
          try:
              out = fn(s)
          except Exception:
              continue
          if out and out != s:
              print(step, name, out[:80]); s = out; break
      else:
          break
  ```
- 判据：每层都能打印出「层号 + 方法 + 前 80 字节」，且下一层仍能被识别。
- 失败分支：某层解出乱码 → 可能顺序错了（比如先 rot13 再 base64），把候选方法全试一遍，用「可打印比例 > 0.9」挑。

## 3. 校验可读性

- 动作：每层解完算可打印比例；出现 `flag{`/`DASCTF{`/中文/英文句子即停。
- 判据：可打印比例 > 0.95 且出现有意义的词。
- 失败分支：全可打印但仍无意义 → 可能是「替换表」（`atoi`/键盘位移/A1Z26），看字符分布。

## 4. 提取 flag

- 动作：`grep -oE "[A-Za-z0-9_]+\\{[^}]+\\}"`；按平台格式确认是否需要内层内容。
- 判据：拿到的串与题目要求的格式一致。
- 失败分支：解出的是提示语而不是 flag → 说明还有一层或 flag 在另一文件里，回头 `ls -la distfiles/`。
