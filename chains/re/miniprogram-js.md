---
name: re/miniprogram-js
description: 微信小程序 / 混淆 JavaScript 逆向：从工程结构找到真正的校验逻辑，去混淆后还原拼接与校验，产出 flag。
when_to_use: 附件是 .zip 且解开后出现 miniprogram/、app.json、project.config.json、*.wxml/*.js，或单个被 javascript-obfuscator 处理过的 solve.js
categories: [re, reverse, revrese, misc]
keywords: [小程序, miniprogram, wxml, wxss, app.json, project.config.json, solve.js, javascript-obfuscator, 混淆, 反混淆, obfuscator, node, jsbeautify, fragments.json, decoy]
stages: [侦察工程结构, 定位校验逻辑, 准备 node 运行时, 去混淆, 还原数据与拼接, 复算校验, 产出 flag]
source: logs/trace-RE1-*.jsonl（DASCTF 2026-11-07 天际线）
---

## 1. 侦察工程结构

- 动作：`ls -la distfiles/`；`unzip -l 附件.zip`；解压后 `find . -type f | sort`；`cat project.config.json app.json project.private.config.json`。
- 判据：能列出「页面目录 + 资源目录 + 入口 js」三块，并说出哪个文件像"参考实现"（常见名 `solve.js`、`check.js`、`verify.js`）——它通常是被混淆的那份。
- 失败分支：zip 里文件名是 `#U5bc6#U7801` 这类 URL 编码 → 先用 `python -c "import urllib.parse,sys;print(urllib.parse.unquote(sys.argv[1]))"` 还原再判断。

## 2. 定位校验逻辑

- 动作：`for f in miniprogram/pages/*/*.js; do echo ===$f; head -40 $f; done`；`cat miniprogram/app.js miniprogram/topic.js`；`cat assets/*.json`。
- 判据：找到"输入 flag → 分片/变换 → 与常量比对"的那条链，并记下：分片数量、每片长度、`order` 数组、`check` 前缀长度。
- 失败分支：页面 js 只做展示、真正逻辑在 `solve.js` 的 `requireSolution()` 里 → 直接 `sed -n '/function requireSolution/,$p' solve.prettify.js` 看它读了哪个文件（常见 `solution.json`、`observation.json`）。

## 3. 准备 node 运行时

- 动作：`which node nodejs npm deno bun`；没有就 `curl -sL https://nodejs.org/dist/v20.11.0/node-v20.11.0-linux-x64.tar.xz -o /tmp/node.tar.xz && tar xf /tmp/node.tar.xz -C /tmp && export PATH=/tmp/node-v20.11.0-linux-x64/bin:$PATH`。
- 判据：`node -v` 有输出。
- 失败分支：沙箱断网时改用 python 复刻逻辑（`js2py`/手工按源码翻译），不要卡在装环境上。

## 4. 去混淆

- 动作：`npx js-beautify solve.js > solve.pretty.js`（或 `python -m jsbeautifier`）；把字符串解码函数挂到全局再调用：
  `cp solve.js solve_dbg.js && echo 'globalThis.__dec = a0_0x3e97;' >> solve_dbg.js && node -e "require('./solve_dbg.js');console.log(globalThis.__dec(0x213))"`。
- 判据：能把关键常量（如 `0x213` → `flag{`）解出可读字符串，并能批量解码字符串表。
- 失败分支：解码函数名不固定 → 搜 `function a0_0x` 或 `atob(`/`fromCharCode(`，先 dump 字符串表再匹配。

## 5. 还原数据与拼接

- 动作：读 `assets/fragments.json` 的 `parts/order/partLen/check`；`xxd assets/layers.bin | head`；按代码把 parts 依 `order` 重排后拼接（`partLen * len(parts)` 常等于 flag 主体长度）。
- 判据：拼出的字符串字符集像 flag 主体（可打印、无重复乱码），且长度与代码里断言的长度一致。
- 失败分支：`assets/decoy.json` 之类同名文件多半是诱饵（内容看着像答案但校验不过）→ 以 `check` 字段指向的那份数据为准。

## 6. 复算校验

- 动作：按源码复算 `check`（常见 `sha256(ordered)` 取 hex 前 N 位，再用自定义 base 编码成 3 个字符）。
- 判据：算出的 check 与 json 里的 `check` 完全一致 → 拼接顺序正确。
- 失败分支：不一致先怀疑 order 语义（是"取出顺序"还是"填回位置"），两种都试一遍。

## 7. 产出 flag

- 动作：拼成平台要求的格式（如 `DASCTF{...}`）并 `submit_flag`，证据写清"parts→order→sha256 校验通过"。
- 判据：平台返回 CORRECT；若本地无平台，把拼接结果与校验过程一起写进结论。
- 失败分支：仍缺 `observation.json` 这类"真实运行时采集"数据 → 判断能否用静态资源重构（本题的 layers.bin + fragments 即可），否则说明这是无法离线复现的题，记录卡点而不是硬猜。
