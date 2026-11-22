/* 植境 Verda · 对话窗口（接 /api/chat）
 * 上下文从 window.VERDA 取（场景、当前植物、评分），没有 Key 时后端走模板兜底。 */
(function () {
  'use strict';

  var fab = document.getElementById('chatFab');
  var panel = document.getElementById('chatPanel');
  var log = document.getElementById('chatLog');
  var form = document.getElementById('chatForm');
  var input = document.getElementById('chatInput');
  var closeBtn = document.getElementById('chatClose');
  var hint = document.getElementById('chatHint');
  var history = [];
  var busy = false;

  function apiBase() {
    var q = new URLSearchParams(location.search);
    if (q.has('api')) return String(q.get('api')).replace(/\/$/, '');
    if (window.VERDA && window.VERDA.online && window.VERDA.online()) {
      return window.VERDA.api();
    }
    return '';
  }

  function add(role, text) {
    var div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function greeting() {
    if (log.children.length) return;
    add('bot', '我是植境助手。可以问：这套为什么这样搭？预算能再低吗？某株是干什么的？');
  }

  function open() {
    panel.hidden = false;
    greeting();
    input.focus();
    var base = apiBase();
    if (!base) {
      hint.textContent = '离线模式：带上 ?api=http://127.0.0.1:5055 才能对话';
      return;
    }
    fetch(base + '/healthz').then(function (r) { return r.json(); }).then(function (d) {
      var ok = d && d.llm && d.llm.available;
      hint.textContent = ok ? ('已连接 ' + (d.llm.model || 'DeepSeek'))
        : '未配置 Key：当前为模板回答';
    }).catch(function () {
      hint.textContent = '后端不可用';
    });
  }

  function send(msg) {
    if (busy || !msg) return;
    busy = true;
    add('user', msg);
    input.value = '';

    var base = apiBase();
    if (!base) {
      add('sys', '离线模式：先启动后端，并在地址后加 ?api=http://127.0.0.1:5055');
      busy = false;
      return;
    }

    var typing = add('sys', '正在思考…');
    var body = {
      message: msg,
      history: history.slice(-6),
      plant_ids: (window.VERDA && window.VERDA.plantIds) ? window.VERDA.plantIds() : [],
      scene: (window.VERDA && window.VERDA.scene) ? window.VERDA.scene() : {}
    };

    fetch(base + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok, data: d }; });
    }).then(function (res) {
      typing.remove();
      if (!res.ok) {
        var e = res.data && res.data.error;
        add('sys', '出错了：' + ((e && e.message) || '请稍后再试'));
        return;
      }
      var reply = res.data.reply || '（空回答）';
      add('bot', reply);
      history.push({ role: 'user', content: msg });
      history.push({ role: 'assistant', content: reply });
      hint.textContent = res.data.source === 'llm' ? 'DeepSeek 回答' : '模板回答（未配置 Key）';
    }).catch(function () {
      typing.remove();
      add('sys', '网络或后端不可用');
    }).then(function () {
      busy = false;
    });
  }

  fab.addEventListener('click', function () {
    if (panel.hidden) open(); else panel.hidden = true;
  });
  closeBtn.addEventListener('click', function () { panel.hidden = true; });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    send(input.value.trim());
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) panel.hidden = true;
  });

  /* ?chat=1 直接展开，方便截图与演示 */
  if (new URLSearchParams(location.search).get('chat') === '1') {
    setTimeout(open, 250);
  }
})();
