---
name: re/upx-garble-go
description: 魔改 UPX（节区名被改 + NRV2B 压缩体）+ garble 混淆的 Go 程序逆向
when_to_use: 节区名异常（1sp0/1sp1/1sp2 之类）、熵高、入口在最后一段、strings 里能看到 Go buildinfo 但函数名全被混淆
categories: [re]
keywords: [upx, garble, golang, go, pclntab, nrv2b, 壳, 节区]
stages: [侦察, 识别壳, 脱壳, 验 OEP, 找 Go 元数据, 定位 main, 还原校验, 产出 flag]
source: trace-RE6-deepseek-flash-20261107-131153.jsonl, trace-RE7-deepseek-flash-20261107-125326.jsonl
---

## 1. 侦察

- 动作：`file`、`strings -n 8 | head -50`、读节区表（`objdump -h`/`r2 -qc iS`）、算熵（`r2 -qc "p=e entropy; e entropy"` 或 `binwalk -E`）。
- 判据：能说出三件事——文件类型（PE/ELF）、入口在哪个段、是否是 Go（`runtime.morestack`、`go:buildid`、`gopclntab` 任一出现）。
- 失败分支：连文件类型都判不出 → 先看 magic 与大小，可能被整体加密，转「找解密 stub」。

## 2. 识别壳

- 动作：看节区名与入口反汇编前 40 条（`r2 -qc "pd 40 @ entry0"`）；找 `pushad`/`popad` 组合、找循环解压。
- 判据：能指出「解压循环用的是什么算法」，例如 NRV2B 的 `shr`+`rep movsb` 特征、LZMA 的 `5d 00 00` 属性字节。
- 失败分支：不是已知壳 → 记下循环的输入/输出指针，直接进第 3 步用模拟器硬解。

## 3. 脱壳

- 动作：先 `upx -d`（大概率因 magic 被改而失败）；改 `UPX!` magic 后再试；仍失败就写 unicorn 模拟脚本：
  - 映射镜像基址，从 EP 开始单步/块执行，hook 到「跳到壳外地址」即视为到 OEP；
  - 用 `mu.mem_read(base, size)` 把整段镜像 dump 成新文件。
- 判据：dump 出来的文件在 OEP 处能反汇编出**合理函数序言**（`push rbp; mov rbp,rsp` 或 Go 的 `CMPQ SP, 16(R14)`），且能看到原程序字符串。
- 失败分支：hook 里 RIP 不前进 / 返回地址取错 → 先修 hook（`mu.reg_write(UC_X86_REG_RIP, ...)` 要显式加指令长度）；dump 后仍乱码 → 回到第 2 步换算法（可能是自定义 + 二次加密）。

## 4. 验 OEP

- 动作：`objdump -d --start-address=<oep> --stop-address=<oep+0x80>`；`strings` 检查是否出现解题相关的提示串（如 `please input your flag`）。
- 判据：OEP 前后能连成完整函数，且字符串/导入表恢复。
- 失败分支：字符串还是空 → dump 的起点或大小错了，重算 `mem_read` 范围。

## 5. 找 Go 元数据

- 动作：搜 pclntab magic（Go 1.18+ 是 `f1 ff ff ff 00 00`，garble 版可能被改成别的 4 字节，可以按「后面紧跟 0x00 0x00 + 指针大小」特征扫）；定位 pcHeader → functab → funcname 表。
- 判据：能列出 `N 个函数名`，且 `main.main` 在里面。
- 失败分支：magic 找不到 → 在 `.rdata`/`.text` 尾部扫指针数组，用「相邻项递增 + 指向可执行段」判定 functab。

## 6. 定位 main

- 动作：从 functab 取 `main.main` 的入口地址，反汇编；若是 garble，字符串解密通常在 `main.main.func*` 里（`for` 循环 + 逐字节 xor/add）。
- 判据：能看到「读输入 → 逐字节比较/变换 → 输出对错」的控制流。
- 失败分支：main 里只有调度没有比较 → 顺着 `main.main.funcN` 逐个看，找带 `scanf/ReadFile` 的那个。

## 7. 还原校验

- 动作：把比较/变换逻辑翻译成 Python（常数表、xor key、置换表都可直接从反汇编抄），代入自己的输入验证「错误分支能触发」。
- 判据：用假输入能稳定命中「错误」分支，说明模型与程序一致。
- 失败分支：行为不一致 → 大概率漏了某个前置变换（大小写归一、去空格、长度补齐），回头读入口处的前处理。

## 8. 产出 flag

- 动作：按模型反解出正确输入，喂给程序确认「正确」分支被触发，再按平台格式提交。
- 判据：程序自己打印 success（不是你觉得对）。
- 失败分支：程序说对但平台判错 → 检查是否需要包 `DASCTF{}`、是否要交内层、是否有第二段校验。
