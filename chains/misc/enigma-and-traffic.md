---
name: misc/enigma-and-traffic
description: 老式密码机（Enigma/M-5 类）说明书 + 报文 + 流量包综合题：先分清"资料/密钥/密文/诱饵"，再按说明书建模解密，最后按题目要求的古怪格式提交。
when_to_use: 附件里同时有密码机说明书 PDF、若干条密文/报文清单、以及 pcap/pcapng；题目提到"日密钥""接线表""转子"或"截获的电报"
categories: [misc, crypto]
keywords: [enigma, 恩尼格玛, 密码机, 转子, 反射器, 接线, 日密钥, 报文, 电报, pcap, pcapng, 冰蝎, behinder, webshell, tshark, pdf, pdftotext]
stages: [清点附件, 还原文件名, PDF 取文本, 流量分流, 建模密码机, 攻报文密钥, 解密并转格式]
source: logs/trace-MISC1-*.jsonl（DASCTF 2026-11-07 Enigma）
---

## 1. 清点附件

- 动作：`ls -la distfiles/`；`file distfiles/*`；`unzip -l 附件.zip`。
- 判据：给每个附件贴标签——「说明书（怎么用）」「密钥资料（接线/轮位/日密钥）」「密文清单（要解的东西）」「流量包（可能是背景故事或诱饵）」。
- 失败分支：附件名带 `#U67d0#U65e5...` 这类 URL 编码 → 先还原，否则会以为文件缺失。

## 2. 还原文件名

- 动作：`python3 -c "import urllib.parse,os;[os.rename(f, urllib.parse.unquote(f)) for f in os.listdir('.') if '%' in f or '#U' in f]"`；编码形如 `#U5bc6` 时用 `re.sub(r'#U([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1),16)), name)`。
- 判据：名字变成可读中文（"M-5密码机使用说明书.pdf""某日捕获的报文信息.pdf"）。
- 失败分支：直接 `unzip -O cp936` 再试一次。

## 3. PDF 取文本

- 动作：先 `which pdftotext pdfinfo`；没有则 `pip install pypdf pdfminer.six`，用 `pypdf` 逐页 `extract_text()` 或 `pdfminer.six` 的 `extract_text` 落成 txt，再 `grep -n "接线\|转子\|反射器\|日密钥\|窗口"`。
- 判据：能抄出完整的接线表/轮位表/日密钥，并且知道密文清单里每条缺的是"报文密钥（起始窗口）"。
- 失败分支：扫描件无文字层 → `pdftoppm`/`pymupdf` 渲染成图后 OCR（`tesseract -l chi_sim`）。

## 4. 流量分流

- 动作：`tshark -r x.pcapng -q -z io,phs` 看协议分层；`tshark -r x.pcapng -Y "http" -T fields -e http.file_data`；`tshark --export-objects http,out` 导出 webshell 交互。
- 判据：能判断这段流量是"另一个场景的故事"（如冰蝎连 webshell 拿了一个 flag）还是"本题密文的载体"。若流量里出现的 flag 与题目要求的格式（如 `FLAGSTART ... FLAGEND`）不符，**先当作诱饵**。
- 失败分支：`http.file_data` 是 base64/gzip → 解码一层再看；连不上就别死磕，回到密码机主线。

## 5. 建模密码机

- 动作：按说明书实现转子（含非标准接线）、反射器、插线板；写成脚本后用已知明文自测。关键自检：`E(D(x)) == x`（自逆）以及"转子步进顺序/双步进"是否与手册一致。
- 判据：用说明书里给的示例（若有）能复现出同样密文。
- 失败分支：转子上电位置/环设置（Ringstellung）搞混 → 把"日密钥"拆成 转子顺序 / 环设置 / 初始窗口 三项分别对齐。

## 6. 攻报文密钥（本题的关键卡点）

- 动作：逐条试①所有报文共用同一窗口；②窗口由"日密钥 + 报文编号"派生；③机器在某设置下退化为恒等/弱置换（题目说"漏洞被修补了吗"往往暗示这里）；④已知明文攻击（明文含 `FLAGSTART`）。
- 判据：解出的明文可读率明显高于随机（中文/英文成句，可打印比例 > 0.9）。
- 失败分支：100 条全试不通 → 回到"维修指导规范"，找"补丁/改装/错装"那几页，它通常描述了一个可利用的实现缺陷。

## 7. 解密并转格式

- 动作：解出明文后严格按题目要求转换（如 `FLAGSTART xxxx FLAGEND` 且"转小写提交"），再 `submit_flag`，证据写清用了哪份密钥资料、哪条报文、哪个窗口。
- 判据：平台 CORRECT；或离线时输出"明文 + 转换规则 + 依据页码"。
- 失败分支：格式不对被拒 → 先核对大小写、空格、前后缀，再怀疑内容。
