"""Dashboard markup: one self-contained HTML page (CSS + JS inline).

Kept apart from ``webui.py`` so the server logic and the page layout can be
read and edited independently."""

from __future__ import annotations

HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>CTF Agent 控制台</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1c2029;--line:#262b36;--fg:#d7dce5;--dim:#7d8798;
--cyan:#4cc2ff;--green:#5ddb8f;--mag:#c792ea;--yellow:#ffd479;--red:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 Consolas,"Cascadia Mono","Microsoft YaHei",monospace}
header{display:flex;gap:14px;align-items:center;padding:9px 16px;border-bottom:1px solid var(--line);background:#12151b;position:sticky;top:0;z-index:9}
header h1{font-size:15px;margin:0;font-weight:600}
nav{display:flex;gap:4px}
nav button{background:transparent;color:var(--dim);border:1px solid transparent;border-radius:7px;padding:5px 12px;cursor:pointer;font:inherit}
nav button.on{background:#222836;color:var(--fg);border-color:#31384a}
.spacer{flex:1}
.chip{color:var(--dim);font-size:12px}
.chip b{font-weight:600}
.chip .on{color:var(--green)}
.page{padding:14px;display:none}
.page.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;align-items:start;max-width:1400px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px}
.card h2{font-size:13px;margin:0 0 4px;display:flex;gap:8px;align-items:center}
.card .sub{color:var(--dim);font-size:11px;margin-bottom:10px}
#page-config .cards{max-width:1600px;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px}
#page-config .card{padding:16px 18px}
#page-config .card:first-child{grid-column:1/-1}
#page-config .card h2{font-size:14px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:8px}
#page-config .f{margin-bottom:9px}
#page-config .f label{font-size:12px;color:var(--dim);margin-bottom:4px}
#page-config .f input,#page-config .f select{height:32px;padding:0 9px;border-radius:7px;background:#0f1219;border:1px solid var(--line);color:var(--fg);font:inherit;font-size:13px;width:100%}
#page-config .f input:focus,#page-config .f select:focus{outline:none;border-color:#3d6fd4;box-shadow:0 0 0 2px rgba(61,111,212,.18)}
#page-config .chks{display:flex;flex-wrap:wrap;gap:6px}
#page-config .chks label{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:#12161f;cursor:pointer;font-size:12px}
#page-config .chks label:has(input:checked){border-color:#3d6fd4;background:#18203a;color:#cfe0ff}
#page-config .hint{font-size:11px;color:var(--dim);margin-top:3px}
#page-config .pbox{border:1px dashed var(--line);border-radius:9px;padding:10px 12px;margin-top:8px}
#page-config .pbox:empty{display:none}
.savebar{position:sticky;bottom:0;z-index:40;display:flex;gap:10px;align-items:center;max-width:1600px;margin:4px auto 0;padding:10px 4px;background:linear-gradient(180deg,rgba(11,13,18,0),var(--bg) 45%);border-top:1px solid var(--line)}
.cfg-tabs{display:flex;gap:6px;max-width:1600px;margin:2px auto 10px}
.cfg-tabs button{background:#12161f;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit;font-size:13px}
.cfg-tabs button.on{background:#1b2740;color:#cfe0ff;border-color:#3d6fd4}
#page-config .cards{grid-template-columns:1fr}
#page-config .card{display:none}
#page-config .card.on{display:block}
.savebar .msg{font-size:12px;color:var(--dim)}
.savebar button{padding:8px 16px}
.f{display:flex;flex-direction:column;gap:3px;margin-bottom:9px}
.f label{color:var(--dim);font-size:11px}
.f input,.f select{background:#0d1015;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:6px 8px;font:inherit;width:100%}
.f .hint{color:var(--dim);font-size:11px;margin-top:2px}
.models{border:1px solid var(--line);border-radius:6px;background:#0d1015;max-height:150px;overflow:auto;padding:6px 8px}
.models label{display:flex;gap:7px;align-items:center;padding:2px 0;color:var(--fg);font-size:12px;cursor:pointer}
.pgroup{margin:8px 0;padding:8px;border:1px solid var(--line);border-radius:10px;background:#11151d}
.phead{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px}
.phead .dim{color:var(--dim);font-size:12px}
.mrow{display:grid;grid-template-columns:18px minmax(0,1fr) auto 92px 78px;align-items:center;gap:8px;padding:5px 6px;border-radius:8px}
.mrow.on{background:#18203a}
.mrow .mname{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.mrow .mspent{color:var(--dim);font-size:12px;white-space:nowrap}
.mrow .mlimit{width:92px;padding:3px 6px;font-size:12px}
.mrow .mrem{color:var(--dim);font-size:12px;white-space:nowrap;text-align:right}
.mrow .mrem.out{color:var(--red)}
.mini{padding:2px 8px;font-size:11px;border-radius:6px;background:#1c2230;border:1px solid var(--line);color:var(--fg);cursor:pointer}
.prov{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;background:#141821}
.prov-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.prov-head .hint{font-size:11px}
.checks{display:flex;gap:16px;margin:2px 0 10px;color:var(--dim)}
.chks{display:flex;flex-wrap:wrap;gap:8px 16px;padding:5px 0;font-size:12.5px}
.chks label{display:flex;align-items:center;gap:5px;cursor:pointer;color:var(--fg)}
.chks input{accent-color:#3d6fd4;margin:0}
.checks label{display:flex;gap:6px;align-items:center;cursor:pointer}
.btns{display:flex;gap:8px;flex-wrap:wrap}
button{border:0;border-radius:6px;padding:7px 14px;cursor:pointer;font:inherit;color:#fff}
.primary{background:#1f6feb}.primary:hover{background:#2b7ff5}
.danger{background:#a33}.danger:hover{background:#c44}
.ghost{background:#2a2f3a}.ghost:hover{background:#343b49}
.msg{margin-top:10px;font-size:12px;white-space:pre-wrap;word-break:break-word;color:var(--dim)}
.msg.err{color:var(--red)} .msg.ok{color:var(--green)}
/* main page */
.main{display:flex;align-items:stretch;gap:0;padding:14px;height:calc(100vh - 52px)}
@media(max-width:900px){.main{grid-template-columns:1fr;height:auto}}
.rail{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:10px;overflow:auto;flex:0 0 var(--rail-w,330px);min-width:200px}
.splitter{flex:0 0 12px;display:flex;align-items:center;justify-content:center;cursor:col-resize}
.splitter i{width:3px;height:100%;background:var(--line);border-radius:2px;transition:background .15s}
.splitter:hover i{background:#3d6fd4}
.sitem .col{display:flex;flex-direction:column;gap:1px;min-width:0;flex:1}
.sitem .col .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rail h2{font-size:12px;margin:0;color:var(--dim);font-weight:600;letter-spacing:.05em}
.runbox{display:flex;gap:6px}
.runbox button{flex:1;padding:7px 8px}
.runstate{font-size:12px;color:var(--dim);white-space:pre-wrap;word-break:break-word}
.runstate .on{color:var(--green)}
.slist{display:flex;flex-direction:column;gap:4px}
.sitem{display:flex;gap:8px;align-items:center;padding:7px 9px;border:1px solid transparent;border-radius:8px;cursor:pointer;background:#141821}
.sitem:hover{background:#1a1f2a}
.sitem.on{border-color:#3d6fd4;background:#18203a}
.sitem.fin{opacity:.55}
.sitem .dot{width:8px;height:8px;border-radius:50%;background:var(--dim);flex:0 0 auto}
.sitem .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.sitem .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sitem .md{color:var(--dim);font-size:11px}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;min-height:320px;max-height:100%;overflow:hidden;flex:1 1 0;min-width:0}
.pane h3{margin:0;padding:10px 13px;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:8px;align-items:center}
.pane h3 .md{color:var(--dim);font-weight:400}
.phead-bar{display:flex;align-items:center;border-bottom:1px solid var(--line)}
.phead-bar h3{border-bottom:0;flex:1;min-width:0}
.phead-bar button{margin:0 11px;flex:0 0 auto}
.log{overflow:auto;padding:9px 13px;flex:1;font-size:12.5px}
.board{flex:0 0 288px;display:flex;flex-direction:column;border-left:1px solid var(--line);background:#0b0f16;min-height:0}
.bhead{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 11px;border-bottom:1px solid var(--line);font-size:12.5px;color:var(--dim);font-weight:600}
.board-body{overflow:auto;padding:9px 11px}
.bgroup{margin-bottom:12px}
.gtitle{display:flex;justify-content:space-between;font-size:11px;letter-spacing:.06em;color:var(--dim);margin:2px 0 6px;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:6px}
.sq{height:38px;border-radius:7px;border:1px solid #232b39;background:#141a24;color:#7c8798;font-size:10px;display:flex;align-items:center;justify-content:center;overflow:hidden;white-space:nowrap;padding:0 2px}
.sq.solved{background:#12351f;border-color:#2ea043;color:#8ff0b7;font-weight:600}
.sq.active{outline:2px solid #3d6fd4;outline-offset:1px}
.sq.pickable{cursor:pointer}
.sq.picked{outline:2px solid #f0a020;outline-offset:1px;background:#2b2213;border-color:#7a5a1c;color:#ffd58a}
.pickbar{display:flex;align-items:center;gap:6px;padding:8px 11px;border-top:1px solid var(--line);background:#0e131b;font-size:12px}
.pickbar[hidden]{display:none}
.pickbar span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dim)}
#tip{position:fixed;z-index:80;max-width:340px;padding:6px 9px;border-radius:7px;border:1px solid #2b3446;background:#1b2130;color:#e6edf3;font-size:12px;line-height:1.45;white-space:pre-wrap;pointer-events:none;opacity:0;transition:opacity .08s;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.ev{margin:2px 0;white-space:pre-wrap;word-break:break-word}
.think{color:var(--mag)} .tool{color:var(--cyan)} .result{color:var(--dim)}
.flag{color:var(--yellow);font-weight:700} .hintx{color:var(--green)}
.hints{display:flex;gap:6px;padding:9px 11px;border-top:1px solid var(--line)}
.hints input{flex:1;background:#0d1015;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:7px 10px;font:inherit}
.empty{color:var(--dim);padding:30px;text-align:center}
</style></head>
<body>
<header>
  <h1>CTF Agent 控制台</h1>
  <nav>
    <button id="tab-main" class="on" data-page="main">解题观察</button>
    <button id="tab-config" data-page="config">配置</button>
  </nav>
  <span class="spacer"></span>
  <span class="chip" id="chip-run">未运行</span>
  <span class="chip" id="chip-plat"></span>
  <span class="chip" id="chip-solvers">0 个 solver</span>
  <span class="chip" id="chip-bal" title="DeepSeek 官方余额"></span>
</header>

<div class="page on" id="page-main">
  <div class="main">
    <aside class="rail">
      <h2>运行控制</h2>
      <div class="runbox">
        <button class="primary" id="start">开始解题</button>
        <button class="danger" id="stop">停止</button>
      </div>
      <button class="ghost mini" id="resume-last" style="margin:6px 0">继续上次未完成的轮次</button>
      <div class="runstate" id="resume-hint"></div>
      <div class="runstate" id="runstate">状态：未运行</div>
      <div class="runstate" id="summary"></div>
      <div class="f"><label>并发数（运行中可改）</label>
        <div class="runbox"><input id="conc" type="number" min="1" value="1"><button id="conc-apply">应用</button></div>
      </div>
      <h2>并发中的题目</h2>
      <div class="slist" id="slist"><div class="empty">还没有 solver</div></div>
            <button class="ghost" id="toolist">查看题目清单</button>
    </aside>
    <div class="splitter" id="splitter" title="拖动调整宽度，双击恢复"><i></i></div>
    <section class="pane">
      <div class="phead-bar"><h3 id="pane-title">选择一个题目观察</h3>
        <button class="ghost mini" id="skip" disabled title="让这道题立刻停止，把并发位让给下一题">跳过此题</button></div>
      <div class="log" id="log"><div class="empty">点击左侧题目查看思考与操作</div></div>
      <div class="hints">
        <input id="hint-input" placeholder="给当前题目发提示，回车发送（选中题目后可输入）" disabled>
        <button id="hint-send">发送</button>
      </div>
    </section>
    <aside class="board">
      <div class="bhead"><span>题目总览</span><span class="hint" id="bscope"></span>
        <button class="ghost mini" id="pick-toggle" title="点方格选择要跑的题目">选择</button></div>
      <div class="board-body" id="board"><div class="empty">加载中…</div></div>
      <div class="pickbar" id="pickbar" hidden>
        <span id="pick-count">已选 0 道</span>
        <button class="mini" id="pick-clear">清空</button>
        <button class="mini" id="pick-run">开始所选</button>
      </div>
    </aside>
  </div>
</div>

<div class="page" id="page-config">
  <div class="cfg-tabs" id="cfg-tabs">
    <button class="on" data-cfg="model">模型配置</button>
    <button data-cfg="platform">平台配置</button>
    <button data-cfg="solve">解题配置</button>
  </div>
  <div class="cards">
    <section class="card on" data-cfg="model">
      <h2>模型配置</h2>
      <div class="sub">解题用的模型。可多选，多个模型会并发跑同一道题。DeepSeek 的「已用」按官网余额差计算（与官网一致）。</div>
      <div class="f" style="display:flex;gap:8px;align-items:center">
        <button class="mini" id="bal-reset" title="把当前官网余额当作“已用 0”，用于重新开始计量">已用额度清零</button>
        <span class="dim" id="bal-hint" style="font-size:12px"></span>
      </div>
      <div class="f"><label>已选模型</label><div class="models" id="models"></div></div>
      <div class="f"><label>添加模型（spec 格式：供应商/模型名）</label>
        <div style="display:flex;gap:6px">
          <input id="newmodel" placeholder="例如 openrouter/qwen/qwen3-235b">
          <button class="ghost" id="addmodel">添加</button>
        </div>
        <div class="hint" id="hint-newmodel"></div></div>

      <h2 style="margin-top:16px">供应商</h2>
      <div class="sub">DeepSeek 已内置。其他 OpenAI 兼容服务（OpenRouter、Moonshot、SiliconFlow、本地 vLLM 等）在这里添加，然后拉取模型。</div>
      <div id="providers"></div>
      <div class="f" style="margin-top:10px"><label>供应商名称</label>
        <input id="prov-name" placeholder="openrouter"></div>
      <div class="f"><label>Base URL（到 /v1 为止）</label>
        <input id="prov-url" placeholder="https://openrouter.ai/api/v1"></div>
      <div class="f"><label>API Key</label>
        <input id="prov-key" type="password" placeholder="sk-..."></div>
      <div class="btns">
        <button class="ghost" id="addprov">添加供应商</button>
        <button class="ghost" id="fetchprov">拉取模型</button>
      </div>
      <div class="msg" id="provmsg"></div>

      <div class="f" style="margin-top:14px"><label>DeepSeek API Key</label>
        <input id="deepseek_api_key" type="password" placeholder="">
        <div class="hint" id="hint-ds"></div></div>
      <div class="f"><label>DeepSeek Base URL</label><input id="deepseek_base_url"></div>
    </section>

    <section class="card" data-cfg="platform">
      <h2>平台配置</h2>
      <div class="sub">选择要打哪个平台。选定后只拉该平台的题目。</div>
      <div class="f"><label>平台</label>
        <select id="platform">
          <option value="dasctf">DASCTF / 羊城杯</option>
          <option value="ctf2">CTF² Agent Arena</option>
        <option value="ctfplus">CTF+ / 极客挑战赛</option>
          <option value="ret2shell">Ret2Shell / 西电 MoeCTF</option>
          <option value="ctfd">CTFd</option>
        </select></div>

      <div class="f"><label>允许同时开启的容器数（0 = 按平台配额）</label>
        <input id="max_environments" type="number" min="0" value="0" placeholder="例如 2">
        <div class="hint">平台每个账号能同时开几个靶机；容器题超过这个数会排队等待，不会去扫端口。</div></div>

      <div class="f"><label>Flag 格式（如 moectf{} / SYC{}）</label>
        <input id="flag_format" placeholder="moectf{}">
        <div class="hint">只作为提示写进 solver 的提示词，并按前缀做一次软校验（不匹配只记日志）。</div></div>
      <div class="f"><label>提交格式</label>
        <select id="flag_submit_mode">
          <option value="full">完整 flag（含前缀和花括号）</option>
          <option value="inner">仅花括号内内容</option>
        </select>
        <div class="hint">选「仅内容」时，客户端提交前会自动去掉 PREFIX{...} 外壳（DASCTF / 羊城杯常用）。</div></div>

      <div id="box-dasctf" class="pbox">
        <div class="f"><label>SERVER HOST</label><input id="dasctf_url" placeholder="https://pro.dasctf.com"></div>
        <div class="f"><label>ACCESSKEY</label><input id="dasctf_access_key" type="password">
          <div class="hint" id="hint-dasctf"></div></div>
      </div>

      <div id="box-ret2shell" class="pbox">
        <div class="f"><label>站点地址</label><input id="ret2shell_url" placeholder="https://ctf.xidian.edu.cn"></div>
        <div class="f"><label>登录 Token（localStorage.account.token）</label>
          <input id="ret2shell_token" type="password"><div class="hint" id="hint-r2s"></div></div>
        <div class="f"><label>比赛 ID（留空 = 当前比赛）</label><input id="ret2shell_game" placeholder="37"></div>
      </div>

      <div id="box-ctfplus" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctfplus_url" placeholder="https://geek2026.play.ctfplus.cn"></div>
        <div class="f"><label>SessionStore Cookie（CTFPLUS_TOKEN）</label>
          <input id="ctfplus_token" type="password"><div class="hint" id="hint-ctfplus"></div></div>
      </div>
      <div id="box-ctf2" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctf2_url" placeholder="https://ctf2.dasctf.com"></div>
        <div class="f"><label>Agent Token（CTF2_AGENT_TOKEN）</label>
          <input id="ctf2_token" type="password"><div class="hint" id="hint-ctf2"></div></div>
        <div class="f"><label>练习题场（ID / 名字，留空 = 全部）</label><input id="ctf2_ground" placeholder="b9bbb32f-… 或直接粘贴练习场页面 URL"></div>
      </div>

      <div id="box-ctfd" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctfd_url" placeholder="https://ctf.example.com"></div>
        <div class="f"><label>API Token</label><input id="ctfd_token" type="password">
          <div class="hint" id="hint-ctfd"></div></div>
      </div>
    </section>

    <section class="card" data-cfg="solve">
      <h2>解题配置</h2>
      <div class="sub">一轮解多少题、怎么挑题。</div>
      <div class="f"><label>本轮题数（0 = 不限，用协调器持续跑）</label>
        <input id="round_size" type="number" min="0" value="1"></div>
      <div class="f"><label>并发数（同时解几道）</label>
        <input id="max_concurrent" type="number" min="1" value="1">
        <div class="hint">只对“能同时跑”的题生效：Ret2Shell 平台同时只允许 1 个容器实例，容器题再多也只能一个一个来；附件题不受此限</div></div>
      <div class="f"><label>速攻（由易到难连续扫题）</label>
        <div class="checks" style="margin-bottom:6px"><label><input type="checkbox" id="blitz_mode"> 开启速攻：先做简单题，单题超时直接换下一道</label></div>
        <div class="hint">不按“本轮题数”截断，把候选池里的题按难度从易到难连续开打，避免被几道难题拖住进度</div></div>
      <div class="f"><label>单题超时（分钟，0 = 不限）</label>
        <input id="challenge_timeout_min" type="number" min="0" step="0.5" value="0"></div>
      <div class="f"><label>额外轮数（0 = 不重试；一题没解出来时再多跑几轮）</label>
        <input id="challenge_extra_rounds" type="number" min="0" step="1" value="0">
        <div class="hint">超时不会重试；“放弃/没做出”会带着新的上下文重新开一轮</div></div>
      <div class="f"><label>方向（不勾 = 不限）</label>
        <div class="chks" id="cat-box"></div></div>
      <div class="f"><label>难度（不勾 = 不限）</label>
        <div class="chks" id="diff-box"></div></div>
      <div class="f"><label>选题顺序</label>
        <select id="round_order">
          <option value="random">随机（难题加权）</option>
          <option value="hard">难度优先（难→易）</option>
          <option value="score">分数从低到高</option>
          <option value="name">按名称</option>
        </select></div>
      <div class="f"><label>只做名称包含（逗号分隔，可空）</label>
        <input id="only" placeholder="例如 PWN"></div>
      <div class="f"><label>刷题模式（一批一个方向，批大小默认 = 并发数）</label>
        <div class="checks" style="margin-bottom:6px"><label><input type="checkbox" id="round_rotate"> 开启方向轮换（misc → re → crypto …）</label></div>
        <input id="rotate_batch" type="number" min="0" value="0" placeholder="批大小，0 = 并发数"></div>
      <div class="checks">
        <label><input type="checkbox" id="include_solved"> 含已解题</label>
      <label><input type="checkbox" id="writeup_enabled"> 写 Writeup</label>
      <label><input type="checkbox" id="think_chinese"> 中文思考</label>
          <label><input type="checkbox" id="require_flag_evidence"> 提交需带证据</label>
      <label><input type="checkbox" id="skip_solved_pull"> 拉题跳过已解</label>
        <label><input type="checkbox" id="trace_mask"> 日志脱敏</label>
        <label><input type="checkbox" id="fresh_solve"> 干净模式（不看历史记忆、清空本地题目）</label>
        <label><input type="checkbox" id="skills_enabled"> 技能库（按需加载 skills/*.md）</label>
        <label><input type="checkbox" id="chains_enabled"> 解题链（阶段 + 判据，chains/*.md）</label>
        <label><input type="checkbox" id="no_submit"> 不提交（演练）</label>
      </div>
      <div class="hint">「含已解题」才会把平台已标已解的题拉进本轮；「拉题跳过已解」只决定已解题要不要跳过（勾了「含已解题」时自动失效）。「干净模式」用于测试模型真实水平：不注入跨轮笔记、不写笔记、开跑前清空 challenges/ 里的旧题。</div>
    </section>
  </div>
  <div class="savebar">
    <button class="primary" id="save">保存配置</button>
    <button class="ghost" id="save-start">保存并开始</button>
    <div class="msg" id="cfgmsg"></div>
  </div>
</div>

<div id="tip"></div>
<script>
const esc = s => (s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TEXT_FIELDS = ["deepseek_base_url","dasctf_url","ctf2_url","ctf2_ground","ctfplus_url","ret2shell_url","ret2shell_game","ctfd_url",
  "round_order","only"];
const CATEGORY_CHOICES = ["web","misc","pwn","re","crypto"];
const DIFFICULTY_CHOICES = ["入门","简单","中等","困难"];
const SECRETS = ["deepseek_api_key","dasctf_access_key","ctf2_token","ctfplus_token","ret2shell_token","ctfd_token"];
const PLAT_LABELS = {dasctf:"DASCTF / 羊城杯", ctf2:"CTF² Agent Arena", ctfplus:"CTF+ / 极客挑战赛", ret2shell:"Ret2Shell / 西电 MoeCTF", ctfd:"CTFd", auto:"自动"};

let CFG = null, SOLVERS = [], SELECTED = null, PAGE = "main", FORCE_BOTTOM = false;

function showPage(name){
  PAGE = name;
  try { localStorage.setItem("ctf-tab", name); } catch(e){}
  document.querySelectorAll(".page").forEach(p=>p.classList.toggle("on", p.id==="page-"+name));
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("on", b.dataset.page===name));
  if(name==="config") loadConfig();
  if(name==="main") refresh();
}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>showPage(b.dataset.page));

function showCfgTab(name){
  document.querySelectorAll("#page-config .card").forEach(c=>c.classList.toggle("on", c.dataset.cfg===name));
  document.querySelectorAll("#cfg-tabs button").forEach(b=>b.classList.toggle("on", b.dataset.cfg===name));
  try { localStorage.setItem("ctf-cfgtab", name); } catch(e){}
}
document.querySelectorAll("#cfg-tabs button").forEach(b=>b.onclick=()=>showCfgTab(b.dataset.cfg));
try { const ct = localStorage.getItem("ctf-cfgtab"); if (ct) showCfgTab(ct); } catch(e){}
try { const saved = localStorage.getItem("ctf-tab"); if (saved === "config") showPage("config"); } catch(e){}

function renderChecks(){
  document.getElementById("cat-box").innerHTML = CATEGORY_CHOICES.map(v=>
    `<label><input type="checkbox" value="${v}"> ${v}</label>`).join("");
  document.getElementById("diff-box").innerHTML = DIFFICULTY_CHOICES.map(v=>
    `<label><input type="checkbox" value="${v}"> ${v}</label>`).join("");
}
function setChecks(box, value){
  const wanted = (value||"").split(",").map(s=>s.trim().toLowerCase()).filter(Boolean);
  const all = !wanted.length || wanted.includes("all");
  document.querySelectorAll("#"+box+" input").forEach(i=>{
    i.checked = !all && wanted.includes(i.value.toLowerCase());
  });
}
function getChecks(box){
  return [...document.querySelectorAll("#"+box+" input:checked")].map(i=>i.value);
}

function collectForm(){
  const p = {};
  for(const id of TEXT_FIELDS){ const el=document.getElementById(id); if(el) p[id]=el.value.trim(); }
  p.categories = getChecks("cat-box").join(",");
  p.difficulty = getChecks("diff-box").join(",");
  p.platform = document.getElementById("platform").value;
  p.round_size = parseInt(document.getElementById("round_size").value||"0",10)||0;
  p.max_concurrent = parseInt(document.getElementById("max_concurrent").value||"1",10)||1;
  p.challenge_timeout_min = parseFloat(document.getElementById("challenge_timeout_min").value||"0")||0;
  p.challenge_extra_rounds = parseInt(document.getElementById("challenge_extra_rounds").value||"0",10)||0;
  p.include_solved = document.getElementById("include_solved").checked;
  p.writeup_enabled = document.getElementById("writeup_enabled").checked;
  p.flag_format = document.getElementById("flag_format").value.trim();
  p.flag_submit_mode = document.getElementById("flag_submit_mode").value;
  p.think_chinese = document.getElementById("think_chinese").checked;
  p.require_flag_evidence = document.getElementById("require_flag_evidence").checked;
  p.skip_solved_pull = document.getElementById("skip_solved_pull").checked;
  p.trace_mask = document.getElementById("trace_mask").checked;
  p.fresh_solve = document.getElementById("fresh_solve").checked;
  p.skills_enabled = document.getElementById("skills_enabled").checked;
  p.chains_enabled = document.getElementById("chains_enabled").checked;
  p.round_rotate = document.getElementById("round_rotate").checked;
  p.blitz_mode = document.getElementById("blitz_mode").checked;
  p.rotate_batch = parseInt(document.getElementById("rotate_batch").value||"0",10)||0;
  p.max_environments = parseInt(document.getElementById("max_environments").value||"0",10)||0;
  p.no_submit = document.getElementById("no_submit").checked;
  p.models = [...document.querySelectorAll("#models input[type=checkbox]:checked")].map(i=>i.value);
  p.quotas = {};
  document.querySelectorAll("#models .mrow").forEach(row=>{
    const spec = row.querySelector("input[type=checkbox]").value;
    const limit = parseFloat(row.querySelector(".mlimit").value||"0") || 0;
    if(limit > 0) p.quotas[spec] = limit; else p.quotas[spec] = 0;
  });
  for(const id of SECRETS){ const v=document.getElementById(id).value.trim(); if(v) p[id]=v; }
  return p;
}

function providerName(spec, c){
  const prov = spec.split("/")[0];
  if(prov === "deepseek") return "DeepSeek";
  const hit = (c.providers||[]).find(p=>p.name===prov);
  return hit ? hit.name : prov;
}

function renderModelList(c){
  const quotas = c.quotas || {};
  const chosen = c.models || [];
  const choices = c.model_choices || [];
  if(!choices.length){
    document.getElementById("models").innerHTML = '<div class="empty">还没有可选模型</div>';
    return;
  }
  const groups = {};
  for(const spec of choices){
    const prov = spec.split("/")[0];
    (groups[prov] = groups[prov] || []).push(spec);
  }
  const html = Object.keys(groups).map(prov=>{
    const rows = groups[prov].map(spec=>{
      const q = quotas[spec] || {currency:"USD", limit:0, spent:0, remaining:null, available:true};
      const on = chosen.includes(spec);
      const sym = (q.currency||"USD")==="CNY" ? "¥" : "$";
      const rem = q.limit > 0 ? `剩余 ${sym}${(q.remaining ?? 0).toFixed(2)}` : "不限";
      const warn = q.limit > 0 && q.available === false ? ' class="mrem out"' : ' class="mrem"';
      const src = (q.currency||"USD")==="CNY" ? "（官方）" : "";
      return `<div class="mrow${on?" on":""}">
        <label class="chk"><input type="checkbox" value="${esc(spec)}" ${on?"checked":""}></label>
        <span class="mname">${esc(spec)}</span>
        <span class="mspent">已用 ${sym}${(q.spent||0).toFixed(2)}${src}</span>
        <input class="mlimit" type="number" min="0" step="1" value="${q.limit>0?q.limit:""}" placeholder="上限 ${sym}">
        <span${warn}>${rem}</span>
      </div>`;
    }).join("");
    const n = groups[prov].filter(x=>chosen.includes(x)).length;
    return `<div class="pgroup">
      <div class="phead"><b>${esc(providerName(groups[prov][0], c))}</b>
        <span class="dim">${groups[prov].length} 个模型 · 已选 ${n}</span>
        <span class="spacer"></span>
        <button class="mini" data-prov="${esc(prov)}" data-act="all">全选</button>
        <button class="mini" data-prov="${esc(prov)}" data-act="none">清空</button>
      </div>${rows}</div>`;
  }).join("");
  document.getElementById("models").innerHTML = html;
  document.querySelectorAll("#models .phead button").forEach(btn=>{
    btn.onclick = ()=>{
      const prov = btn.dataset.prov, act = btn.dataset.act;
      document.querySelectorAll("#models .mrow").forEach(row=>{
        const box = row.querySelector("input[type=checkbox]");
        if(box.value.split("/")[0] !== prov) return;
        box.checked = (act === "all");
        row.classList.toggle("on", box.checked);
      });
    };
  });
  document.querySelectorAll("#models input[type=checkbox]").forEach(box=>{
    box.onchange = ()=>box.closest(".mrow").classList.toggle("on", box.checked);
  });
}

function fillForm(c){
  CFG = c;
  document.getElementById("platform").value = (c.platform==="auto") ? "dasctf" : c.platform;
  document.getElementById("round_size").value = c.round_size ?? 1;
  document.getElementById("max_concurrent").value = c.max_concurrent ?? 1;
  document.getElementById("challenge_timeout_min").value = c.challenge_timeout_min ?? 0;
  document.getElementById("challenge_extra_rounds").value = c.challenge_extra_rounds ?? 0;
  setChecks("cat-box", c.categories || "");
  setChecks("diff-box", c.difficulty || "");
  document.getElementById("round_order").value = c.round_order || "random";
  document.getElementById("only").value = c.round_only || "";
  document.getElementById("include_solved").checked = !!c.include_solved;
  document.getElementById("writeup_enabled").checked = !!c.writeup_enabled;
  document.getElementById("flag_format").value = c.flag_format || "";
  document.getElementById("flag_submit_mode").value = c.flag_submit_mode || "full";
  document.getElementById("think_chinese").checked = c.think_chinese !== false;
  document.getElementById("require_flag_evidence").checked = c.require_flag_evidence !== false;
  document.getElementById("skip_solved_pull").checked = c.skip_solved_pull !== false;
  document.getElementById("trace_mask").checked = c.trace_mask !== false;
  document.getElementById("fresh_solve").checked = c.fresh_solve === true;
  document.getElementById("skills_enabled").checked = c.skills_enabled !== false;
  document.getElementById("chains_enabled").checked = c.chains_enabled !== false;
  document.getElementById("round_rotate").checked = !!c.round_rotate;
  document.getElementById("blitz_mode").checked = c.blitz_mode === true;
  document.getElementById("rotate_batch").value = c.rotate_batch || 0;
  document.getElementById("max_environments").value = c.max_environments || 0;
  document.getElementById("deepseek_base_url").value = c.deepseek_base_url || "";
  document.getElementById("dasctf_url").value = c.dasctf_url || "";
  document.getElementById("ctf2_url").value = c.ctf2_url || "";
  document.getElementById("ctf2_ground").value = c.ctf2_ground || "";
  document.getElementById("ctfplus_url").value = c.ctfplus_url || "";
  document.getElementById("ret2shell_url").value = c.ret2shell_url || "";
  document.getElementById("ret2shell_game").value = c.ret2shell_game || "";
  document.getElementById("ctfd_url").value = c.ctfd_url || "";
  renderModelList(c);
  for(const id of SECRETS){
    const el=document.getElementById(id); el.value="";
    el.placeholder = c[id+"_set"] ? ("已设置 "+(c[id+"_masked"]||"")) : "未设置";
  }
  renderProviders(c.providers||[]);
  updatePlatformBoxes();
  syncSolvedSwitches();
}
function updatePlatformBoxes(){
  const p = document.getElementById("platform").value;
  for(const k of ["dasctf","ctf2","ctfplus","ret2shell","ctfd"]){
    document.getElementById("box-"+k).style.display = (p===k) ? "block" : "none";
  }
  document.getElementById("chip-plat").textContent = "平台：" + (PLAT_LABELS[p]||p);
}
document.getElementById("platform").onchange = updatePlatformBoxes;

// 「含已解题」与「拉题跳过已解」互相矛盾：勾了前者就把后者置灰，避免出现
// "既想重做、又被本地短路拦住" 的状态。
function syncSolvedSwitches(){
  const inc = document.getElementById("include_solved");
  const skip = document.getElementById("skip_solved_pull");
  if(!inc || !skip) return;
  skip.disabled = inc.checked;
  if(inc.checked) skip.checked = false;
  skip.title = inc.checked ? "已勾选「含已解题」：本项自动失效，已解题会真的被拉取并提交" : "";
}
document.getElementById("include_solved").onchange = syncSolvedSwitches;

function renderProviders(list){
  const box = document.getElementById("providers");
  if(!list || !list.length){ box.innerHTML = '<div class="hint">还没有自定义供应商</div>'; return; }
  box.innerHTML = list.map(p=>`<div class="prov">
      <div class="prov-head">
        <b>${esc(p.name)}</b>
        <span class="hint">${esc(p.base_url)}</span>
      </div>
      <div class="hint">Key: ${p.api_key_set ? "已设置 "+esc(p.api_key_masked) : "未设置"} · 模型 ${p.models.length} 个</div>
      <div class="btns" style="margin-top:6px">
        <button class="ghost" data-refetch="${esc(p.name)}">拉取模型</button>
        <button class="ghost" data-del="${esc(p.name)}">删除</button>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-refetch]").forEach(b=>b.onclick=()=>fetchProviderModels(b.dataset.refetch));
  box.querySelectorAll("[data-del]").forEach(b=>b.onclick=async ()=>{
    if(!confirm("删除供应商 "+b.dataset.del+" ?")) return;
    const r=await fetch("/api/providers/delete",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:b.dataset.del})});
    const j=await r.json(); renderProviders(j.providers); provMsg("已删除","ok"); loadConfig();
  });
}
function provMsg(t, cls){ const m=document.getElementById("provmsg"); m.textContent=t; m.className="msg "+(cls||""); }

async function addProvider(){
  const name=document.getElementById("prov-name").value.trim();
  const base_url=document.getElementById("prov-url").value.trim();
  const api_key=document.getElementById("prov-key").value.trim();
  if(!name||!base_url){ provMsg("名称和 Base URL 必填","err"); return false; }
  const r=await fetch("/api/providers",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name,base_url,api_key})});
  const j=await r.json();
  if(!j.ok){ provMsg(j.error||"添加失败","err"); return false; }
  renderProviders(j.providers); provMsg("供应商已保存，可以点「拉取模型」","ok");
  loadConfig(); return true;
}
async function fetchProviderModels(name){
  const base_url=document.getElementById("prov-url").value.trim();
  const api_key=document.getElementById("prov-key").value.trim();
  provMsg("正在拉取 "+name+" 的模型…");
  const r=await fetch("/api/providers/fetch",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name, base_url: name? base_url : "", api_key})});
  const j=await r.json();
  if(!j.ok){ provMsg("拉取失败: "+(j.error||""),"err"); return; }
  renderProviders(j.providers);
  provMsg(`拉到 ${j.models.length} 个模型，已加入模型列表（在上面勾选要用的）`, "ok");
  loadConfig();
}
document.getElementById("addprov").onclick = addProvider;
document.getElementById("fetchprov").onclick = async () => {
  const name = document.getElementById("prov-name").value.trim();
  if(!name){ provMsg("先填供应商名称","err"); return; }
  if(await addProvider()) await fetchProviderModels(name);
};

async function addModel(){
  const spec = document.getElementById("newmodel").value.trim();
  if(!spec){ return; }
  await fetch("/api/models",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({models:[spec]})});
  document.getElementById("newmodel").value = "";
  document.getElementById("hint-newmodel").textContent = "已加入："+spec;
  loadConfig();
}
document.getElementById("addmodel").onclick = addModel;
document.getElementById("newmodel").onkeydown = e => { if(e.key==="Enter") addModel(); };

async function loadConfig(){
  try{ fillForm(await (await fetch("/api/config")).json()); }
  catch(e){ document.getElementById("cfgmsg").textContent = "读取配置失败: "+e; }
  try{
    const b = await (await fetch("/api/balance")).json();
    const hint = document.getElementById("bal-hint");
    if(b.ok && b.total!=null){
      hint.textContent = `官网余额 ${b.currency==="CNY"?"¥":"$"}${b.total}` +
        (b.spent!=null ? ` · 已用 ¥${Number(b.spent).toFixed(2)}（按余额差）` : "");
    }else{ hint.textContent = b.error || ""; }
  }catch(e){}
}
document.getElementById("bal-reset").onclick = async ()=>{
  try{
    const r = await fetch("/api/balance/reset",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const j = await r.json();
    if(j.ok){ cfgMsg("已把当前余额设为基准（已用归零）","ok"); loadConfig(); }
    else cfgMsg(j.error||"重置失败","err");
  }catch(e){ cfgMsg("重置失败: "+e,"err"); }
};
function cfgMsg(text, cls){ const m=document.getElementById("cfgmsg"); m.textContent=text; m.className="msg "+(cls||""); }

async function saveOnly(){
  const r = await fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(collectForm())});
  const j = await r.json();
  if(j.ok){ cfgMsg("已保存到 .env", "ok"); loadConfig(); }
  else cfgMsg("保存失败: "+(j.error||""), "err");
}
async function postStart(form, okText){
  const send = async (extra) => {
    const r = await fetch("/api/run/start",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(Object.assign({}, form, extra||{}))});
    return await r.json();
  };
  let j = await send();
  const busy = () => /已经有轮次|已经在运行|already running/i.test(j.error||"");
  if(!j.ok && busy()){
    if(!confirm("当前有一轮在跑（会先停掉它，正在跑的目标会被清理）。继续吗？")){
      const chip = document.getElementById("chip-run");
      if(chip) chip.textContent = "已有轮次在跑";
      return false;
    }
    j = await send({restart:true});
  }
  if(!j.ok){
    cfgMsg(j.error||"启动失败", "err");
    const chip = document.getElementById("chip-run");
    if(chip) chip.textContent = busy() ? "已有轮次在跑" : "启动失败";
    return false;
  }
  cfgMsg(okText ? okText.replace("%PID%", j.pid) : ("已启动 pid "+j.pid), "ok");
  showPage("main"); pollRun();
  return true;
}
async function startRun(){
  return postStart(collectForm());
}
document.getElementById("save").onclick = saveOnly;
document.getElementById("save-start").onclick = startRun;
document.getElementById("start").onclick = startRun;

// ---- board picking: choose exactly which challenges to run -------------------
let PICKING = false;
const PICK = new Set();

function renderPick(){
  const bar = document.getElementById("pickbar");
  const n = PICK.size;
  if(bar) bar.hidden = !PICKING && n === 0;
  const count = document.getElementById("pick-count");
  if(count) count.textContent = n ? `已选 ${n} 道` : "点方格选择题目";
  const run = document.getElementById("pick-run");
  if(run) run.disabled = n === 0;
  const t = document.getElementById("pick-toggle");
  if(t){ t.textContent = PICKING ? "取消选择" : "选择"; t.classList.toggle("on", PICKING); }
  const board = document.getElementById("board");
  if(board) board.classList.toggle("picking", PICKING);
}

function togglePick(name){
  if(!name) return;
  if(PICK.has(name)) PICK.delete(name); else PICK.add(name);
  document.querySelectorAll("#board .sq").forEach(sq=>{
    if(sq.dataset.name === name) sq.classList.toggle("picked", PICK.has(name));
  });
  renderPick();
}

document.getElementById("pick-toggle").onclick = () => {
  PICKING = !PICKING;
  if(!PICKING) PICK.clear();
  document.querySelectorAll("#board .sq.picked").forEach(sq=>sq.classList.remove("picked"));
  renderPick();
};
document.getElementById("pick-clear").onclick = () => {
  PICK.clear();
  document.querySelectorAll("#board .sq.picked").forEach(sq=>sq.classList.remove("picked"));
  renderPick();
};
document.getElementById("pick-run").onclick = startPicked;

document.getElementById("board").addEventListener("click", ev => {
  const sq = ev.target.closest(".sq");
  if(!sq) return;
  if(!PICKING){ PICKING = true; }
  togglePick(sq.dataset.name || "");
});

async function startPicked(){
  const names = [...PICK];
  if(!names.length) return;
  const form = collectForm();
  form.pick = names;
  // Re-running a challenge the platform already credits only works with
  // include_solved; tick it for the operator instead of failing silently.
  const solvedPicked = document.querySelectorAll("#board .sq.picked.solved").length;
  if(solvedPicked && !form.include_solved){
    form.include_solved = true;
    const box = document.getElementById("include_solved");
    if(box){ box.checked = true; if(typeof syncSolvedSwitches === "function") syncSolvedSwitches(); }
  }
  const ok = await postStart(form, `已启动 pid %PID%（${names.length} 道自选题）`);
  if(ok){ PICKING = false; PICK.clear(); renderPick(); }
}
document.getElementById("resume-last").onclick = async () => {
  const form = collectForm();
  form.resume = "latest";
  await postStart(form, "已从上次未完成的轮次继续，pid %PID%");
};
async function pollRuns(){
  try{
    const j = await (await fetch("/api/runs")).json();
    const runs = j.runs || [];
    const open = runs.filter(r=>!r.finished);
    const hint = document.getElementById("resume-hint");
    if(!hint) return;
    const o = open[0];
    if(o){
      const spent = o.cost_usd ? `，$${Number(o.cost_usd).toFixed(3)}` : "";
      hint.textContent = `上次未完成：${o.run_id}（${o.solved}/${o.total} 已解${spent}）`;
    } else {
      hint.textContent = "没有未完成的轮次";
    }
  }catch(e){}
}
pollRuns(); setInterval(pollRuns, 15000);
document.getElementById("stop").onclick = async () => {
  await fetch("/api/run/stop",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
  pollRun();
};
document.getElementById("toolist").onclick = () => {
  const plat = (CFG && CFG.platform) ? CFG.platform : "auto";
  alert("题目清单在命令行查看：\\n\\nuv run python scripts\\\\list_" + (plat==="ret2shell"?"ret2shell":"dasctf") + ".py\\n\\n它会以只读方式列出平台的题目、分值、难度和是否已解。");
};

async function pollRun(){
  try{
    const j = await (await fetch("/api/run")).json();
    const chip = document.getElementById("chip-run");
    const st = document.getElementById("runstate");
    if(j.concurrency && document.activeElement !== document.getElementById("conc")){
      document.getElementById("conc").value = j.concurrency;
    }
    if(j.running){
      const mins = Math.floor((Date.now()/1000 - j.started_at)/60);
      chip.innerHTML = '<b class="on">● 运行中</b>';
      st.innerHTML = `<span class="on">● 运行中</span> pid ${j.pid} · ${mins} 分钟 · 并发 ${j.concurrency||1}`;
    }else if(j.exit_code!=null){
      chip.textContent = "已结束";
      st.textContent = "○ 已结束，退出码 " + j.exit_code + "（日志 logs/" + j.log + "）";
    }else{
      chip.textContent = "未运行";
      st.textContent = "状态：未运行";
    }
  }catch(e){}
}

async function applyConcurrency(){
  const v = parseInt(document.getElementById("conc").value||"1",10)||1;
  try{
    const r = await fetch("/api/run/concurrency",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({value:v})});
    const j = await r.json();
    if(j.ok){ cfgMsg("并发数已设为 "+j.concurrency+"（运行中立即生效）","ok"); }
    else { cfgMsg(j.error||"设置失败","err"); }
  }catch(e){ cfgMsg("设置失败: "+e,"err"); }
}
document.getElementById("conc-apply").onclick = applyConcurrency;

async function pollBalance(){
  const el = document.getElementById("chip-bal");
  try{
    const j = await (await fetch("/api/balance")).json();
    if(j.ok && j.total!=null){
      const sym = (j.currency||"CNY").toUpperCase()==="CNY" ? "¥" : "$";
      el.textContent = "余额 " + sym + j.total;
      el.title = "DeepSeek 官方余额（" + (j.currency||"") + "）";
    }else{
      el.textContent = "";
      el.title = j.error || "";
    }
  }catch(e){ el.textContent = ""; }
}

function renderEvent(ev){
  const t = ev.type;
  if(t==='thinking') return `<div class="ev think">💭 ${esc((ev.text||'').slice(0,900))}</div>`;
  if(t==='tool_call') return `<div class="ev tool">› ${esc(ev.tool||'')} ${esc((ev.args||'').slice(0,400))}</div>`;
  if(t==='tool_result') return `<div class="ev result">‹ ${esc((ev.result||'').slice(0,600))}</div>`;
  if(t==='message') return `<div class="ev">${esc((ev.text||'').slice(0,600))}</div>`;
  if(t==='hint_injected') return `<div class="ev hintx">↵ 注入提示 x${ev.count||1}</div>`;
  if(t==='flag_confirmed') return `<div class="ev flag">✔ 提交成功</div>`;
  if(t==='start') return `<div class="ev result">—— 开始 ${esc(ev.challenge||'')} / ${esc(ev.model||'')}</div>`;
  return '';
}

function metaText(s){
  const bits=[];
  if(s.category) bits.push(s.category);
  if(s.value) bits.push(s.value+" 分");
  if(s.difficulty) bits.push(s.difficulty);
  return bits.join(" · ");
}

function renderSolvers(){
  const list = document.getElementById("slist");
  document.getElementById("chip-solvers").textContent = SOLVERS.length + " 个 solver";  if(!SOLVERS.length){ list.innerHTML = '<div class="empty">还没有 solver<br><small>到「配置」页点保存并开始</small></div>'; return; }
  if(!SELECTED || !SOLVERS.some(s=>s.key===SELECTED)) SELECTED = SOLVERS[0].key;
  list.innerHTML = SOLVERS.map(s=>`<div class="sitem ${s.key===SELECTED?"on":""} ${s.finished?"fin":""}" data-key="${esc(s.key)}" title="${esc(s.challenge)}">
      <span class="dot ${s.active?"on":""}"></span>
      <span class="col">
        <span class="nm" data-tip="${esc(s.challenge)}">${esc(s.challenge)}</span>
        <span class="md">${esc(metaText(s))}${metaText(s)?" · ":""}${esc(s.model||"")}${s.since?" · "+esc(s.since):""}</span>
      </span>
    </div>`).join("");
  list.querySelectorAll(".sitem").forEach(el=>el.onclick=()=>{ SELECTED = el.dataset.key; FORCE_BOTTOM = true; renderSolvers(); renderLog(); });
}

function renderLog(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  const log = document.getElementById("log");
  const input = document.getElementById("hint-input");
  if(!cur){
    document.getElementById("pane-title").textContent = "选择一个题目观察";
    log.innerHTML = '<div class="empty">点击左侧题目查看思考与操作</div>';
    input.disabled = true; return;
  }
  const mt = metaText(cur);
  document.getElementById("pane-title").innerHTML = `${esc(cur.challenge)} ${mt?`<span class="md">${esc(mt)}</span>`:""} <span class="md">${esc(cur.model||"")}${cur.since?" · "+esc(cur.since):""}</span>`;
  const prevTop = log.scrollTop;
  const atBottom = FORCE_BOTTOM || log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  FORCE_BOTTOM = false;
  log.innerHTML = (cur.events||[]).map(renderEvent).join('') || '<div class="empty">等待输出…</div>';
  // innerHTML resets scrollTop to 0 — restore it so reading does not jump.
  log.scrollTop = atBottom ? log.scrollHeight : prevTop;
  input.disabled = false;
  input.placeholder = `给 ${cur.challenge} 发提示，回车发送`;
  const skip = document.getElementById("skip");
  skip.disabled = !cur.active;
  skip.textContent = cur.active ? "跳过此题" : "已结束";
}

async function skipChallenge(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  if(!cur) return;
  if(!confirm(`跳过「${cur.challenge}」？这道题会立刻停止，并发位让给下一题。`)) return;
  try{
    const r = await fetch('/api/solver/skip',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({challenge: cur.challenge})});
    const j = await r.json();
    if(j.ok){ cfgMsg("已请求跳过 "+cur.challenge,"ok"); }
    else { cfgMsg(j.error||"跳过失败","err"); }
  }catch(e){ cfgMsg("跳过失败: "+e,"err"); }
}

async function refresh(){
  if(PAGE!=="main") return;
  const all = '?all=1';
  try{
    const j = await (await fetch('/api/state'+all)).json();
    SOLVERS = (j.solvers||[]).map(s=>({...s, key: s.file || s.challenge}));
    renderSolvers(); renderLog();
  }catch(e){}
}

async function sendHint(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  const input = document.getElementById("hint-input");
  const text = input.value.trim();
  if(!cur || !text) return;
  await fetch('/api/hint',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({challenge: cur.challenge, text})});
  input.value = '';
}
document.getElementById("hint-send").onclick = sendHint;
document.getElementById("hint-input").onkeydown = e => { if(e.key==='Enter') sendHint(); };

// 左侧题目栏宽度可拖动，双击恢复默认；宽度记在 localStorage
document.getElementById("skip").onclick = skipChallenge;

(function(){
  const KEY = "ctf-rail-w";
  const saved = localStorage.getItem(KEY);
  if(saved) document.documentElement.style.setProperty("--rail-w", saved);
  const sp = document.getElementById("splitter");
  let dragging = false;
  sp.addEventListener("mousedown", e => { dragging = true; e.preventDefault(); document.body.style.userSelect = "none"; });
  window.addEventListener("mousemove", e => {
    if(!dragging) return;
    const w = Math.max(200, Math.min(e.clientX - 14, window.innerWidth - 380));
    document.documentElement.style.setProperty("--rail-w", w + "px");
  });
  window.addEventListener("mouseup", () => {
    if(!dragging) return;
    dragging = false; document.body.style.userSelect = "";
    localStorage.setItem(KEY, getComputedStyle(document.documentElement).getPropertyValue("--rail-w").trim());
  });
  sp.addEventListener("dblclick", () => {
    document.documentElement.style.setProperty("--rail-w", "330px");
    localStorage.setItem(KEY, "330px");
  });
})();

setInterval(refresh, 1500);
setInterval(pollRun, 3000);
setInterval(pollBalance, 60000);
setInterval(pollBoard, 5000);

async function pollBoard(){
  try{
    const j = await (await fetch("/api/board")).json();
    renderBoard(j);
  }catch(e){}
}

function renderBoard(j){
  const box = document.getElementById("board");
  const scope = document.getElementById("bscope");
  const groups = (j && j.groups) || [];
  if(scope) scope.textContent = (j.scope === "all" ? "全部" : "本批") + (j.total ? ` · ${j.solved}/${j.total}` : "") + (j.error ? ` · ${j.error}` : "");
  if(scope) scope.title = j.error || "";
  if(!groups.length){ box.innerHTML = '<div class="empty">还没有题目</div>'; return; }
  box.innerHTML = groups.map(g=>{
    const done = g.items.filter(i=>i.solved).length;
    return `<div class="bgroup"><div class="gtitle"><span>${esc(g.label||g.category)}</span><span>${done}/${g.items.length}</span></div>
      <div class="grid">${g.items.map(i=>{
        const cls = "sq" + (i.solved?" solved":"") + (i.active?" active":"")
          + (PICK.has(i.name)?" picked":"") + (PICKING?" pickable":"");
        const tip = [i.name, i.difficulty, i.value?i.value+" 分":""].filter(Boolean).join(" · ");
        return `<div class="${cls}" data-name="${esc(i.name||"")}" data-tip="${esc(tip)}">${esc((i.name||"?").slice(0,2))}</div>`;
      }).join("")}</div></div>`;
  }).join("");
  renderPick();
}

renderChecks();
renderPick(); refresh(); pollRun(); pollBalance(); pollBoard(); loadConfig();

// Instant tooltip: native title has a ~1s delay and clips long names.
const TIP = document.getElementById("tip");
function tipPlace(x, y){
  const pad = 14;
  let left = x + pad, top = y + pad;
  const r = TIP.getBoundingClientRect();
  if(left + r.width > window.innerWidth - 8) left = Math.max(8, x - r.width - pad);
  if(top + r.height > window.innerHeight - 8) top = Math.max(8, y - r.height - pad);
  TIP.style.left = left + "px";
  TIP.style.top = top + "px";
}
document.addEventListener("mouseover", e => {
  const el = e.target.closest && e.target.closest("[data-tip]");
  if(!el) return;
  TIP.textContent = el.getAttribute("data-tip") || "";
  TIP.style.opacity = "1";
  tipPlace(e.clientX, e.clientY);
});
document.addEventListener("mousemove", e => {
  if(TIP.style.opacity === "1") tipPlace(e.clientX, e.clientY);
});
document.addEventListener("mouseout", e => {
  if(e.target.closest && e.target.closest("[data-tip]")) TIP.style.opacity = "0";
});
window.addEventListener("scroll", () => { TIP.style.opacity = "0"; }, true);
</script></body></html>
"""
