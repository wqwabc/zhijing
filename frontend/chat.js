/* 植境 Verda · 右侧对话列（接 /api/chat）
 * 上下文从 window.VERDA 取；Key/Base 只存 sessionStorage，随请求头传给后端。 */
(function () {
  'use strict';

  var log = document.getElementById('chatLog');
  var form = document.getElementById('chatForm');
  var input = document.getElementById('chatInput');
  var hint = document.getElementById('chatHint');
  var settingsBtn = document.getElementById('chatSettingsBtn');
  var settings = document.getElementById('chatSettings');
  var keyInput = document.getElementById('llmKey');
  var baseInput = document.getElementById('llmBase');
  var saveBtn = document.getElementById('llmSave');
  var savedNote = document.getElementById('llmSaved');
  var history = [];
  var busy = false;

  if (!log || !form) return;

  function lsKey() { return sessionStorage.getItem('verda_llm_key') || ''; }
  function lsBase() { return sessionStorage.getItem('verda_llm_base') || ''; }

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
    add('bot', '我是植境助手。左边可以自己拼植物，右边问我：这套为什么这样搭？预算能再低吗？某株怎么养？');
  }

  function syncHint() {
    var key = lsKey();
    if (key) {
      hint.textContent = '本会话 Key 已就绪 · ' + (lsBase() || '默认 DeepSeek Base');
      return;
    }
    var base = apiBase();
    if (!base) {
      hint.textContent = '离线模式：带上 ?api=http://127.0.0.1:5055 才能对话';
      return;
    }
    fetch(base + '/healthz').then(function (r) { return r.json(); }).then(function (d) {
      var ok = d && d.llm && d.llm.available;
      hint.textContent = ok ? ('服务端已连接 ' + (d.llm.model || 'DeepSeek'))
        : '未配置 Key：当前为模板回答（可在 ⚙ 里填）';
    }).catch(function () { hint.textContent = '后端不可用'; });
  }

  function openSettings(show) {
    settings.hidden = !show;
    if (show) {
      keyInput.value = lsKey();
      baseInput.value = lsBase();
      keyInput.focus();
    }
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
    var headers = { 'Content-Type': 'application/json' };
    if (lsKey()) headers['X-LLM-Key'] = lsKey();
    if (lsBase()) headers['X-LLM-Base'] = lsBase();

    var body = {
      message: msg,
      history: history.slice(-6),
      plant_ids: (window.VERDA && window.VERDA.plantIds) ? window.VERDA.plantIds() : [],
      scene: (window.VERDA && window.VERDA.scene) ? window.VERDA.scene() : {}
    };

    fetch(base + '/api/chat', {
      method: 'POST',
      headers: headers,
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
      hint.textContent = res.data.source === 'llm'
        ? 'DeepSeek 回答 · ' + (res.data.model || '')
        : '模板回答（未配置 Key）';
    }).catch(function () {
      typing.remove();
      add('sys', '网络或后端不可用');
    }).then(function () { busy = false; });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    send(input.value.trim());
  });

  settingsBtn.addEventListener('click', function () { openSettings(settings.hidden); });
  saveBtn.addEventListener('click', function () {
    var key = keyInput.value.trim();
    var base = baseInput.value.trim();
    if (key) sessionStorage.setItem('verda_llm_key', key);
    else sessionStorage.removeItem('verda_llm_key');
    if (base) sessionStorage.setItem('verda_llm_base', base);
    else sessionStorage.removeItem('verda_llm_base');
    savedNote.textContent = key ? '已保存到本会话（刷新后失效）' : '已清除本会话 Key';
    syncHint();
    openSettings(false);
  });

  greeting();
  syncHint();

  /* ?chat=1 时展开设置，便于演示 */
  if (new URLSearchParams(location.search).get('chat') === '1') {
    setTimeout(function () { openSettings(true); }, 300);
  }
})();
