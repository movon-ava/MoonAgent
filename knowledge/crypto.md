# CRYPTO 方向经验清单

## 先定性
- 看题面给的参数：`n,e,c`（RSA）、椭圆曲线、大整数、密文文件、`hint`。
- 用 `python3 -c "import Crypto, gmpy2, sympy, z3"` 确认工具（镜像里都有）。

## RSA 常见攻击顺序
1. 小 `e`（3/5/17）：`c` 开 `e` 次方；`c + k*n` 逐个开方。
2. 共模/同 `n` 多密文：`gcd(c1^e1 - c2^e2, n)`；广播攻击用 CRT。
3. 已知 `p,q` 关系：`p+q`、`p^q`、`p-q` 可解二次方程。
4. `d` 小：Wiener（连分数）。
5. 模数分解：`factordb`、`yafu`、`Fermat`（p,q 接近）、`Pollard rho`。
6. Padding：Coppersmith（`small_roots`）、Bleichenbacher（需要 oracle）。

## 其它
- 分组密码：先看模式（ECB 块重复、CBC 字节翻转、CTR 重用 nonce 异或）。
- 伪随机：LCG 解方程、MT19937 状态恢复（624 个输出）。
- 格：`fpylll`/`sage`；先构造格再看维度是否可约。

## 提交前
- 把推导脚本放在 `/challenge/workspace/solve.py`，输出 `p`/`m`/flag 的那行作为 `evidence`。
