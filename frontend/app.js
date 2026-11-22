/* 植境 Verda · 前端交互（E）
 *
 * 两种运行形态：
 *   1) 只开静态服务 → 离线演示模式：植物/案例读 data/ 与 assets/，锚定与合成为纯前端；
 *   2) 带上 ?api=http://127.0.0.1:5055 → 接 D 的 Flask 后端：合成、评分、推荐、改稿走真接口。
 */
(function () {
  'use strict';

  var CFG = {
    api: new URLSearchParams(location.search).has('api')
      ? String(new URLSearchParams(location.search).get('api')).replace(/\/$/, '')
      : '',
    demo: new URLSearchParams(location.search).get('demo') === '1',
    dataRoot: '../data/',
    assetRoot: '../',
    maxPlants: 6
  };

  var $ = function (id) { return document.getElementById(id); };
  var clamp = function (v, a, b) { return v < a ? a : (v > b ? b : v); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var fmt = function (n, d) { return (n == null || isNaN(n)) ? '—' : Number(n).toFixed(d == null ? 1 : d); };

  var LIGHT_CN = { L1: 'L1 耐阴', L2: 'L2 散射', L3: 'L3 明亮散射', L4: 'L4 直射' };
  var TOXIC_CN = { safe: '无毒', toxic: '有毒', unknown: '未知' };

  var S = {
    online: false,
    catalog: [],
    ready: 0,
    photo: null,          // {url, w, h, id, source}
    anchor: null,         // {g1,g2,r1,r2,pxPerCm,groundY,refCm,refType}
    plants: [],           // {uid, plantId, x, heightCm, layer}
    selected: null,
    mode: 'idle',         // idle | ground | ref
    temp: [],
    drag: null,
    uid: 0,
    scale: 1,
    score: null,
    composing: false,
    lastComposeUrl: null
  };
  var IMGCACHE = {};      // plantId -> {img, bb}
  var CASES = [];

  /* ---------------------------------------------------------- 基础 */
  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.classList.remove('on'); }, ms || 2300);
  }
  function loading(on, text) {
    $('loading').classList.toggle('on', !!on);
    if (text) $('loadingText').textContent = text;
  }
  function apiUrl(p) { return CFG.api + p; }

  function req(path, opts) {
    opts = opts || {};
    var url = apiUrl(path);
    var init = { method: opts.method || 'GET', headers: {} };
    if (opts.json) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.json);
    }
    if (opts.body) { init.method = 'POST'; init.body = opts.body; }
    return fetch(url, init).then(function (r) {
      return r.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (!r.ok) {
          var msg = data && data.error ? data.error.message : ('HTTP ' + r.status);
          var hint = data && data.error && data.error.hint ? '（' + data.error.hint + '）' : '';
          throw new Error(msg + hint);
        }
        return data;
      });
    });
  }

  /* ---------------------------------------------------------- 植物目录 */
  function parseCSV(text) {
    var rows = [], row = [], cur = '', q = false, i = 0;
    if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
    for (; i < text.length; i++) {
      var ch = text[i];
      if (q) {
        if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else { q = false; } }
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ',') { row.push(cur); cur = ''; }
      else if (ch === '\n') { row.push(cur); rows.push(row); row = []; cur = ''; }
      else if (ch !== '\r') cur += ch;
    }
    if (cur.length || row.length) { row.push(cur); rows.push(row); }
    return rows;
  }

  function normApi(p) {
    return {
      id: p.plant_id, name: p.name_cn, latin: p.name_latin || '',
      hMin: p.height_range_cm[0], hMax: p.height_range_cm[1],
      spread: p.spread_cm, price: p.price_cny || '',
      tags: p.tags || [], available: !!p.available,
      thumb: p.thumb_url ? apiUrl(p.thumb_url) : null,
      image: p.image_url ? apiUrl(p.image_url) : null,
      kind: p.kind || 'photo',
      styles: p.style_tags || [], petSafe: !!p.pet_safe, toxic: p.toxic
    };
  }
  function normLocal(it, master) {
    var m = master[it.plant_id] || {};
    var tags = [];
    if (m.leaf && m.leaf.indexOf('大叶') >= 0) tags.push('大叶');
    if (it.light_level === 'L1' || it.light_level === 'L2') tags.push('耐阴');
    if (m.form === '垂吊') tags.push('垂吊');
    if (it.pet_safe) tags.push('宠物友好');
    if (it.toxic === 'toxic') tags.push('有毒');
    var file = it.file || null;
    return {
      id: it.plant_id, name: it.name_cn, latin: it.name_latin || '',
      hMin: it.height_range_cm[0], hMax: it.height_range_cm[1],
      spread: it.spread_cm, price: m.price_cny || '',
      tags: tags, available: !!it.has_cutout,
      thumb: file ? CFG.assetRoot + file : null,
      image: file ? CFG.assetRoot + file : null,
      kind: (file && file.indexOf('/illustrations/') >= 0) ? 'illustration' : 'photo',
      styles: it.style_tags || [], petSafe: !!it.pet_safe, toxic: it.toxic
    };
  }

  function loadCatalog() {
    return req('/api/plants').then(function (d) {
      S.online = true;
      S.catalog = (d.plants || []).map(normApi);
      S.ready = S.catalog.filter(function (p) { return p.available; }).length;
      $('apiState').textContent = '后端已连接';
      $('apiState').className = 'badge';
    }).catch(function () {
      S.online = false;
      $('apiState').textContent = '离线演示';
      $('apiState').className = 'badge warn';
      var master = {};
      return fetch(CFG.dataRoot + 'plants_master.csv')
        .then(function (r) { return r.text(); })
        .then(function (txt) {
          var rows = parseCSV(txt), head = rows.shift() || [];
          rows.forEach(function (r) {
            if (!r.length || !r[0]) return;
            var o = {};
            head.forEach(function (h, i) { o[h] = r[i]; });
            master[o.plant_id] = o;
          });
        })
        .catch(function () { })
        .then(function () {
          return fetch(CFG.dataRoot + 'assets_index.json')
            .then(function (r) { return r.json(); })
            .then(function (j) {
              S.catalog = j.items.map(function (it) { return normLocal(it, master); });
            });
        })
        .catch(function () { S.catalog = []; })
        .then(function () {
          S.ready = S.catalog.filter(function (p) { return p.available; }).length;
        });
    }).then(function () {
      renderPalette();
      renderRecNote();
    });
  }

  function illuCount(list) {
    return (list || []).filter(function (id) {
      var p = byId(id);
      return p && p.kind === 'illustration';
    }).length;
  }

  function byId(id) {
    for (var i = 0; i < S.catalog.length; i++) if (S.catalog[i].id === id) return S.catalog[i];
    return null;
  }
  function median(p) { return Math.round((p.hMin + p.hMax) / 2); }

  function getImg(p, cb) {
    if (IMGCACHE[p.id]) { if (IMGCACHE[p.id].ready) cb(IMGCACHE[p.id]); return; }
    var rec = { img: new Image(), bb: null, ready: false };
    IMGCACHE[p.id] = rec;
    rec.img.onload = function () {
      rec.bb = alphaBox(rec.img);
      rec.ready = true;
      cb(rec);
    };
    rec.img.onerror = function () { rec.ready = false; };
    rec.img.src = p.image;
  }

  function alphaBox(img) {
    var w = 180, h = Math.max(1, Math.round(180 * img.naturalHeight / img.naturalWidth));
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    var x = c.getContext('2d');
    x.drawImage(img, 0, 0, w, h);
    var d, minY = h, maxY = -1, minX = w, maxX = -1;
    try { d = x.getImageData(0, 0, w, h).data; }
    catch (e) { return { l: 0.02, t: 0.02, r: 0.98, b: 0.98 }; }
    for (var y = 0; y < h; y++) {
      for (var X = 0; X < w; X++) {
        if (d[(y * w + X) * 4 + 3] > 16) {
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
          if (X < minX) minX = X;
          if (X > maxX) maxX = X;
        }
      }
    }
    if (maxY <= minY) return { l: 0.02, t: 0.02, r: 0.98, b: 0.98 };
    return { l: minX / w, t: minY / h, r: (maxX + 1) / w, b: (maxY + 1) / h };
  }

  /* ---------------------------------------------------------- 舞台 */
  function setPhoto(url, w, h, source, id) {
    S.photo = { url: url, w: w, h: h, source: source, id: id || null };
    $('baseImg').src = url;
    $('stageEmpty').hidden = true;
    $('stageInner').hidden = false;
    $('composedImg').classList.remove('on');
    $('composedImg').removeAttribute('src');
    S.lastComposeUrl = null;
    $('rCompose').textContent = '本地预览';
    layout();
  }

  function layout() {
    if (!S.photo) return;
    var inner = $('stageInner');
    var stage = $('stage');
    var availW = Math.max(0, stage.clientWidth - 20);
    var availH = Math.max(0, stage.clientHeight - 20);
    var r = (availW && availH)
      ? Math.min(availW / S.photo.w, availH / S.photo.h)
      : (inner.clientWidth / S.photo.w);
    inner.style.width = Math.round(S.photo.w * r) + 'px';
    inner.style.height = Math.round(S.photo.h * r) + 'px';
    S.scale = r;
    renderAll();
  }

  function photoToStage(x, y) { return { x: x * S.scale, y: y * S.scale }; }

  function anchorReady() { return !!(S.anchor && S.anchor.pxPerCm > 0); }

  function groundSpan() {
    var g = S.anchor;
    if (!g) return { min: 0, max: S.photo ? S.photo.w : 1000 };
    return { min: Math.min(g.g1.x, g.g2.x), max: Math.max(g.g1.x, g.g2.x) };
  }

  function renderAll() { renderGuides(); renderLayers(); updateReadout(); }

  function renderGuides() {
    var svg = $('guides');
    if (!S.photo) { svg.innerHTML = ''; return; }
    var W = S.photo.w, H = S.photo.h;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    var parts = [];
    if (S.anchor) {
      var g = S.anchor;
      parts.push('<line x1="' + g.g1.x + '" y1="' + g.g1.y + '" x2="' + g.g2.x + '" y2="' + g.g2.y +
        '" stroke="rgba(29,158,117,.95)" stroke-width="2" stroke-dasharray="10 7" vector-effect="non-scaling-stroke"/>');
      [g.g1, g.g2].forEach(function (p) {
        parts.push('<circle cx="' + p.x + '" cy="' + p.y + '" r="4" fill="#fff" stroke="#0F6E56" stroke-width="2" vector-effect="non-scaling-stroke"/>');
      });
      if (g.r1 && g.r2) {
        parts.push('<line x1="' + g.r1.x + '" y1="' + g.r1.y + '" x2="' + g.r2.x + '" y2="' + g.r2.y +
          '" stroke="rgba(24,95,165,.85)" stroke-width="2" vector-effect="non-scaling-stroke"/>');
        parts.push('<circle cx="' + g.r1.x + '" cy="' + g.r1.y + '" r="3.5" fill="#fff" stroke="#185FA5" stroke-width="2" vector-effect="non-scaling-stroke"/>');
        parts.push('<circle cx="' + g.r2.x + '" cy="' + g.r2.y + '" r="3.5" fill="#fff" stroke="#185FA5" stroke-width="2" vector-effect="non-scaling-stroke"/>');
      }
    }
    if (S.temp.length) {
      S.temp.forEach(function (p) {
        parts.push('<circle cx="' + p.x + '" cy="' + p.y + '" r="5" fill="rgba(29,158,117,.8)"/>');
      });
    }
    svg.innerHTML = parts.join('');
  }

  function baseYOf(it) {
    return (it.baseY == null) ? S.anchor.groundY : it.baseY;
  }
  function hasFloating() {
    return S.plants.some(function (it) { return it.baseY != null; });
  }

  function plantGeom(it) {
    var p = byId(it.plantId);
    var pxH = it.heightCm * S.anchor.pxPerCm;
    var rec = IMGCACHE[p.id];
    var bb = (rec && rec.bb) || { l: 0.02, t: 0.02, r: 0.98, b: 0.98 };
    var ar = (rec && rec.ready) ? (rec.img.naturalWidth / rec.img.naturalHeight) : 0.7;
    var fh = Math.max(0.25, bb.b - bb.t), fw = Math.max(0.1, bb.r - bb.l);
    var imgH = pxH / fh;
    var imgW = imgH * ar;
    return {
      imgH: imgH, imgW: imgW, bb: bb,
      left: it.x - (bb.l * imgW + fw * imgW / 2),
      top: baseYOf(it) - bb.b * imgH,
      baseY: baseYOf(it),
      contentW: fw * imgW
    };
  }

  function renderLayers() {
    var box = $('layers');
    if (!S.photo || !anchorReady()) { box.innerHTML = ''; return; }
    var html = '';
    var sorted = S.plants.slice().sort(function (a, b) { return b.layer - a.layer; });
    sorted.forEach(function (it) {
      var p = byId(it.plantId);
      if (!p) return;
      var g = plantGeom(it);
      var rec = IMGCACHE[p.id];
      if (!rec || !rec.ready) { getImg(p, function () { renderLayers(); }); }
      var src = p.image;
      var lift = S.anchor.groundY - g.baseY;
      var shW = g.contentW * 1.15 * S.scale;
      var shA = Math.max(0.10, 0.30 - lift / Math.max(1, S.photo.h) * 1.4);
      var shY = (g.baseY + 2) * S.scale;
      html += '<div class="plant-shadow" style="left:' + (it.x * S.scale - shW / 2) + 'px;top:' + shY +
        'px;width:' + shW + 'px;opacity:' + shA.toFixed(2) + '"></div>' +
        '<div class="plant-layer' + (S.selected === it.uid ? ' sel' : '') + '" data-uid="' + it.uid + '"' +
        ' style="left:' + (g.left * S.scale) + 'px;top:' + (g.top * S.scale) + 'px;' +
        'width:' + (g.imgW * S.scale) + 'px;height:' + (g.imgH * S.scale) + 'px">' +
        '<img src="' + esc(src) + '" alt="' + esc(p.name) + '" style="width:100%;height:100%"></div>';
    });
    box.innerHTML = html;
  }

  function updateReadout() {
    $('rScale').textContent = anchorReady() ? (fmt(S.anchor.pxPerCm, 2) + ' px/cm') : '未锚定';
    $('rScale').className = anchorReady() ? '' : 'warn';
    $('rGround').textContent = S.anchor ? fmt(S.anchor.groundY, 0) + ' px' : '—';
    $('rPlants').textContent = S.plants.length + ' / ' + CFG.maxPlants;
    renderLayersPanel();
  }

  /* ---------------------------------------------------------- 照片与校验 */
  var DEMO_ROOM = '../assets/cases/nordic_living_01.jpg';

  function uploadFile(file) {
    var url = URL.createObjectURL(file);
    return new Promise(function (resolve) {
      var done = function () { resolve(true); };
      var probe = new Image();
      probe.onload = function () {
        setPhoto(url, probe.naturalWidth, probe.naturalHeight, 'upload', null);
        localChecks(probe);
        if (!S.online) { toast('照片已载入（离线模式：本地预览）'); done(); return; }
        loading(true, '上传并校验照片…');
        var fd = new FormData();
        fd.append('photo', file, file.name || 'room.jpg');
        req('/api/upload', { body: fd }).then(function (d) {
          S.photo.id = d.photo_id;
          S.photo.w = d.width; S.photo.h = d.height;
          renderChecks(d.checks, d.usable, d.suggestion);
          if (!d.usable) toast('照片可用性偏低，可继续，或改用立面模式', 3200);
          else toast('照片已就绪，下一步：画落地线');
        }).catch(function (e) {
          toast('上传失败：' + e.message, 3600);
        }).then(function () { loading(false); done(); });
      };
      probe.onerror = function () { toast('这张图打不开，换一张试试'); resolve(false); };
      probe.src = url;
    });
  }

  function localChecks(img) {
    var items = [];
    var long = Math.max(img.width, img.height);
    items.push({ name: 'resolution', pass: long >= 1200, message: '长边 ' + long + 'px ' + (long >= 1200 ? '≥' : '<') + ' 1200px' });
    var c = document.createElement('canvas'); c.width = 64; c.height = 64;
    var x = c.getContext('2d'); x.drawImage(img, 0, 0, 64, 64);
    var d = x.getImageData(0, 0, 64, 64).data;
    var sum = 0, sum2 = 0, n = 0;
    for (var i = 0; i < d.length; i += 4) {
      var l = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      sum += l; sum2 += l * l; n++;
    }
    var mean = sum / n, sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
    items.push({ name: 'brightness', pass: mean >= 55 && mean <= 205, message: '平均亮度 ' + Math.round(mean) + '/255' });
    items.push({ name: 'blur', pass: sd >= 16, message: '对比度 ' + Math.round(sd) + '（离线粗测）' });
    renderChecks(items, items.every(function (i) { return i.pass; }), '');
  }

  function renderChecks(checks, usable, suggestion) {
    if (!checks) { $('checks').innerHTML = ''; return; }
    var html = checks.map(function (c) {
      return '<li><span class="dot ' + (c.pass ? 'ok' : 'bad') + '"></span><span>' + esc(c.message) + '</span></li>';
    }).join('');
    if (suggestion) html += '<li><span class="dot warn"></span><span>' + esc(suggestion) + '</span></li>';
    $('checks').innerHTML = html;
    if (usable === false) {
      $('anchorNote').textContent = '照片未通过校验：可继续手动锚定，或改用立面模式。';
      $('anchorNote').className = 'note warn';
    }
  }

  /* ---------------------------------------------------------- 锚定 */
  function setMode(m, note) {
    S.mode = m; S.temp = [];
    $('stage').style.cursor = m === 'idle' ? 'default' : 'crosshair';
    if (note) { $('anchorNote').textContent = note; $('anchorNote').className = 'note'; }
  }

  function stagePoint(e) {
    var r = $('stageInner').getBoundingClientRect();
    return {
      x: clamp((e.clientX - r.left) / r.width * S.photo.w, 0, S.photo.w),
      y: clamp((e.clientY - r.top) / r.height * S.photo.h, 0, S.photo.h)
    };
  }

  function finishAnchor() {
    var a = S.anchor;
    var len = Math.hypot(a.r1.x - a.r2.x, a.r1.y - a.r2.y);
    a.pxPerCm = len / a.refCm;
    a.groundY = (a.g1.y + a.g2.y) / 2;
    var deg = Math.atan2(a.g2.y - a.g1.y, a.g2.x - a.g1.x) * 180 / Math.PI;
    a.angle = deg;
    if (a.pxPerCm < 0.5 || a.pxPerCm > 40) {
      $('anchorNote').textContent = '锚定结果 ' + fmt(a.pxPerCm, 2) + ' px/cm 偏出合理范围，参照物可能点错了。';
      $('anchorNote').className = 'note bad';
    } else {
      $('anchorNote').textContent = '已锚定：1 cm ≈ ' + fmt(a.pxPerCm, 2) + ' px（参照 ' + a.refCm + 'cm，' +
        (Math.abs(deg) > 3 ? '落地线倾斜 ' + fmt(deg, 1) + '°，按平均高度落地' : '落地线水平') + '）';
      $('anchorNote').className = 'note';
    }
    setMode('idle');
    renderAll();
    if (S.online && S.photo.id) {
      req('/api/anchor', {
        json: {
          photo_id: S.photo.id,
          ground: [{ x: a.g1.x, y: a.g1.y }, { x: a.g2.x, y: a.g2.y }],
          ref: [{ x: a.r1.x, y: a.r1.y }, { x: a.r2.x, y: a.r2.y }],
          ref_type: a.refType, custom_height_cm: a.refCm
        }
      }).then(function (d) {
        S.anchor.pxPerCm = d.px_per_cm;
        S.anchor.groundY = d.ground_y;
        renderAll();
        toast('服务端锚定通过：' + fmt(d.px_per_cm, 2) + ' px/cm');
      }).catch(function (e) {
        $('anchorNote').textContent = '服务端校验未通过：' + e.message;
        $('anchorNote').className = 'note bad';
      });
    }
  }

  $('stage').addEventListener('pointerdown', function (e) {
    if (!S.photo) return;
    if (S.mode === 'ground' || S.mode === 'ref') {
      var p = stagePoint(e);
      S.temp.push(p);
      if (S.temp.length === 1) {
        $('anchorNote').textContent = S.mode === 'ground' ? '再点一下落地线的另一端' : '再点一下参照物的另一端';
        renderGuides();
        return;
      }
      var a = S.temp[0], b = S.temp[1];
      if (Math.hypot(a.x - b.x, a.y - b.y) < 12) { toast('两点太近，重新点'); S.temp = []; renderGuides(); return; }
      if (S.mode === 'ground') {
        S.anchor = S.anchor || {};
        S.anchor.g1 = a; S.anchor.g2 = b;
        if (S.anchor.pxPerCm) finishAnchor(); else { setMode('idle'); renderAll(); }
      } else {
        S.anchor = S.anchor || {};
        S.anchor.r1 = a; S.anchor.r2 = b;
        var sel = $('selRef').value;
        S.anchor.refType = sel;
        S.anchor.refCm = sel === 'custom' ? (parseFloat($('inRef').value) || 100) :
          (sel === 'door' ? 200 : sel === 'bed' ? 50 : 80);
        if (!S.anchor.g1) {
          S.anchor.g1 = { x: S.photo.w * 0.1, y: S.photo.h * 0.8 };
          S.anchor.g2 = { x: S.photo.w * 0.9, y: S.photo.h * 0.8 };
        }
        finishAnchor();
      }
      return;
    }

    var pl = e.target.closest ? e.target.closest('.plant-layer') : null;
    if (pl) {
      var uid = parseInt(pl.getAttribute('data-uid'), 10);
      var target = findPlant(uid);
      if (!target) return;
      S.selected = uid;
      S.drag = {
        uid: uid, el: pl,
        sx: e.clientX, sy: e.clientY,
        startX: target.x, startBase: baseYOf(target)
      };
      // 进入编辑态：把图层显形、把服务端成图收起，拖动才有即时反馈
      $('layers').classList.remove('hide');
      $('composedImg').classList.remove('on');
      pl.classList.add('dragging');
      try { pl.setPointerCapture(e.pointerId); } catch (err) { }
      renderLayersPanel();
      if (!S.dragHintShown) {
        S.dragHintShown = true;
        toast('拖动可上下左右摆放；靠近地面会自动吸附回地面', 3200);
      }
      return;
    }
    S.selected = null;
    renderLayersPanel();
    renderLayers();
  });

  $('stage').addEventListener('pointermove', function (e) {
    if (!S.drag || !S.photo) return;
    var d = S.drag, it = findPlant(d.uid);
    if (!it) return;
    var dx = e.clientX - d.sx, dy = e.clientY - d.sy;
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;

    var span = groundSpan();
    it.x = clamp(d.startX + dx / S.scale, span.min, span.max);

    var wantBase = d.startBase + dy / S.scale;
    var gy = S.anchor.groundY;
    // 靠近地面 8px 以内吸附，避免"差一点点没贴地"
    if (Math.abs(wantBase - gy) <= 8) it.baseY = null;
    else it.baseY = clamp(wantBase, S.photo.h * 0.02, S.photo.h * 0.995);

    var liftCm = (gy - baseYOf(it)) / S.anchor.pxPerCm;
    dragBadge(it.baseY == null ? '贴地' : ('离地 ' + Math.round(liftCm) + ' cm'));

    var g = plantGeom(it);
    d.el.style.left = (g.left * S.scale) + 'px';
    d.el.style.top = (g.top * S.scale) + 'px';
    var sh = d.el.previousElementSibling;
    if (sh && sh.className === 'plant-shadow') {
      var shW = g.contentW * 1.15 * S.scale;
      sh.style.left = (it.x * S.scale - shW / 2) + 'px';
      sh.style.top = ((g.baseY + 2) * S.scale) + 'px';
      sh.style.width = shW + 'px';
      sh.style.opacity = Math.max(0.10, 0.30 - (gy - g.baseY) / Math.max(1, S.photo.h) * 1.4).toFixed(2);
    }
  });

  function dragBadge(text) {
    var el = $('dragBadge');
    if (!el) return;
    if (!text) { el.classList.remove('on'); return; }
    el.textContent = text;
    el.classList.add('on');
  }

  $('stage').addEventListener('pointerup', function () {
    if (!S.drag) return;
    S.drag.el.classList.remove('dragging');
    S.drag = null;
    dragBadge('');
    renderLayersPanel();
    updateReadout();
    renderLayers();
    scheduleCompose();
    setTimeout(doScore, 60);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && S.mode !== 'idle') { setMode('idle'); toast('已取消'); }
  });

  function findPlant(uid) {
    for (var i = 0; i < S.plants.length; i++) if (S.plants[i].uid === uid) return S.plants[i];
    return null;
  }

  /* ---------------------------------------------------------- 植物与图层 */
  function addPlant(p, x, cm) {
    if (!p.available) { toast('「' + p.name + '」暂无去底素材，仅参考'); return null; }
    if (S.plants.length >= CFG.maxPlants) { toast('最多 ' + CFG.maxPlants + ' 株'); return null; }
    var span = groundSpan();
    var it = {
      uid: ++S.uid, plantId: p.id,
      x: clamp(x == null ? (span.min + span.max) / 2 : x, span.min + 2, span.max - 2),
      heightCm: cm || median(p),
      layer: 0
    };
    S.plants.push(it);
    S.selected = it.uid;
    getImg(p, function () { renderAll(); scheduleCompose(); });
    renderAll();
    scheduleCompose();
    return it;
  }

  function renderPalette() {
    var q = ($('search').value || '').trim().toLowerCase();
    var active = Array.prototype.map.call(document.querySelectorAll('#chipWrap .chip.on'), function (c) {
      return c.getAttribute('data-chip');
    });
    var onlyPhoto = active.indexOf('photo') >= 0;
    var html = '', shown = 0;
    S.catalog.forEach(function (p) {
      if (active.indexOf('available') >= 0 && !p.available) return;
      if (onlyPhoto && p.kind === 'illustration') return;
      var hitTag = true;
      active.forEach(function (t) {
        if (t === 'available' || t === 'photo') return;
        if ((p.tags || []).indexOf(t) < 0) hitTag = false;
      });
      if (!hitTag) return;
      if (q) {
        var hay = (p.name + ' ' + p.latin + ' ' + (p.tags || []).join(' ') + ' ' + (p.styles || []).join(' ')).toLowerCase();
        if (hay.indexOf(q) < 0) return;
      }
      shown++;
      var img = p.thumb
        ? '<img src="' + esc(p.thumb) + '" alt="" loading="lazy">'
        : '<div style="width:30px;height:36px;border-radius:5px;background:var(--line2)"></div>';
      html += '<div class="plant' + (p.available ? '' : ' off') + '" data-id="' + p.id + '">' + img +
        '<div class="m"><b>' + esc(p.name) + '</b><i>' + p.hMin + '–' + p.hMax + 'cm · ' +
        esc((p.tags || []).slice(0, 2).join(' / ')) + (p.available ? '' : ' · 仅参考') +
        (p.kind === 'illustration' ? '<em class="tagillu">插画</em>' : '') + '</i></div>' +
        '<div class="plus">' + (p.available ? '+' : '—') + '</div></div>';
    });
    $('plants').innerHTML = html || '<div class="note">没有匹配的植物</div>';
  }

  $('plants').addEventListener('click', function (e) {
    var row = e.target.closest('.plant');
    if (!row) return;
    var p = byId(row.getAttribute('data-id'));
    if (!p) return;
    if (!S.photo) { toast('先上传照片或用示例房间'); return; }
    if (!anchorReady()) { toast('先画落地线并标定高度'); return; }
    addPlant(p);
  });

  $('search').addEventListener('input', renderPalette);
  $('chipWrap').addEventListener('click', function (e) {
    var c = e.target.closest('.chip');
    if (!c) return;
    c.classList.toggle('on');
    renderPalette();
  });

  function renderLayersPanel() {
    var box = $('layerList');
    if (!S.plants.length) {
      box.innerHTML = '<div class="note">还没有植物。左侧面板点「+」加入。</div>';
      $('heightBox').hidden = true;
      return;
    }
    var ordered = S.plants.slice().sort(function (a, b) { return a.layer - b.layer; });
    var html = '';
    ordered.forEach(function (it) {
      var p = byId(it.plantId);
      html += '<li data-uid="' + it.uid + '">' +
        '<span class="nm" style="' + (S.selected === it.uid ? 'color:#0F6E56' : '') + '">' +
        esc(p ? p.name : it.plantId) + ' · ' + it.heightCm + 'cm' +
        (p && p.kind === 'illustration' ? ' <em class="tagillu">插画</em>' : '') +
        (it.baseY != null ? ' <em class="tagillu" style="background:#E6F1FB;color:#185FA5">离地 ' +
          Math.round((S.anchor.groundY - it.baseY) / S.anchor.pxPerCm) + 'cm</em>' : '') + '</span>' +
        '<button class="mini" data-act="front" title="置前">↑</button>' +
        '<button class="mini" data-act="back" title="置后">↓</button>' +
        '<button class="mini" data-act="del" title="移除">×</button></li>';
    });
    box.innerHTML = html;

    var sel = findPlant(S.selected);
    if (sel) {
      var p2 = byId(sel.plantId);
      $('heightBox').hidden = false;
      $('hName').textContent = (p2 ? p2.name : sel.plantId) + '（' + p2.hMin + '–' + p2.hMax + 'cm）';
      $('hVal').textContent = sel.heightCm + ' cm';
      var r = $('hRange');
      r.min = p2.hMin; r.max = p2.hMax; r.value = sel.heightCm;
    } else {
      $('heightBox').hidden = true;
    }
  }

  $('layerList').addEventListener('click', function (e) {
    var li = e.target.closest('li');
    if (!li) return;
    var uid = parseInt(li.getAttribute('data-uid'), 10);
    var it = findPlant(uid);
    if (!it) return;
    var btn = e.target.closest('button');
    if (!btn) { S.selected = uid; renderLayersPanel(); renderLayers(); return; }
    var act = btn.getAttribute('data-act');
    if (act === 'del') {
      S.plants = S.plants.filter(function (p) { return p.uid !== uid; });
      if (S.selected === uid) S.selected = null;
    } else if (act === 'front') {
      it.layer = Math.max(0, it.layer - 1);
    } else if (act === 'back') {
      it.layer = it.layer + 1;
    }
    renderAll();
    scheduleCompose();
  });

  $('hRange').addEventListener('input', function () {
    var it = findPlant(S.selected);
    if (!it) return;
    it.heightCm = parseInt(this.value, 10);
    $('hVal').textContent = it.heightCm + ' cm';
    renderLayers();
    updateReadout();
  });
  $('hRange').addEventListener('change', function () { scheduleCompose(); });

  /* ---------------------------------------------------------- 合成 */
  var composeTimer = null;
  function scheduleCompose() {
    clearTimeout(composeTimer);
    composeTimer = setTimeout(doCompose, 420);
  }

  function doCompose() {
    if (!S.photo || !anchorReady() || !S.plants.length) {
      $('composedImg').classList.remove('on');
      $('layers').classList.remove('hide');
      $('rCompose').textContent = '本地预览';
      return;
    }
    if (hasFloating()) {
      $('composedImg').classList.remove('on');
      $('layers').classList.remove('hide');
      $('rCompose').textContent = '本地合成（含离地）';
      return;
    }
    if (!S.online || !S.photo.id) { $('rCompose').textContent = '本地预览'; return; }

    S.composing = true;
    req('/api/compose', {
      json: {
        photo_id: S.photo.id,
        anchor: { px_per_cm: S.anchor.pxPerCm, ground_y: S.anchor.groundY },
        items: S.plants.map(function (it) {
          return { plant_id: it.plantId, x: Math.round(it.x), height_cm: it.heightCm, layer: it.layer };
        }),
        watermark: true
      }
    }).then(function (d) {
      S.lastComposeUrl = apiUrl(d.image_url);
      var im = new Image();
      im.onload = function () {
        $('composedImg').src = S.lastComposeUrl;
        $('composedImg').classList.add('on');
        $('layers').classList.add('hide');
      };
      im.src = S.lastComposeUrl;
      $('rCompose').textContent = Math.round(d.elapsed_ms) + ' ms';
      if (d.warnings && d.warnings.length) toast(d.warnings[0], 3000);
    }).catch(function (e) {
      $('rCompose').textContent = '回退本地预览';
      $('composedImg').classList.remove('on');
      $('layers').classList.remove('hide');
      toast('合成失败：' + e.message, 3600);
    }).then(function () { S.composing = false; });
  }

  /* ---------------------------------------------------------- 评分 */
  var scoreTimer = null;
  function scheduleScore() {
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(doScore, 300);
  }

  function scenePayload() {
    return {
      room: $('selRoom').value,
      style: $('selStyle').value,
      light: parseInt($('selLight').value, 10),
      weekly_minutes: parseInt($('selWeekly').value, 10),
      has_pet: $('chkPet').checked,
      budget: parseFloat($('selBudget').value)
    };
  }

  function ids() {
    var out = [];
    S.plants.forEach(function (p) { if (out.indexOf(p.plantId) < 0) out.push(p.plantId); });
    return out;
  }

  function doScore() {
    if (!S.plants.length) { renderScore(null); return; }
    if (!S.online) { renderScore(null); return; }
    req('/api/score', { json: { plant_ids: ids(), scene: scenePayload() } })
      .then(function (d) { renderScore(d); })
      .catch(function () { renderScore(null); });
  }

  function renderScore(d) {
    if (!d) {
      $('sTotal').textContent = '—';
      $('sAesthetic').textContent = '—';
      $('sFit').textContent = '—';
      $('dimsWrap').innerHTML = '';
      $('flagWrap').hidden = true;
      if (S.plants.length) {
        $('dimsWrap').innerHTML = '<span class="note" style="margin:0">离线演示：七维评分需连接后端</span>';
      }
      return;
    }
    S.score = d;
    $('sTotal').textContent = fmt(d.total, 1);
    $('sAesthetic').textContent = fmt(d.aesthetic, 1);
    $('sFit').textContent = fmt(d.fit, 1);
    $('dimsWrap').innerHTML = (d.dimensions || []).map(function (x) {
      return '<div class="dim" title="' + esc(x.detail) + '"><div class="t"><span>' + esc(x.name) +
        '</span><span>' + fmt(x.score, 0) + '</span></div><div class="bar"><i style="width:' +
        clamp(x.score, 0, 100) + '%"></i></div></div>';
    }).join('');
    if (d.hard_flags && d.hard_flags.length) {
      $('flagWrap').hidden = false;
      $('flagWrap').textContent = d.hard_flags.join('　');
    } else {
      $('flagWrap').hidden = true;
    }
    renderReasons(d.reasons);
  }

  function renderReasons(reasons) {
    var el = $('reasonsWrap');
    if (!el) return;
    if (!reasons || !reasons.length) { el.innerHTML = ''; el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = '<h3>为什么这样搭 <em>可解释</em></h3><ol style="margin:0;padding-left:18px;font-size:11.5px;color:var(--ink2);line-height:1.75">' +
      reasons.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ol>';
  }

  /* ---------------------------------------------------------- 推荐 */
  function renderRecNote() {
    $('recNote').textContent = S.online
      ? '按顶栏的场景 / 风格 / 光照 / 预算生成三套性格不同的方案（稳妥 / 对比 / 个性）。'
      : '离线演示：推荐需要后端 /api/recommend。启动 python app.py 后加 ?api= 参数即可。';
  }

  $('btnRecommend').addEventListener('click', function () {
    if (!S.online) { toast('推荐需要后端：启动 python app.py 后刷新并加 ?api='); return; }
    loading(true, '生成方案…');
    req('/api/recommend', { json: { scene: scenePayload() } }).then(function (d) {
      renderPlans(d.plans || []);
      if (!d.plans || !d.plans.length) toast('没有可推荐的方案，试试放宽预算或光照');
    }).catch(function (e) {
      toast('推荐失败：' + e.message, 3600);
    }).then(function () { loading(false); });
  });

  function renderPlans(plans) {
    if (!plans.length) { $('plansWrap').innerHTML = ''; return; }
    $('plansWrap').innerHTML = plans.map(function (p, i) {
      return '<div class="plan" data-i="' + i + '">' +
        '<div class="hd"><b>' + esc(p.personality) + '</b><span>' + fmt(p.score && p.score.total, 1) + ' 分</span></div>' +
        '<div class="ds">' + esc(p.desc || '') + '</div>' +
        '<div class="nm">' + esc(p.names || (p.plant_ids || []).join('、')) + '</div>' +
        '<div class="meta"><span>¥' + fmt(p.total_price, 0) + '</span><span>每周 ' + (p.care_min_week || 0) + ' 分钟</span>' +
        '<span>' + (p.plant_ids || []).length + ' 株</span>' +
        (illuCount(p.plant_ids) ? '<span style="color:#854F0B">含 ' + illuCount(p.plant_ids) + ' 插画</span>' : '') + '</div>' +
        '<div class="acts"><button class="primary mini" data-apply="' + i + '">放到照片里</button>' +
        '<button class="mini" data-self="' + i + '">在自选里调</button></div></div>';
    }).join('');
    $('plansWrap')._plans = plans;
  }

  $('plansWrap').addEventListener('click', function (e) {
    var plans = $('plansWrap')._plans || [];
    var ap = e.target.closest('[data-apply]');
    var sf = e.target.closest('[data-self]');
    var idx = ap ? +ap.getAttribute('data-apply') : (sf ? +sf.getAttribute('data-self') : -1);
    if (idx < 0 || !plans[idx]) return;
    applyPlan(plans[idx]);
    if (sf) { switchTab('self'); }
  });

  function applyPlan(plan) {
    if (!S.photo) { toast('先上传照片或用示例房间'); return; }
    if (!anchorReady()) { toast('先画落地线并标定高度'); return; }
    S.plants = [];
    S.uid = S.plants.length;
    var list = plan.plant_ids || [];
    list.forEach(function (pid, i) {
      var p = byId(pid);
      if (!p || !p.available) return;
      var span = groundSpan();
      var t = (i + 1) / (list.length + 1);
      addPlant(p, span.min + (span.max - span.min) * t);
    });
    renderAll();
    doScore();
    toast('已套用「' + (plan.personality || '方案') + '」');
  }

  /* ---------------------------------------------------------- 改稿 */
  $('reviseChips').addEventListener('click', function (e) {
    var c = e.target.closest('.chip');
    if (!c) return;
    revise(c.getAttribute('data-act'));
  });
  $('btnRevise').addEventListener('click', function () {
    var t = ($('inRevise').value || '').trim();
    if (!t) { toast('说一句想怎么改'); return; }
    revise(t);
  });

  function revise(instruction) {
    if (!S.plants.length) { toast('先放几株植物'); return; }
    if (!S.online) { toast('改稿需要后端 /api/revise'); return; }
    loading(true, '改稿中…');
    req('/api/revise', { json: { plant_ids: ids(), scene: scenePayload(), instruction: instruction } })
      .then(function (d) {
        var out = $('reviseOut');
        out.classList.add('on');
        var diff = d.diff || {};
        var after = d.after || {};
        out.innerHTML = '「' + esc(instruction) + '」→ <span class="diff">' +
          esc(after.names || (after.plant_ids || []).join('、')) + '</span>' +
          '（保留 ' + Math.round((diff.keep_ratio || 0) * 100) + '%，总分 ' +
          fmt(d.before && d.before.total, 1) + ' → ' + fmt(after.total, 1) + '）' +
          '<div class="row" style="margin-top:6px"><button class="mini" id="btnApplyRevise">套用</button></div>';
        $('btnApplyRevise').onclick = function () {
          S.plants = [];
          var list = after.plant_ids || [];
          list.forEach(function (pid, i) {
            var p = byId(pid);
            if (!p || !p.available) return;
            var span = groundSpan();
            var t = (i + 1) / (list.length + 1);
            addPlant(p, span.min + (span.max - span.min) * t);
          });
          renderAll(); doScore();
          toast('已套用改稿');
        };
      })
      .catch(function (e) { toast('改稿失败：' + e.message, 3600); })
      .then(function () { loading(false); });
  }

  /* ---------------------------------------------------------- 案例 */
  function loadCases() {
    fetch(CFG.dataRoot + 'cases_manifest.csv').then(function (r) { return r.text(); }).then(function (txt) {
      var rows = parseCSV(txt), head = rows.shift() || [];
      CASES = rows.filter(function (r) { return r.length && r[0]; }).map(function (r) {
        var o = {};
        head.forEach(function (h, i) { o[h] = r[i]; });
        return o;
      });
      renderCases();
    }).catch(function () {
      $('caseNote').textContent = '案例清单读取失败（需要用 http 打开页面，而不是双击文件）。';
    });
  }

  function renderCases() {
    var room = $('caseRoom').value, style = $('caseStyle').value;
    var list = CASES.filter(function (c) {
      return (!room || c.room === room) && (!style || c.style === style);
    });
    $('caseCount').textContent = '共 ' + list.length + ' 张';
    $('caseGrid').innerHTML = list.slice(0, 24).map(function (c) {
      return '<div class="case" title="' + esc(c.source_url || '') + '"><img src="' + esc(CFG.assetRoot + c.file_path) +
        '" alt="" loading="lazy"><span>' + esc(c.room) + ' · ' + esc(c.style) + '</span></div>';
    }).join('') || '<div class="note">没有匹配的案例</div>';
  }
  $('caseRoom').addEventListener('change', renderCases);
  $('caseStyle').addEventListener('change', renderCases);

  /* ---------------------------------------------------------- 导出 */
  $('btnExportPng').addEventListener('click', function () {
    if (!S.photo || !S.plants.length) { toast('先放植物'); return; }
    if (hasFloating()) { exportLocal(); return; }
    if (S.online && S.photo.id) {
      loading(true, '生成效果图…');
      req('/api/compose', {
        json: {
          photo_id: S.photo.id,
          anchor: { px_per_cm: S.anchor.pxPerCm, ground_y: S.anchor.groundY },
          items: S.plants.map(function (it) {
            return { plant_id: it.plantId, x: Math.round(it.x), height_cm: it.heightCm, layer: it.layer };
          }),
          watermark: true
        }
      }).then(function (d) {
        return fetch(apiUrl(d.image_url)).then(function (r) { return r.blob(); }).then(function (b) {
          saveBlob(b, 'verda-' + Date.now() + '.png');
          toast('已导出 ' + d.width + '×' + d.height + ' 效果图');
        });
      }).catch(function (e) { toast('导出失败：' + e.message, 3600); })
        .then(function () { loading(false); });
      return;
    }
    exportLocal();
  });

  function exportLocal() {
    var W = S.photo.w, H = S.photo.h;
    var scale = Math.max(1, 1600 / Math.max(W, H));
    var c = document.createElement('canvas');
    c.width = Math.round(W * scale); c.height = Math.round(H * scale);
    var x = c.getContext('2d');
    var base = new Image();
    base.onload = function () {
      x.drawImage(base, 0, 0, c.width, c.height);
      var sorted = S.plants.slice().sort(function (a, b) { return b.layer - a.layer; });
      sorted.forEach(function (it) {
        var p = byId(it.plantId), rec = IMGCACHE[p.id];
        if (!rec || !rec.ready) return;
        var g = plantGeom(it);
        var lift = S.anchor.groundY - g.baseY;
        var shW = g.contentW * 1.15 * scale;
        var alpha = Math.max(0.10, 0.30 - lift / Math.max(1, H) * 1.4);
        x.save();
        x.globalAlpha = alpha;
        x.fillStyle = '#000';
        x.beginPath();
        x.ellipse(it.x * scale, (g.baseY + 2) * scale, shW / 2, Math.max(2, shW * 0.055), 0, 0, Math.PI * 2);
        x.filter = 'blur(6px)';
        x.fill();
        x.restore();
        x.drawImage(rec.img, g.left * scale, g.top * scale, g.imgW * scale, g.imgH * scale);
      });
      x.fillStyle = 'rgba(29,42,34,.55)';
      x.fillRect(c.width - 96, c.height - 34, 84, 24);
      x.fillStyle = '#fff';
      x.font = '14px "PingFang SC",sans-serif';
      x.textAlign = 'right';
      x.fillText('效果示意', c.width - 18, c.height - 16);
      c.toBlob(function (b) { saveBlob(b, 'verda-' + Date.now() + '.png'); toast(hasFloating() ? '已导出（前端合成，含离地摆放）' : '已导出（前端合成）'); });
    };
    base.src = S.photo.url;
  }

  $('btnExportList').addEventListener('click', function () {
    if (!S.plants.length) { toast('先放植物'); return; }
    var lines = ['# 植境 Verda · 采购清单', '',
      '> 场景：' + $('selRoom').selectedOptions[0].textContent + ' · ' + $('selStyle').selectedOptions[0].textContent +
      '　|　合成图为效果示意，非实景拍摄', '',
      '| 植物 | 学名 | 规格 | 冠幅 | 参考价 | 标签 |', '|---|---|---|---|---|---|'];
    var priceMin = 0, priceMax = 0, minutes = 0, seen = {};
    S.plants.forEach(function (it) {
      var p = byId(it.plantId);
      if (!p || seen[p.id]) return;
      seen[p.id] = 1;
      var pr = String(p.price || '').split('-');
      var a = parseInt(pr[0], 10) || 0;
      var b = pr.length > 1 ? (parseInt(pr[1], 10) || a) : a;
      priceMin += a; priceMax += b;
      lines.push('| ' + p.name + ' | ' + p.latin + ' | ' + it.heightCm + ' cm | ' + p.spread + ' cm | ¥' +
        (p.price || '—') + ' | ' + (p.tags || []).join(' / ') +
        (p.kind === 'illustration' ? '（插画示意）' : '') + ' |');
    });
    lines.push('', '合计：' + S.plants.length + ' 株，参考价 ¥' + priceMin + (priceMax !== priceMin ? '–' + priceMax : '') + '。');
    if (S.score) {
      lines.push('', '## 评分', '',
        '- 综合 ' + fmt(S.score.total) + '（审美 ' + fmt(S.score.aesthetic) + ' / 适配 ' + fmt(S.score.fit) + '）');
      (S.score.reasons || []).forEach(function (r) { lines.push('- ' + r); });
      if (S.score.hard_flags && S.score.hard_flags.length) {
        lines.push('', '> ⚠️ ' + S.score.hard_flags.join('；'));
      }
    }
    saveBlob(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }), 'verda-list-' + Date.now() + '.md');
    toast('已导出清单');
  });

  function saveBlob(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }

  /* ---------------------------------------------------------- 入口动作 */
  $('btnUpload').addEventListener('click', function () { $('file').click(); });
  $('btnUpload2').addEventListener('click', function () { $('file').click(); });
  $('file').addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0];
    if (f) uploadFile(f);
    e.target.value = '';
  });

  $('btnDemo').addEventListener('click', loadDemoRoom);
  $('btnFlat').addEventListener('click', flatMode);
  $('btnFlat2').addEventListener('click', flatMode);

  function loadDemoRoom() {
    loading(true, '载入示例房间…');
    return fetch(DEMO_ROOM).then(function (r) { return r.blob(); }).then(function (b) {
      var f = new File([b], 'demo-room.jpg', { type: b.type || 'image/jpeg' });
      return uploadFile(f).then(function () { applyDemoAnchor(); });
    }).catch(function () {
      toast('示例房间读不到：请从仓库根目录用 http 打开页面', 3600);
    }).then(function () { loading(false); });
  }

  function applyDemoAnchor() {
    if (!S.photo) return;
    var W = S.photo.w, H = S.photo.h;
    S.anchor = {
      g1: { x: W * 0.06, y: H * 0.935 }, g2: { x: W * 0.94, y: H * 0.925 },
      r1: { x: W * 0.5, y: H * 0.33 }, r2: { x: W * 0.5, y: H * 0.93 },
      refType: 'door', refCm: 200
    };
    finishAnchor();
  }

  function flatMode() {
    var W = 1400, H = 900;
    var c = document.createElement('canvas');
    c.width = W; c.height = H;
    var x = c.getContext('2d');
    x.fillStyle = '#E9EAE4'; x.fillRect(0, 0, W, H * 0.78);
    x.fillStyle = '#D8D2C4'; x.fillRect(0, H * 0.78, W, H * 0.22);
    x.fillStyle = '#C7C1AE'; x.fillRect(0, H * 0.78 - 6, W, 6);
    x.fillStyle = 'rgba(29,42,34,.06)';
    x.fillRect(W * 0.08, H * 0.30, W * 0.22, H * 0.34);
    c.toBlob(function (b) {
      uploadFile(new File([b], 'flat-room.png', { type: 'image/png' })).then(function () {
        S.anchor = {
          g1: { x: W * 0.08, y: H * 0.80 }, g2: { x: W * 0.92, y: H * 0.80 },
          r1: { x: W * 0.5, y: H * 0.20 }, r2: { x: W * 0.5, y: H * 0.80 },
          refType: 'custom', refCm: 240
        };
        finishAnchor();
        toast('立面模式：无照片也能完整演示');
      });
    }, 'image/png');
  }

  $('btnGround').addEventListener('click', function () {
    if (!S.photo) { toast('先上传照片或用示例房间'); return; }
    setMode('ground', '点两下：先点近处地面，再点远处地面');
  });
  $('btnAutoGround').addEventListener('click', function () {
    if (!S.photo) { toast('先上传照片或用示例房间'); return; }
    function applyGround(y, conf, method) {
      S.anchor = S.anchor || {};
      S.anchor.g1 = { x: 0, y: y };
      S.anchor.g2 = { x: S.photo.w, y: y };
      S.anchor.groundY = y;
      if (S.anchor.pxPerCm) finishAnchor(); else { setMode('idle'); renderAll(); }
      $('anchorNote').className = 'note';
      $('anchorNote').textContent = '自动落地线：y=' + Math.round(y) + 'px（' +
        (method === 'fallback' ? '未找到明显地面，按 82% 默认值' :
          '置信度 ' + Math.round((conf || 0) * 100) + '%') + '），可手动重画。';
      toast(conf >= 0.5 ? '已自动判断落地线' : '置信度较低，请检查落地线');
    }
    if (!S.online || !S.photo.id) {
      applyGround(S.photo.h * 0.82, 0.2, 'fallback');
      return;
    }
    loading(true, '正在判断落地线…');
    req('/api/groundline', { json: { photo_id: S.photo.id } }).then(function (d) {
      applyGround(d.ground_y, d.confidence, d.method);
    }).catch(function () {
      applyGround(S.photo.h * 0.82, 0.2, 'fallback');
    }).then(function () { loading(false); });
  });
  $('btnRef').addEventListener('click', function () {
    if (!S.photo) { toast('先上传照片或用示例房间'); return; }
    setMode('ref', '点参照物的两端（门框上下沿 / 沙发两侧）');
  });
  $('selRef').addEventListener('change', function () {
    $('inRef').hidden = this.value !== 'custom';
    if (this.value === 'custom') $('inRef').focus();
  });

  ['selRoom', 'selStyle', 'selLight', 'selWeekly', 'selBudget', 'chkPet'].forEach(function (id) {
    $(id).addEventListener('change', function () { scheduleScore(); });
  });

  /* tabs */
  function switchTab(name) {
    Array.prototype.forEach.call(document.querySelectorAll('.tabs button'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-tab') === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.pane'), function (p) {
      p.classList.toggle('on', p.id === 'pane-' + name);
    });
  }
  document.querySelector('.tabs').addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (b) switchTab(b.getAttribute('data-tab'));
  });

  /* resize */
  var rt = null;
  window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(layout, 120);
  });
  $('baseImg').addEventListener('load', function () { layout(); });

  /* boot */
  loadCatalog().then(function () {
    loadCases();
    if (CFG.demo) {
      setTimeout(function () {
        loadDemoRoom().then(function () {
          setTimeout(function () {
          var W = S.photo.w;
          [['P01', 0.60, 130], ['P04', 0.78, 70], ['P05', 0.90, 45]].forEach(function (row) {
            var p = byId(row[0]);
            if (p) addPlant(p, W * row[1], row[2]);
          });
          doScore();
          doCompose();
          switchTab('self');
          }, 500);
        });
      }, 120);
    }
  });

  /* 给对话窗口用的只读上下文 */
  window.VERDA = {
    api: function () { return CFG.api; },
    scene: scenePayload,
    plantIds: ids,
    score: function () { return S.score; },
    online: function () { return S.online; }
  };

  /* 布局：搭配工具收进左下抽屉，对话挂到右列 */
  (function restructure() {
    var side = document.querySelector('.side');
    var drawer = document.getElementById('toolDrawer');
    var panel = document.getElementById('chatPanel');
    if (!side || !drawer) return;

    ['.tabs', '.panes'].forEach(function (sel) {
      var el = side.querySelector(sel);
      if (el) drawer.appendChild(el);
    });
    Array.prototype.slice.call(side.querySelectorAll(':scope > .card'))
      .forEach(function (card) { drawer.appendChild(card); });

    if (panel) {
      panel.hidden = false;
      side.appendChild(panel);
      side.classList.add('chat-side');
    }

    var btn = document.getElementById('btnDrawer');
    if (btn) {
      btn.addEventListener('click', function () {
        drawer.hidden = !drawer.hidden;
        btn.setAttribute('aria-expanded', String(!drawer.hidden));
      });
    }
  })();
})();
