---
name: crypto/rsa-classic
description: RSA 经典弱点：小 e、共模、共享素数、Fermat、Wiener
when_to_use: 给了 n/e/c，或给了两组以上的 (n, e, c)
categories: [crypto]
keywords: [rsa, small e, common modulus, fermat, wiener, 共模]
---
## 先分类

| 条件 | 攻击 |
| --- | --- |
| e=3 且 m^3 < n | 直接开三次方根（`gmpy2.iroot`） |
| 同一 m、两个 e、同一个 n | 共模：`a*e1 + b*e2 = 1` → `m = c1^a * c2^b mod n` |
| 多组 n 共享素数 | 两两 `gcd(n1, n2)` |
| p、q 相邻 | Fermat 分解：`a=ceil(sqrt(n))`，`b2=a^2-n` 开方 |
| e 很大、d 很小 | Wiener 连分数攻击 |
| 给了 dp/dq | `p = gcd(n, pow(2, e*dp, n)-2)` |

## 常用代码

```python
from Crypto.Util.number import long_to_bytes, inverse
from math import gcd, isqrt

# 共模
def common_modulus(n, e1, c1, e2, c2):
    g, a, b = ext_gcd(e1, e2)                # a*e1 + b*e2 = 1
    m = pow(c1, a, n) * pow(c2, b, n) % n
    return long_to_bytes(m)

# Fermat
def fermat(n):
    a = isqrt(n) + 1
    while True:
        b2 = a*a - n
        b = isqrt(b2)
        if b*b == b2: return a-b, a+b
        a += 1

# 共享素数
for i in range(len(ns)):
    for j in range(i+1, len(ns)):
        if (p := gcd(ns[i], ns[j])) > 1: print(p)
```

## 工具

`RsaCtfTool --publickey pub.pem --uncipher cipher.bin --attack all`，
sage 的 `small_roots`（Coppersmith）处理 `m` 部分已知 / `p` 高位已知。

## 坑

- `long_to_bytes` 前先确认 m 没被 padding 包裹（Crypto.Util.number 直接转，PKCS#1 v1.5 要剥 `\x00\x02...`）。
- e 与 phi 不互素时用 `gmpy2.iroot` 对每个根试。
