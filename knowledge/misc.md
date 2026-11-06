# MISC / 取证方向经验清单

## 文件先过一遍
- `file`、`binwalk -e`（嵌套压缩/固件）、`7z l`、`exiftool`（元数据/注释）、`pngcheck -v`。
- 图片：`zsteg -a`（PNG LSB）、`steghide extract -sf`（需要口令，先试空/题名）、`stegseek`（爆破）。
- 音频：`ffmpeg -i` 看频谱，`sox` 看波形；摩斯/DTMF 用 `multimon-ng`。

## 常见载体
1. 流量：`tshark -r x.pcap -Y http`、`-z follow,tcp,ascii,0`；HTTP 对象导出 `--export-objects http,out`。
2. 内存：`vol -f dump.raw windows.pslist/pstree/cmdline/consoles/filescan`；Linux 用 `banners/pslist`。
3. 磁盘：`mmls`、`fls -r`、`icat`；未分配空间 `blkls | strings`。
4. 文档：docx/xlsx 解压看 `xml`，PDF `pdf-parser`/`qpdf --qdf`。

## 编码与隐写
- base 家族（16/32/58/64/85/91）、`xxd`、`zlib`、`gzip`、`bzip2`。
- 二维码/条码：`zbarimg`；异常图片转 PNG 后再看。
- 盲水印/最低位：写脚本按位提取，别只靠工具。

## 提交前
- 记录提取命令与输出片段（`zsteg` 的那一行、`vol` 的输出），作为 `evidence`。
