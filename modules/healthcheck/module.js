/* Сходня — модуль healthcheck.
   Индикаторы: карточки, плитки, группы (агрегат), панель проверок при наведении,
   секция проверок в редакторе, вкладка проверок в окне деталей. */
(function () {
  'use strict';
  const S = window.Svod;
  if (!S) return;

  const results = new Map();
  const nextAt = new Map();
  let timer = null;

  const keyOf = (it, i) => it.id + '|' + i;
  const checksOf = (it) => (Array.isArray(it.checks) ? it.checks : []);
  const hostOf = (it) => {
    const h = S.hostOf(it.url);
    return h.replace(/^\w+:\/\//, '').split('/')[0].split(':')[0];
  };
  const portOfUrl = (it) => {
    try { const u = new URL(it.url); return u.port || (u.protocol === 'https:' ? '443' : '80'); } catch (e) { return ''; }
  };

  function targetOf(it, c) {
    const host = hostOf(it);
    if (c.type === 'tcp') return host + ':' + (c.port || '?');
    return host;
  }
  function statusClass(r) { return !r ? 'wait' : (r.ok ? 'up' : 'down'); }
  function msText(r) { return r && r.ms != null ? Math.round(r.ms) + ' мс' : '—'; }

  function rowHTML(it, c, i, showName) {
    const r = results.get(keyOf(it, i));
    const body = showName
      ? '<span class="hc-name">' + S.esc(it.title) + '</span><span class="hc-target">' + S.esc(c.type + ' ' + targetOf(it, c)) + '</span>'
      : '<span class="hc-kind">' + S.esc(c.type) + '</span><span class="hc-target">' + S.esc(targetOf(it, c)) + '</span>';
    return '<div class="hc-item ' + statusClass(r) + '">' +
      '<span class="hc-sdot"></span>' + body +
      '<span class="hc-ms">' + msText(r) + '</span>' +
      '</div>';
  }

  function ensureTimer() {
    if (timer) return;
    timer = setInterval(tick, 1000);
  }

  function tick() {
    if (document.hidden) return;
    const page = S.state.page;
    if (!page || !page.groups) return;
    const now = Date.now();
    page.groups.forEach((g) => (g.items || []).forEach((it) => {
      checksOf(it).forEach((c, i) => {
        const interval = Math.max(1, Math.min(3600, Number(c.interval) || 5));
        const k = keyOf(it, i);
        if (now >= (nextAt.get(k) || 0)) {
          nextAt.set(k, now + interval * 1000);
          run(it, c, i);
        }
      });
    }));
  }

  async function run(it, c, i) {
    const k = keyOf(it, i);
    try {
      const r = await S.api('api/modules/healthcheck/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: c.type, url: it.url, host: c.host || '', port: c.port || 0, timeout: 2 }),
      });
      const j = await r.json();
      results.set(k, { ok: !!j.ok, ms: j.ms, code: j.code, error: j.error, ts: Date.now() });
    } catch (e) {
      results.set(k, { ok: false, error: 'нет связи с сервером', ts: Date.now() });
    }
    paint();
  }

  function paneFor(host) {
    let pane = host.querySelector('.hc-pane');
    if (!pane) {
      pane = document.createElement('div');
      pane.className = 'hc-pane';
      host.appendChild(pane);
    }
    return pane;
  }

  function statusOf(rows) {
    const rs = rows.map((r) => results.get(keyOf(r.it, r.i)));
    const known = rs.filter(Boolean);
    const allOk = known.length === rows.length && known.every((r) => r.ok);
    const anyDown = known.some((r) => !r.ok);
    return anyDown ? 'down' : allOk ? 'up' : 'wait';
  }

  function paintCards() {
    const page = S.state.page;
    page.groups.forEach((g) => (g.items || []).forEach((it) => {
      const cs = checksOf(it);
      document.querySelectorAll('.cardwrap[data-id="' + it.id + '"]').forEach((wrap) => {
        let dot = wrap.querySelector('.hc-dot');
        if (!cs.length) {
          if (dot) dot.remove();
          const old = wrap.querySelector('.hc-pane');
          if (old) old.remove();
          return;
        }
        if (!dot) {
          dot = document.createElement('span');
          dot.className = 'hc-dot';
          wrap.appendChild(dot);
        }
        const rows = cs.map((c, i) => ({ it, c, i }));
        const st = statusOf(rows);
        dot.className = 'hc-dot ' + st;
        dot.setAttribute('aria-label', 'Проверки: ' + (st === 'down' ? 'есть недоступные' : st === 'up' ? 'всё доступно' : 'ожидание'));
        const pane = paneFor(wrap);
        pane.innerHTML = '<div class="hc-ptitle">Проверки</div>' + rows.map((r) => rowHTML(r.it, r.c, r.i)).join('');
      });
    }));
  }

  function paintGroups() {
    const page = S.state.page;
    document.querySelectorAll('.gtile[data-gi]').forEach((tile) => {
      const g = page.groups[+tile.dataset.gi];
      if (!g) return;
      const rows = [];
      (g.items || []).forEach((it) => checksOf(it).forEach((c, i) => rows.push({ it, c, i })));
      let dot = tile.querySelector('.hc-dot');
      if (!rows.length) {
        if (dot) dot.remove();
        const p = tile.querySelector('.hc-pane');
        if (p) p.remove();
        return;
      }
      if (!dot) {
        dot = document.createElement('span');
        dot.className = 'hc-dot';
        tile.appendChild(dot);
      }
      const st = statusOf(rows);
      dot.className = 'hc-dot ' + st;
      dot.setAttribute('aria-label', 'Проверки группы: ' + (st === 'down' ? 'есть недоступные' : st === 'up' ? 'всё доступно' : 'ожидание'));
      const pane = paneFor(tile);
      pane.innerHTML = '<div class="hc-ptitle">Проверки</div>' + rows.map((r) => rowHTML(r.it, r.c, r.i, true)).join('');
    });
  }

  function paint() {
    const page = S.state.page;
    if (!page || !page.groups) return;
    paintCards();
    paintGroups();
  }

  document.addEventListener('mouseover', (e) => {
    const host = e.target.closest && e.target.closest('.cardwrap, .gtile');
    if (!host) return;
    const pane = host.querySelector('.hc-pane');
    if (!pane) return;
    host.classList.remove('flip');
    const r = host.getBoundingClientRect();
    if (r.right + 280 > window.innerWidth) host.classList.add('flip');
  });

  function editorSection(item) {
    const wrap = document.createElement('div');
    wrap.className = 'hc-editor';
    wrap.innerHTML =
      '<div class="hc-ehead"><span>Проверки доступности</span><span class="hc-count"></span></div>' +
      '<div class="hc-rows"></div>' +
      '<button type="button" class="hc-add">+ проверка</button>' +
      '<div class="hc-hint">Интервал — 1–3600 секунд. http/https проверяют адрес элемента, ping — хост из ссылки, tcp — порт (можно изменить).</div>';
    const rows = wrap.querySelector('.hc-rows');

    function sync(row) {
      const type = row.querySelector('.hc-type').value;
      row.classList.toggle('no-port', type !== 'tcp');
      const host = hostOf(item);
      row.querySelector('.hc-target').textContent = type === 'tcp'
        ? host + ':' + (row.querySelector('.hc-port').value || '?')
        : host;
    }

    function addRow(c) {
      const isTcp = (c.type || 'http') === 'tcp';
      const row = document.createElement('div');
      row.className = 'hc-row';
      row.innerHTML =
        '<select class="hc-type"><option value="http">http</option><option value="https">https</option>' +
        '<option value="ping">ping</option><option value="tcp">tcp</option></select>' +
        '<span class="hc-target"></span>' +
        '<input class="hc-port" type="number" min="1" max="65535" placeholder="порт" value="' +
          (c.port || (isTcp ? portOfUrl(item) : '')) + '">' +
        '<span class="hc-intwrap"><input class="hc-int" type="number" min="1" max="3600" value="' +
          (c.interval || 5) + '" title="Интервал, секунд"><span class="hc-suffix">с</span></span>' +
        '<button type="button" class="hc-del" title="Удалить проверку">✕</button>';
      row.querySelector('.hc-type').value = c.type || 'http';
      row.querySelector('.hc-type').onchange = () => sync(row);
      row.querySelector('.hc-port').oninput = () => sync(row);
      row.querySelector('.hc-del').onclick = () => { row.remove(); updateCount(); };
      rows.appendChild(row);
      sync(row);
      updateCount();
    }

    function updateCount() {
      wrap.querySelector('.hc-count').textContent = rows.children.length ? rows.children.length : '';
    }

    checksOf(item).forEach(addRow);
    wrap.querySelector('.hc-add').onclick = () => addRow({ type: 'http', interval: 5 });

    return {
      el: wrap,
      get() {
        return Array.from(rows.querySelectorAll('.hc-row')).map((row) => {
          const type = row.querySelector('.hc-type').value;
          const out = { type, interval: Math.max(1, Math.min(3600, Number(row.querySelector('.hc-int').value) || 5)) };
          if (type === 'tcp') out.port = Number(row.querySelector('.hc-port').value) || 0;
          return out;
        }).filter((c) => c.type === 'http' || c.type === 'https' || (c.type === 'tcp' && c.port));
      },
    };
  }

  function detailsSection(item) {
    const cs = checksOf(item);
    if (!cs.length) return null;
    const el = document.createElement('div');
    el.className = 'hc-details';
    el.innerHTML = '<div class="hc-dhead">Проверки</div>' + cs.map((c, i) => rowHTML(item, c, i)).join('');
    return el;
  }

  S.registerModule({
    id: 'healthcheck',
    onBoot() { ensureTimer(); },
    onRender() { paint(); },
    editorSection,
    detailsSection,
  });
})();
