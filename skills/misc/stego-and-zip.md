---
name: misc/stego-and-zip
description: 隐写与压缩包：LSB、附加数据、伪加密、已知明文攻击
when_to_use: 给了图片/音频/zip，strings 没线索，binwalk 有隐藏段
categories: [misc]
keywords: [stego, lsb, zip, 伪加密, known plaintext, 隐写, 压缩包]
---
## 图片

```bash
file a.png; exiftool a.png; binwalk -e a.png      # 附加 zip/png
zsteg -a a.png                                     # LSB / 位平面
pngcheck -v a.png                                  # CRC 错误 / 尺寸被改
foremost -i a.png -o out                           # carver
```
- 高度被改：用 `pngcheck` 报错反推真实高度，或爆破 4 字节 CRC。
- `steghide extract -sf a.jpg`（密码常为空 / 题目名 / 123456）。
- 二维码：`zbarimg a.png`；反色/透视用 `python cv2` 处理后再解。

## 音频

```bash
sox a.wav -n spectrogram -o spec.png     # 频谱图
```
摩斯：`-`/`.` 的节奏可以用 python 按包络切分；DTMF 用 `multimon-ng`。

## 压缩包

```bash
zipinfo -v a.zip | grep -i encrypt          # 伪加密（bit 0 被置位）
zip2john a.zip > h; john h --wordlist=rockyou.txt
```
- **伪加密**：把 `PK\x01\x02` 后面的通用标志位从 `0x09` 改回 `0x00`。
- **已知明文**：`bkcrack -C a.zip -c plain.txt -p plain.txt -o 0`（需 ≥12 字节已知明文且非 deflate 存储）。
- **CRC 爆破**：小文件（1–3 字节）直接暴力内容匹配 CRC。
- 分卷/损坏：`7z x` 或 `zip -FF a.zip --out fixed.zip`。

## 通用

先 `strings -n 5` + `binwalk`，再看 `xxd | tail` 是否有第二段文件；`7z l` 能列出嵌套压缩包。
