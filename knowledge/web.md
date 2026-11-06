# WEB 方向经验清单

## 先侦察
- `curl -i` 看响应头（Server、X-Powered-By、Set-Cookie），`robots.txt`、`/sitemap.xml`、`.git/HEAD`、`.env`、`/backup.zip`。
- 目录爆破优先小字典：`ffuf -u http://T/FUZZ -w /tools.txt`，先看 200/301/403。
- JS 里找接口：`grep -oE '"/api/[a-zA-Z0-9_/-]+"'`；前端源码常含隐藏路由与硬编码 key。

## 常见漏洞的顺序
1. 注入：SQL（`'`、`"`、`1 and 1=1`）、命令（`;` `|` `$()`）、模板（`{{7*7}}`、`${7*7}`）。
2. 文件类：LFI（`../../etc/passwd`、php://filter）、上传（后缀/内容/MIME/解析）、zip slip。
3. 反序列化：PHP `O:`、Java `rO0`/`aced`、Python pickle、Node `_$$ND_FUNC$$_`。
4. 认证：JWT（`alg:none`、弱密钥爆破、kid 注入）、session 伪造、越权 IDOR。
5. SSRF：`http://127.0.0.1`、`file://`、云元数据 `169.254.169.254`、DNS rebinding。
6. 请求走私：CL.TE / TE.CL，先 `curl --http1.1` 手工构造，注意代理差异。

## 拿 flag 的位置
- 环境变量、`/flag`、`/flag.txt`、数据库表、`/proc/self/environ`、命令回显、盲注布尔/时间。
- RCE 后优先 `cat /flag*; env | grep -i flag`，再找 `/challenge`、`/app`。

## 提交前
- 记录能复现 flag 的最小请求（URL + 关键 header/body），作为 `evidence`。
