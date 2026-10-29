'use strict';

(() => {
  const PX = 2;
  const ZOOM_MIN = 0.1;
  const ZOOM_MAX = 4;
  const ZOOM_START_MIN = 0.6;
  const WHEEL_SENSITIVITY = 0.0015;
  const BUTTON_ZOOM_STEP = 1.25;
  const CLUSTER_OPEN_ZOOM = 2;
  const RING = 70;
  const ARC = 40;
  const TIER_R = { mars: 4, earth: 7, jupiter: 11 };
  const PULSE_MS = 2000;
  const SESSION_REFRESH_MS = 6000;
  const FULL_REFRESH_MS = 20000;
  const FRAME_MS = 66;
  const FAN_START = Math.PI;
  const FAN_END = 2 * Math.PI;
  const SUN_ANGLE = 1.5 * Math.PI;
  const GROUP_GAP = 26;
  const BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  const LEVEL_NAMES = { full: 'Full transcript', compacted: 'Compacted (default)', extra_compacted: 'Extra-compacted' };
  const FONT = {
    A: '010101111101101', B: '110101110101110', C: '011100100100011', D: '110101101101110',
    E: '111100110100111', F: '111100110100100', G: '011100101101011', H: '101101111101101',
    I: '111010010010111', J: '001001001101010', K: '101101110101101', L: '100100100100111',
    M: '101111111101101', N: '110101101101101', O: '010101101101010', P: '110101110100100',
    Q: '010101101110011', R: '110101110101101', S: '011100010001110', T: '111010010010010',
    U: '101101101101111', V: '101101101101010', W: '101101111111101', X: '101101010101101',
    Y: '101101010010010', Z: '111001010100111', 0: '111101101101111', 1: '010110010010111',
    2: '110001010100111', 3: '110001010001110', 4: '101101111001001', 5: '111100110001110',
    6: '011100111101111', 7: '111001010010010', 8: '111101111101111', 9: '111101111001110',
    ' ': '000000000000000', '-': '000000111000000', '.': '000000000000010', _: '000000000000111',
    ':': '000010000010000', '%': '101001010100101', '/': '001001010100100', '+': '000010111010000',
    '!': '010010010000010', '?': '110001010000010', '(': '001010010010001', ')': '100010010010100',
    '#': '101111101111101', ',': '000000000010100', "'": '010010000000000', '&': '010101010101011',
    '=': '000111000111000', '>': '100010001010100', '<': '001010100010001', '*': '000101010101000',
  };
  const DEFAULT_MASTER = [
    '#000000', '#1d2b53', '#7e2553', '#008751', '#ab5236', '#5f574f', '#c2c3c7', '#fff1e8',
    '#ff004d', '#ffa300', '#ffec27', '#00e436', '#29adff', '#83769c', '#ff77a8', '#ffccaa',
  ];

  const state = {
    view: null,
    M: DEFAULT_MASTER,
    schemes: {},
    cam: { x: 0, y: 0 },
    z: 1,
    camTarget: null,
    listHover: null,
    listCollapsed: new Set(),
    listSig: '',
    expanded: new Set(),
    collapsedByUser: new Set(),
    selected: null,
    focusPlanet: null,
    layout: null,
    hits: [],
    hover: null,
    drag: null,
    dropTarget: null,
    t: 0,
    stars: [],
    sun: { data: null, files: {}, open: new Set(), projectsOpen: new Set() },
    summaries: {},
    transcripts: {},
    reviewPrompts: {},
    suggest: {},
    stats: {},
    pending: {},
    panelSig: '',
    binSig: '',
    pulse: null,
    lastView: 0,
    fitted: false,
    showLabels: true,
    animate: true,
  };

  const $ = (sel) => document.querySelector(sel);
  const canvas = $('#sky');
  const ctx = canvas.getContext('2d');

  // ---------- DOM + API helpers ----------

  function h(tag, props, ...kids) {
    const e = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') e.className = v;
        else if (k === 'style') e.style.cssText = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else if (k === 'value') e.value = v;
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const k of kids.flat(Infinity)) {
      if (k === null || k === undefined || k === false) continue;
      e.append(k instanceof Node ? k : String(k));
    }
    return e;
  }

  async function api(method, path, body) {
    const opts = { method, headers: { 'x-webtree': '1' } };
    if (body !== undefined) {
      opts.headers['content-type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(path, opts);
    let data = null;
    try {
      data = await r.json();
    } catch (e) {
      data = null;
    }
    if (!r.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : r.statusText);
    }
    return data;
  }

  const enc = encodeURIComponent;

  let toastTimer = null;
  function toast(msg, kind) {
    const t = $('#toast');
    t.textContent = msg;
    t.className = kind === 'info' ? 'info' : '';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add('hidden'), kind === 'info' ? 2500 : 6000);
  }

  async function act(fn, okMsg) {
    try {
      const result = await fn();
      if (okMsg) toast(okMsg, 'info');
      await refresh(true);
      return result;
    } catch (e) {
      toast(e.message || String(e));
      await refresh(true);
      return undefined;
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied to clipboard', 'info');
    } catch (e) {
      const ta = h('textarea', null, text);
      document.body.append(ta);
      ta.select();
      let ok = false;
      try {
        ok = document.execCommand('copy');
      } catch (err) {
        ok = false;
      }
      ta.remove();
      toast(ok ? 'Copied to clipboard' : 'Copy failed; select the text manually', ok ? 'info' : undefined);
    }
  }

  function fmtTokens(n) {
    if (n === undefined || n === null) return '?';
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 1 : 2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
    return String(n);
  }

  function fmtMB(bytes) {
    if (bytes === undefined || bytes === null) return '?';
    const mb = bytes / 1e6;
    return (mb < 0.01 ? mb.toFixed(3) : mb < 10 ? mb.toFixed(2) : mb.toFixed(1)) + ' MB';
  }

  function fmtDate(iso) {
    if (!iso) return '?';
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString();
  }

  function shortProject(p) {
    return (p || '').replace(/^-home-[^-]+-?/, '~/').replace(/^~\/$/, '~');
  }

  function nodes() {
    return (state.view && state.view.nodes) || {};
  }

  function clusters() {
    return (state.view && state.view.clusters) || {};
  }

  function titleOf(id) {
    if (id === 'sun') return 'Sun';
    const c = clusters()[id];
    if (c) return c.name;
    const n = nodes()[id];
    if (!n) return id;
    if (n.kind === 'cloud') return n.note ? 'Cloud: ' + n.note : 'Cloud';
    return (n.session && n.session.title) || n.note || n.id;
  }

  function busy(kind, id) {
    const b = state.view && state.view.busy;
    return !!(b && b[kind] && b[kind].includes(id));
  }

  function planets() {
    return Object.values(nodes()).filter((n) => n.kind === 'planet' && !n.missing);
  }

  // ---------- data refresh ----------

  async function refresh(force) {
    try {
      const now = Date.now();
      const pulse = await api('GET', '/api/pulse');
      const old = state.pulse;
      const treeChanged = !old || old.mtime !== pulse.mtime || JSON.stringify(old.busy) !== JSON.stringify(pulse.busy);
      const sessionsChanged = old && old.sessions !== pulse.sessions && now - state.lastView > SESSION_REFRESH_MS;
      state.pulse = pulse;
      if (!force && !treeChanged && !sessionsChanged && now - state.lastView < FULL_REFRESH_MS) return;
      const view = await api('GET', '/api/view');
      state.lastView = now;
      applyView(view);
      $('#status').textContent = 'synced ' + new Date().toLocaleTimeString();
    } catch (e) {
      $('#status').textContent = 'offline: ' + (e.message || e);
    }
  }

  function applyView(view) {
    state.view = view;
    state.M = (view.palettes && view.palettes.master) || DEFAULT_MASTER;
    state.schemes = (view.palettes && view.palettes.schemes) || {};
    for (const [k, v] of Object.entries(state.M)) document.documentElement.style.setProperty('--c' + k, v);
    if (state.selected && state.selected.type === 'node' && !nodes()[state.selected.id]) state.selected = null;
    if (state.selected && state.selected.type === 'cluster' && !clusters()[state.selected.id]) state.selected = null;
    if (state.focusPlanet && !nodes()[state.focusPlanet]) state.focusPlanet = null;
    relayout();
    if (!state.fitted) {
      fit();
      state.fitted = true;
    }
    renderBin();
    renderList();
    renderPanel(false);
    renderSettings();
  }

  // ---------- layout ----------

  function zoom() {
    return state.z;
  }

  function spacing(count) {
    const grow = Math.sqrt(count);
    return { arc: ARC + 6 * grow, ring: RING + 8 * grow };
  }

  function clusterOpen(cid) {
    if (state.collapsedByUser.has(cid)) return false;
    return state.expanded.has(cid) || zoom() >= CLUSTER_OPEN_ZOOM;
  }

  function relayout() {
    const ns = nodes();
    const rep = {};
    const items = {};
    for (const [cid, c] of Object.entries(clusters())) {
      const members = c.members.filter((m) => ns[m]);
      if (!members.length || clusterOpen(cid)) continue;
      for (const m of members) rep[m] = cid;
      items[cid] = { id: cid, type: 'cluster', cluster: c, members, parentRaw: null, children: [] };
    }
    for (const [id, n] of Object.entries(ns)) {
      if (rep[id]) {
        const cid = rep[id];
        if (n.parent && rep[n.parent] !== cid && items[cid].parentRaw === null) items[cid].parentRaw = n.parent;
        continue;
      }
      items[id] = { id, type: n.kind === 'cloud' ? 'cloud' : 'planet', node: n, parentRaw: n.parent, children: [] };
    }
    const sun = { id: 'sun', type: 'sun', children: [], depth: 0, x: 0, y: 0 };
    for (const it of Object.values(items)) {
      let p = it.parentRaw || 'sun';
      if (p !== 'sun') p = rep[p] || p;
      if (p === it.id || (p !== 'sun' && !items[p])) p = 'sun';
      it.parent = p;
    }
    for (const it of Object.values(items)) {
      let cur = it.parent;
      const seen = new Set([it.id]);
      while (cur !== 'sun') {
        if (seen.has(cur)) {
          it.parent = 'sun';
          break;
        }
        seen.add(cur);
        cur = items[cur].parent;
      }
    }
    const created = (it) => (it.node && it.node.created) || '';
    const slotOf = {};
    for (const it of Object.values(items).sort((a, b) => created(a).localeCompare(created(b)) || a.id.localeCompare(b.id))) {
      const holder = it.parent === 'sun' ? sun : items[it.parent];
      const g = it.node && it.node.group;
      const key = g ? `${it.parent}|${g}` : null;
      if (key && slotOf[key]) {
        slotOf[key].members.push(it);
        continue;
      }
      const slot = { id: 'slot:' + it.id, members: [it], group: g || null };
      if (key) slotOf[key] = slot;
      (holder.slots = holder.slots || []).push(slot);
    }
    for (const it of [sun, ...Object.values(items)]) {
      it.slots = it.slots || [];
      it.children = it.slots.flatMap((sl) => sl.members);
    }
    const leaves = (it) => {
      for (const sl of it.slots) sl.leaves = sl.members.reduce((acc, m) => acc + leaves(m), 0);
      it.leaves = it.slots.length ? it.slots.reduce((acc, sl) => acc + sl.leaves, 0) : 1;
      return it.leaves;
    };
    const total = leaves(sun);
    const gap = spacing(Object.keys(items).length);
    const r1 = Math.max(gap.ring + 20, (total * gap.arc) / (FAN_END - FAN_START));
    sun.angle = SUN_ANGLE;
    sun.r = 0;
    let maxDepth = 0;
    const groups = [];
    const place = (it, a0, a1, depth) => {
      let a = a0;
      const r = r1 + (depth - 1) * gap.ring;
      for (const sl of it.slots) {
        const span = ((a1 - a0) * sl.leaves) / it.leaves;
        const mid = a + span / 2;
        const n = sl.members.length;
        const step = n > 1 ? Math.min(GROUP_GAP / r, span / n) : 0;
        let b = a;
        sl.members.forEach((c, i) => {
          const ang = mid + (i - (n - 1) / 2) * step;
          const sub = ((a1 - a0) * c.leaves) / it.leaves;
          c.depth = depth;
          c.angle = ang;
          c.r = r;
          c.x = Math.cos(ang) * r;
          c.y = Math.sin(ang) * r;
          c.slot = sl;
          maxDepth = Math.max(maxDepth, depth);
          place(c, b, b + sub, depth + 1);
          b += sub;
        });
        if (n > 1) {
          sl.angle = mid;
          sl.r = r;
          sl.parent = it.id;
          groups.push(sl);
        }
        a += span;
      }
    };
    place(sun, FAN_START, FAN_END, 1);
    const all = [sun, ...Object.values(items)];
    const byId = Object.fromEntries(all.map((it) => [it.id, it]));
    const rings = Array.from({ length: maxDepth }, (_, i) => r1 + i * gap.ring);
    state.layout = { items: all, byId, rep, rings, r1, ring: gap.ring, groups };
  }

  function posOf(id) {
    const L = state.layout;
    if (!L) return null;
    if (L.byId[id]) return L.byId[id];
    if (L.rep[id]) return L.byId[L.rep[id]];
    const c = clusters()[id];
    if (c) {
      const pts = c.members.map((m) => L.byId[m]).filter(Boolean);
      if (!pts.length) return null;
      return { x: pts.reduce((s, p) => s + p.x, 0) / pts.length, y: pts.reduce((s, p) => s + p.y, 0) / pts.length };
    }
    return null;
  }

  function fit() {
    const L = state.layout;
    if (!L) return;
    let maxR = 40;
    for (const it of L.items) maxR = Math.max(maxR, Math.hypot(it.x, it.y) + 30);
    const fitZ = Math.min((canvas.width - 20) / (2 * maxR), (canvas.height - 40) / (maxR + 40));
    state.z = Math.max(ZOOM_START_MIN, Math.min(1, fitZ));
    state.cam = { x: 0, y: -maxR / 2 + 10 };
    state.camTarget = null;
    updateZoomLabel();
    relayout();
  }

  function updateZoomLabel() {
    $('#zoom-label').textContent = zoom().toFixed(2) + 'x';
  }

  function setZoom(z, sx, sy) {
    z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
    if (z === state.z) return;
    const W = canvas.width;
    const H = canvas.height;
    const cx = sx === undefined ? W / 2 : sx;
    const cy = sy === undefined ? H / 2 : sy;
    const z0 = zoom();
    const wx = (cx - W / 2) / z0 + state.cam.x;
    const wy = (cy - H / 2) / z0 + state.cam.y;
    state.z = z;
    const z1 = zoom();
    state.cam.x = wx - (cx - W / 2) / z1;
    state.cam.y = wy - (cy - H / 2) / z1;
    updateZoomLabel();
    relayout();
  }

  // ---------- pixel primitives ----------

  function mk(w, h2) {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h2;
    return c;
  }

  function hash2(x, y, s) {
    let v = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(s | 0, 982451653);
    v = Math.imul(v ^ (v >>> 13), 1274126177);
    return ((v ^ (v >>> 16)) >>> 0) / 4294967296;
  }

  function noise(x, y, s) {
    const xi = Math.floor(x);
    const yi = Math.floor(y);
    const xf = x - xi;
    const yf = y - yi;
    const a = hash2(xi, yi, s);
    const b = hash2(xi + 1, yi, s);
    const c = hash2(xi, yi + 1, s);
    const d = hash2(xi + 1, yi + 1, s);
    const u = xf * xf * (3 - 2 * xf);
    const v = yf * yf * (3 - 2 * yf);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  }

  function strHash(s) {
    let v = 2166136261;
    for (let i = 0; i < s.length; i++) {
      v ^= s.charCodeAt(i);
      v = Math.imul(v, 16777619);
    }
    return v >>> 0;
  }

  function bayer(x, y) {
    return (BAYER[y & 3][x & 3] + 0.5) / 16;
  }

  function px(g, x, y, color) {
    g.fillStyle = color;
    g.fillRect(x, y, 1, 1);
  }

  function clip(x0, y0, x1, y1, xmin, ymin, xmax, ymax) {
    let t0 = 0;
    let t1 = 1;
    const dx = x1 - x0;
    const dy = y1 - y0;
    const p = [-dx, dx, -dy, dy];
    const q = [x0 - xmin, xmax - x0, y0 - ymin, ymax - y0];
    for (let i = 0; i < 4; i++) {
      if (p[i] === 0) {
        if (q[i] < 0) return null;
      } else {
        const r = q[i] / p[i];
        if (p[i] < 0) {
          if (r > t1) return null;
          if (r > t0) t0 = r;
        } else {
          if (r < t0) return null;
          if (r < t1) t1 = r;
        }
      }
    }
    return [x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy];
  }

  function line(x0, y0, x1, y1, color, pattern, phase) {
    const c = clip(x0, y0, x1, y1, -2, -2, canvas.width + 2, canvas.height + 2);
    if (!c) return;
    let [ax, ay, bx, by] = c.map(Math.round);
    ctx.fillStyle = color;
    const dx = Math.abs(bx - ax);
    const dy = -Math.abs(by - ay);
    const sx = ax < bx ? 1 : -1;
    const sy = ay < by ? 1 : -1;
    let err = dx + dy;
    let i = phase || 0;
    const period = pattern ? pattern[0] + pattern[1] : 0;
    for (;;) {
      if (!pattern || ((i % period) + period) % period < pattern[0]) ctx.fillRect(ax, ay, 1, 1);
      if (ax === bx && ay === by) break;
      const e2 = 2 * err;
      if (e2 >= dy) {
        err += dy;
        ax += sx;
      }
      if (e2 <= dx) {
        err += dx;
        ay += sy;
      }
      i++;
    }
  }

  function textWidth(text, scale) {
    return text.length * 4 * scale - scale;
  }

  function pixelText(text, x, y, color, scale, align, shadow) {
    scale = scale || 1;
    text = String(text).toUpperCase();
    let sx = Math.round(align === 'left' ? x : x - textWidth(text, scale) / 2);
    const sy = Math.round(y);
    for (const pass of shadow === false ? [0] : [1, 0]) {
      ctx.fillStyle = pass ? state.M[0] : color;
      let cx = sx + pass * scale;
      for (const ch of text) {
        const glyph = FONT[ch] || FONT['?'];
        for (let i = 0; i < 15; i++) {
          if (glyph[i] === '1') ctx.fillRect(cx + (i % 3) * scale, sy + pass * scale + Math.floor(i / 3) * scale, scale, scale);
        }
        cx += 4 * scale;
      }
    }
    return sx;
  }

  // ---------- sprites ----------

  const spriteCache = new Map();

  function cached(key, build) {
    let s = spriteCache.get(key);
    if (!s) {
      s = build();
      spriteCache.set(key, s);
      if (spriteCache.size > 600) spriteCache.delete(spriteCache.keys().next().value);
    }
    return s;
  }

  function planetSprite(tier, colors, seed, missing) {
    const M = state.M;
    return cached(`p|${tier}|${colors.join()}|${seed}|${missing}|${M.join()}`, () => {
      const R = TIER_R[tier] || TIER_R.mars;
      const size = 2 * R + 1;
      const cv = mk(size, size);
      const g = cv.getContext('2d');
      const [c0, c1, c2] = missing ? [M[5], M[6], M[1]] : colors;
      const so = seed % 97;
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const dx = x - R;
          const dy = y - R;
          if (dx * dx + dy * dy > R * R + R * 0.6) continue;
          let col;
          if (tier === 'earth') {
            col = noise(x * 0.42 + so, y * 0.42, seed) > 0.5 ? c0 : c1;
          } else if (tier === 'jupiter') {
            const wob = noise(x * 0.22 + so, y * 0.5, seed) * 2.2;
            const band = Math.floor((y + wob) / (R / 3.2));
            col = band % 2 ? c1 : c0;
            if (band % 5 === 3) col = c2;
            const ex = (dx - R * 0.3) / (R * 0.32);
            const ey = (dy - R * 0.32) / (R * 0.18);
            if (ex * ex + ey * ey <= 1) col = c2;
          } else {
            const n = noise(x * 0.7 + so, y * 0.7, seed);
            col = n > 0.66 ? c1 : n < 0.24 ? c2 : c0;
            if (dy <= -R + 1 && !missing) col = M[7];
          }
          const shade = (dx + dy) / (R * 1.6);
          if (shade > 0.55 || (shade > 0.25 && (x + y) % 2 === 0)) col = col === c2 ? M[1] : c2;
          const hl = -Math.round(R * 0.45);
          if (!missing && dy === hl && (dx === hl || (tier !== 'mars' && dx === hl + 1))) col = M[7];
          px(g, x, y, col);
        }
      }
      return cv;
    });
  }

  function sunSprite(frame) {
    const M = state.M;
    return cached(`sun|${frame}|${M.join()}`, () => {
      const R = 12;
      const pad = 7;
      const size = 2 * (R + pad) + 1;
      const c = R + pad;
      const cv = mk(size, size);
      const g = cv.getContext('2d');
      for (let i = 0; i < 16; i++) {
        const a = (i / 16) * Math.PI * 2;
        const long = (i % 2 === 0) !== (frame === 1);
        const len = i % 4 === 0 ? (long ? 6 : 4) : long ? 4 : 2;
        for (let r = R + 2; r < R + 2 + len; r++) {
          px(g, Math.round(c + Math.cos(a) * r), Math.round(c + Math.sin(a) * r), r > R + 3 ? M[9] : M[10]);
        }
      }
      for (let y = -R; y <= R; y++) {
        for (let x = -R; x <= R; x++) {
          const d = Math.sqrt(x * x + y * y) / R;
          if (d > 1.04) continue;
          const th = bayer(x + c, y + c);
          let col = M[10];
          if (d > 0.78) col = (d - 0.78) / 0.26 > th ? M[9] : M[10];
          if (d > 0.93) col = M[9];
          if (d < 0.38) col = d / 0.38 < th + 0.2 ? M[7] : M[10];
          if (x === -5 && y === -6) col = M[7];
          px(g, c + x, c + y, col);
        }
      }
      return cv;
    });
  }

  function cloudSprite(seed, frame, tint, error) {
    const M = state.M;
    return cached(`c|${seed}|${frame}|${tint}|${error}|${M.join()}`, () => {
      const W = 26;
      const H = 15;
      const cv = mk(W, H);
      const g = cv.getContext('2d');
      const shift = frame ? 1 : 0;
      const blobs = [
        [7 + shift, 9, 6, 4],
        [13, 6, 6, 5],
        [19 - shift, 9, 6, 4],
        [12, 11, 8, 3],
      ];
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          let dens = 0;
          for (const [cx, cy, rx, ry] of blobs) {
            const v = 1 - ((x - cx) / rx) ** 2 - ((y - cy) / ry) ** 2;
            dens = Math.max(dens, v);
          }
          if (dens <= 0) continue;
          const th = bayer(x + seed, y);
          if (dens * 1.6 < th) continue;
          let col = dens > 0.45 ? M[7] : M[6];
          if (y > 9 && (x + y) % 2 === 0) col = tint;
          if (dens < 0.2) col = M[13];
          if (error && hash2(x, y, seed) < 0.18) col = M[8];
          px(g, x, y, col);
        }
      }
      return cv;
    });
  }

  function drawSprite(sprite, cx, cy, s) {
    const w = sprite.width * s;
    const hgt = sprite.height * s;
    ctx.drawImage(sprite, Math.round(cx - w / 2), Math.round(cy - hgt / 2), w, hgt);
  }

  // ---------- canvas drawing ----------

  function resize() {
    const wrap = $('#sky-wrap');
    const w = Math.max(1, Math.floor(wrap.clientWidth / PX));
    const hh = Math.max(1, Math.floor(wrap.clientHeight / PX));
    if (canvas.width === w && canvas.height === hh) return;
    canvas.width = w;
    canvas.height = hh;
    canvas.style.width = w * PX + 'px';
    canvas.style.height = hh * PX + 'px';
    ctx.imageSmoothingEnabled = false;
    const count = Math.floor((w * hh) / 260);
    const colors = [6, 7, 13, 12, 15, 6, 7, 5];
    state.stars = Array.from({ length: count }, (_, i) => ({
      x: hash2(i, 1, 7) * w * 2,
      y: hash2(i, 2, 7) * hh * 2,
      c: colors[Math.floor(hash2(i, 3, 7) * colors.length)],
      big: hash2(i, 4, 7) < 0.06,
      period: 1500 + hash2(i, 5, 7) * 4000,
      phase: hash2(i, 6, 7) * 10000,
      depth: 0.05 + hash2(i, 8, 7) * 0.2,
    }));
    draw();
  }

  function toScreen(x, y) {
    const z = zoom();
    return [Math.round((x - state.cam.x) * z + canvas.width / 2), Math.round((y - state.cam.y) * z + canvas.height / 2)];
  }

  function spriteScale() {
    return Math.max(1, Math.floor(zoom()));
  }

  function drawStars() {
    const W = canvas.width;
    const H = canvas.height;
    const M = state.M;
    const z = zoom();
    for (const s of state.stars) {
      const x = Math.floor((((s.x - state.cam.x * z * s.depth) % (W * 2)) + W * 2) % (W * 2));
      const y = Math.floor((((s.y - state.cam.y * z * s.depth) % (H * 2)) + H * 2) % (H * 2));
      if (x >= W || y >= H) continue;
      const ph = ((state.t + s.phase) % s.period) / s.period;
      if (ph > 0.93) continue;
      const col = ph > 0.8 ? M[5] : M[s.c];
      ctx.fillStyle = col;
      ctx.fillRect(x, y, 1, 1);
      if (s.big && ph < 0.25) {
        ctx.fillStyle = M[s.c];
        ctx.fillRect(x - 1, y, 1, 1);
        ctx.fillRect(x + 1, y, 1, 1);
        ctx.fillRect(x, y - 1, 1, 1);
        ctx.fillRect(x, y + 1, 1, 1);
      }
    }
  }

  function itemRadius(it) {
    const s = spriteScale();
    if (it.type === 'sun') return 13 * s;
    if (it.type === 'cloud') return 10 * s;
    if (it.type === 'cluster') return 12 * s;
    return planetRadius(it.node) * s;
  }

  function planetRadius(n) {
    const sig = (state.view && state.view.signals) || {};
    const tier = sig.planet_size === false ? 'earth' : n.tier_name || 'mars';
    return TIER_R[tier] || TIER_R.mars;
  }

  function nodeColors(n) {
    return n.colors && n.colors.length >= 3 ? n.colors : [state.M[8], state.M[9], state.M[4]];
  }

  function drawPlanet(it, sx, sy, s) {
    const n = it.node;
    const sig = (state.view && state.view.signals) || {};
    const tier = sig.planet_size === false ? 'earth' : n.tier_name || 'mars';
    const sprite = planetSprite(tier, nodeColors(n), strHash(it.id), !!n.missing);
    drawSprite(sprite, sx, sy, s);
    const R = planetRadius(n) * s;
    if (n.badge && Math.floor(state.t / 400) % 3 !== 0) {
      const bx = sx + R - s;
      const by = sy - R - 3 * s;
      ctx.fillStyle = state.M[8];
      ctx.fillRect(bx, by, 5 * s, 6 * s);
      ctx.fillStyle = state.M[10];
      ctx.fillRect(bx + 2 * s, by + s, s, 2 * s);
      ctx.fillRect(bx + 2 * s, by + 4 * s, s, s);
    }
    if (n.sun_drift) {
      ctx.fillStyle = state.M[9];
      ctx.fillRect(sx - R - 2 * s, sy - R - 2 * s, 2 * s, 2 * s);
    }
  }

  function drawCluster(it, sx, sy, s) {
    const M = state.M;
    const R = 12 * s;
    for (let a = 0; a < 48; a++) {
      const ang = (a / 48) * Math.PI * 2 + state.t / 4000;
      const x = Math.round(sx + Math.cos(ang) * R);
      const y = Math.round(sy + Math.sin(ang) * R);
      if ((a + Math.floor(state.t / 300)) % 3 !== 0) {
        ctx.fillStyle = M[13];
        ctx.fillRect(x, y, s, s);
      }
    }
    const offs = [[-4, 3], [4, 3], [0, -4]];
    it.members.slice(0, 3).forEach((m, i) => {
      const n = nodes()[m];
      const sprite = planetSprite('mars', nodeColors(n), strHash(m), !!n.missing);
      drawSprite(sprite, sx + offs[i][0] * s, sy + offs[i][1] * s, s);
    });
    pixelText(String(it.members.length), sx + R, sy - R, M[10], s, 'left');
  }

  function drawSatellite(x, y, s, status) {
    const M = state.M;
    const body = status === 'done' ? M[11] : status === 'error' ? M[8] : M[10];
    ctx.fillStyle = M[12];
    ctx.fillRect(x - 3 * s, y - s, 2 * s, 2 * s);
    ctx.fillRect(x + 2 * s, y - s, 2 * s, 2 * s);
    ctx.fillStyle = M[6];
    ctx.fillRect(x - s, y - s, 3 * s, 3 * s);
    ctx.fillStyle = body;
    ctx.fillRect(x, y, s, s);
    if ((status === 'running' || status === 'pending') && Math.floor(state.t / 250) % 2) {
      ctx.fillStyle = M[10];
      ctx.fillRect(x, y - 2 * s, s, s);
    }
  }

  function drawBrackets(x, y, r, color) {
    const s = spriteScale();
    const k = 3 * s;
    ctx.fillStyle = color;
    for (const [dx, dy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const cx = x + dx * (r + 2 * s);
      const cy = y + dy * (r + 2 * s);
      ctx.fillRect(dx < 0 ? cx : cx - k + s, cy, k, s);
      ctx.fillRect(cx, dy < 0 ? cy : cy - k + s, s, k);
    }
  }

  function arc(r, a0, a1, color, pattern) {
    const z = zoom();
    if (Math.abs(a1 - a0) < 1e-6) return;
    const n = Math.max(6, Math.ceil((Math.abs(a1 - a0) * r * z) / 3));
    let [px0, py0] = toScreen(Math.cos(a0) * r, Math.sin(a0) * r);
    for (let i = 1; i <= n; i++) {
      const a = a0 + ((a1 - a0) * i) / n;
      const [px1, py1] = toScreen(Math.cos(a) * r, Math.sin(a) * r);
      line(px0, py0, px1, py1, color, pattern, i * 3);
      px0 = px1;
      py0 = py1;
    }
  }

  function spoke(a, r0, r1, color, pattern) {
    const [x0, y0] = toScreen(Math.cos(a) * r0, Math.sin(a) * r0);
    const [x1, y1] = toScreen(Math.cos(a) * r1, Math.sin(a) * r1);
    line(x0, y0, x1, y1, color, pattern, 0);
  }

  function junction(a, r, color) {
    const [x, y] = toScreen(Math.cos(a) * r, Math.sin(a) * r);
    const s = spriteScale();
    ctx.fillStyle = color;
    ctx.fillRect(x - s, y - s, 2 * s + 1, 2 * s + 1);
  }

  function drawGroupBracket(sl, bus, color) {
    const z = zoom();
    const s = spriteScale();
    const members = sl.members;
    const solid = members.some((m) => m.type !== 'cloud');
    const col = solid ? color : state.M[13];
    const pattern = solid ? null : [1, 2];
    const reach = Math.max(...members.map((m) => itemRadius(m))) / z + 6;
    const rb = sl.r - reach;
    const lo = Math.min(...members.map((m) => m.angle));
    const hi = Math.max(...members.map((m) => m.angle));
    spoke(sl.angle, bus, rb, col, pattern);
    junction(sl.angle, bus, col);
    arc(rb, lo, hi, col, pattern);
    for (const m of members) {
      const mc = m.type === 'cloud' ? state.M[13] : col;
      spoke(m.angle, rb, m.r - itemRadius(m) / z, mc, m.type === 'cloud' ? [1, 2] : null);
    }
    const [jx, jy] = toScreen(Math.cos(sl.angle) * rb, Math.sin(sl.angle) * rb);
    ctx.fillStyle = col;
    ctx.fillRect(jx - s, jy - s, 2 * s + 1, 2 * s + 1);
  }

  function busRadius(parent, child) {
    const L = state.layout;
    if (parent.id === 'sun') return L.r1 * 0.55;
    return parent.r + (child.r - parent.r) * 0.5;
  }

  function drawEdges(L) {
    const M = state.M;
    const z = zoom();
    for (const r of L.rings) arc(r, FAN_START, FAN_END, M[1], [1, 5]);
    const byParent = {};
    for (const it of L.items) {
      if (it.type === 'sun') continue;
      (byParent[it.parent] = byParent[it.parent] || []).push(it);
    }
    for (const [pid, kids] of Object.entries(byParent)) {
      const parent = L.byId[pid];
      if (!parent) continue;
      const bus = busRadius(parent, kids[0]);
      const base = pid === 'sun' ? M[12] : M[6];
      const angles = kids.map((k) => (k.slot && k.slot.members.length > 1 ? k.slot.angle : k.angle));
      const lo = Math.min(parent.angle, ...angles);
      const hi = Math.max(parent.angle, ...angles);
      const solid = kids.some((k) => k.type !== 'cloud');
      const trunk = solid ? base : M[13];
      const trunkPattern = solid ? null : [1, 2];
      const sunGap = pid === 'sun' ? itemRadius(parent) / z : 0;
      spoke(parent.angle, parent.r + sunGap, bus, trunk, trunkPattern);
      if (pid === 'sun') {
        const solidKids = kids.filter((k) => k.type !== 'cloud').map((k) => (k.slot && k.slot.members.length > 1 ? k.slot.angle : k.angle));
        const slo = solidKids.length ? Math.min(SUN_ANGLE, ...solidKids) : SUN_ANGLE;
        const shi = solidKids.length ? Math.max(SUN_ANGLE, ...solidKids) : SUN_ANGLE;
        arc(bus, slo, shi, base, null);
        arc(bus, lo, slo, M[13], [1, 2]);
        arc(bus, shi, hi, M[13], [1, 2]);
      } else {
        arc(bus, lo, hi, trunk, trunkPattern);
      }
      junction(parent.angle, bus, trunk);
      const drawn = new Set();
      for (const k of kids) {
        const sl = k.slot;
        if (sl && sl.members.length > 1) {
          if (drawn.has(sl)) continue;
          drawn.add(sl);
          drawGroupBracket(sl, bus, base);
          continue;
        }
        const cloud = k.type === 'cloud';
        const col = cloud ? M[13] : base;
        spoke(k.angle, bus, k.r, col, cloud ? [1, 2] : null);
        junction(k.angle, bus, col);
      }
    }
  }

  function draw() {
    const W = canvas.width;
    const H = canvas.height;
    const M = state.M;
    ctx.fillStyle = M[0];
    ctx.fillRect(0, 0, W, H);
    drawStars();
    const L = state.layout;
    state.hits = [];
    if (!L) {
      pixelText('LOADING...', W / 2, H / 2, M[6], 2);
      return;
    }
    const s = spriteScale();
    const z = zoom();
    const frame = Math.floor(state.t / 500) % 2;
    const scr = {};
    for (const it of L.items) scr[it.id] = toScreen(it.x, it.y);

    drawEdges(L);

    for (const p of (state.view && state.view.pulls) || []) {
      const a = posOf(p.source);
      const b = posOf(p.target);
      if (!a || !b || a === b) continue;
      const [x0, y0] = toScreen(a.x, a.y);
      const [x1, y1] = toScreen(b.x, b.y);
      line(x0, y0, x1, y1, M[14], [4, 3], -Math.floor(state.t / 120));
      const ang = Math.atan2(y1 - y0, x1 - x0);
      const back = 10 * s;
      const hx = x1 - Math.cos(ang) * back;
      const hy = y1 - Math.sin(ang) * back;
      for (const da of [-0.5, 0.5]) {
        line(hx, hy, hx - Math.cos(ang + da) * 4 * s, hy - Math.sin(ang + da) * 4 * s, M[14], null, 0);
      }
    }

    for (const [cid, c] of Object.entries(clusters())) {
      if (!clusterOpen(cid)) continue;
      const pts = c.members.map((m) => L.byId[m]).filter(Boolean);
      if (!pts.length) continue;
      for (const p of pts) {
        const [x, y] = scr[p.id];
        const r = itemRadius(p) + 3 * s;
        for (let a = 0; a < 24; a += 2) {
          ctx.fillStyle = M[13];
          ctx.fillRect(Math.round(x + Math.cos((a / 24) * 6.283) * r), Math.round(y + Math.sin((a / 24) * 6.283) * r), s, s);
        }
      }
      const cp = posOf(cid);
      const [cx, cy] = toScreen(cp.x, cp.y);
      const label = c.name.length > 40 ? c.name.slice(0, 39) + '.' : c.name;
      const lx = pixelText(label, cx, cy - 24 * s, M[14], 1);
      state.hits.push({ type: 'cluster-label', id: cid, x: cx, y: cy - 22 * s, r: 0, box: [lx, cy - 24 * s, textWidth(label, 1), 6] });
    }

    const [sunX, sunY] = scr.sun;
    drawSprite(sunSprite(frame), sunX, sunY, s);
    state.hits.push({ type: 'sun', id: 'sun', x: sunX, y: sunY, r: 14 * s });
    if (state.showLabels) pixelText('SUN', sunX, sunY + 21 * s, M[10], 1);

    const margin = 40 * s;
    for (const it of L.items) {
      if (it.type === 'sun') continue;
      const [x, y] = scr[it.id];
      if (x < -margin || y < -margin || x > W + margin || y > H + margin) continue;
      const r = itemRadius(it);
      if (it.type === 'planet') drawPlanet(it, x, y, s);
      else if (it.type === 'cloud') {
        const n = it.node;
        const working = busy('instantiate', it.id) || state.pending['inst:' + it.id];
        const f = working ? Math.floor(state.t / 150) % 2 : frame;
        drawSprite(cloudSprite(strHash(it.id) % 8, f, nodeColors(n)[0], !!n.error), x, y, s);
      } else if (it.type === 'cluster') drawCluster(it, x, y, s);
      state.hits.push({ type: it.type, id: it.id, x, y, r: r + s });
      if (state.showLabels && (z >= 1 || it.type === 'cluster')) {
        let label = it.type === 'cluster' ? it.cluster.name : titleOf(it.id);
        const max = it.type === 'cluster' ? 34 : 22;
        if (label.length > max) label = label.slice(0, max - 1) + '.';
        const sel = state.selected && state.selected.id === it.id;
        const col = sel ? M[10] : it.type === 'cloud' ? M[13] : it.type === 'cluster' ? M[14] : M[6];
        pixelText(label, x, y + r + 3 * s, col, 1);
        if (it.type === 'planet' && z >= 2 && it.node.context_pct !== undefined) {
          pixelText(it.node.context_pct + '%', x, y + r + 10 * s, M[5], 1);
        }
      }
    }

    const byTarget = {};
    for (const rv of (state.view && state.view.reviews) || []) (byTarget[rv.target] = byTarget[rv.target] || []).push(rv);
    for (const [target, revs] of Object.entries(byTarget)) {
      const p = posOf(target);
      if (!p) continue;
      const it = L.byId[target] || L.byId[L.rep[target]];
      const [x, y] = toScreen(p.x, p.y);
      const orbit = (it ? itemRadius(it) : 8 * s) + 6 * s;
      revs.forEach((rv, i) => {
        const status = busy('reviews', rv.id) ? 'running' : rv.status;
        const speed = status === 'done' || status === 'error' ? 0.0006 : 0.0016;
        const ang = state.t * speed * (1 + i * 0.15) + (i * Math.PI * 2) / revs.length;
        const sx2 = Math.round(x + Math.cos(ang) * orbit);
        const sy2 = Math.round(y + Math.sin(ang) * orbit * 0.6);
        drawSatellite(sx2, sy2, s, status);
        state.hits.push({ type: 'review', id: rv.id, target, x: sx2, y: sy2, r: 4 * s });
      });
    }

    if (state.selected) {
      const p = state.selected.type === 'sun' ? { x: 0, y: 0 } : posOf(state.selected.id);
      if (p && Math.floor(state.t / 350) % 2 === 0) {
        const it = L.byId[state.selected.id];
        const [x, y] = toScreen(p.x, p.y);
        drawBrackets(x, y, it ? itemRadius(it) : 12 * s, M[10]);
      }
    }

    if (state.listHover && (!state.selected || state.selected.id !== state.listHover)) {
      const p = posOf(state.listHover);
      const it = L.byId[state.listHover] || L.byId[L.rep[state.listHover]];
      if (p) {
        const [x, y] = toScreen(p.x, p.y);
        drawBrackets(x, y, it ? itemRadius(it) : 12 * s, M[12]);
      }
    }

    if (state.dropTarget) {
      const hit = state.dropTarget;
      if (Math.floor(state.t / 150) % 2 === 0) drawBrackets(hit.x, hit.y, hit.r, M[11]);
    }

    const d = state.drag;
    if (d && d.kind === 'node' && d.moved && d.cur) {
      line(d.from.x, d.from.y, d.cur[0], d.cur[1], M[14], [2, 2], -Math.floor(state.t / 80));
      pixelText(state.dropTarget ? (state.dropTarget.type === 'sun' ? 'MOVE TO TOP' : 'PULL INTO') : 'DRAG ONTO A PLANET', d.cur[0], d.cur[1] + 8, M[14], 1);
    }

    if (state.view && !Object.keys(nodes()).length) {
      pixelText('DRAG A SESSION FROM THE DROP BIN ONTO THE SUN', sunX, sunY + 34 * s, M[13], 1);
    }
  }

  function easeCamera() {
    const t = state.camTarget;
    if (!t) return;
    const dx = t.x - state.cam.x;
    const dy = t.y - state.cam.y;
    if (Math.hypot(dx, dy) < 0.5) {
      state.cam = { x: t.x, y: t.y };
      state.camTarget = null;
    } else {
      state.cam.x += dx * 0.25;
      state.cam.y += dy * 0.25;
    }
    state._dirty = true;
  }

  function panTo(id) {
    const p = id === 'sun' ? { x: 0, y: 0 } : posOf(id);
    if (p) state.camTarget = { x: p.x, y: p.y };
  }

  function loop(now) {
    easeCamera();
    if (state.animate || !state._lastFrame) {
      if (!state._lastFrame || now - state._lastFrame >= FRAME_MS) {
        state.t = now;
        state._lastFrame = now;
        draw();
      }
    } else if (state._dirty) {
      state._dirty = false;
      draw();
    }
    requestAnimationFrame(loop);
  }

  // ---------- hit testing + input ----------

  function canvasPoint(e) {
    const rect = canvas.getBoundingClientRect();
    return [(e.clientX - rect.left) / PX, (e.clientY - rect.top) / PX];
  }

  function hitTest(x, y, filter) {
    for (let i = state.hits.length - 1; i >= 0; i--) {
      const hit = state.hits[i];
      if (filter && !filter(hit)) continue;
      if (hit.box) {
        const [bx, by, bw, bh] = hit.box;
        if (x >= bx - 1 && x <= bx + bw + 1 && y >= by - 1 && y <= by + bh + 1) return hit;
      } else if (Math.hypot(hit.x - x, hit.y - y) <= hit.r) return hit;
    }
    return null;
  }

  const isPlanetOrSun = (hit) => hit.type === 'sun' || (hit.type === 'planet' && !nodes()[hit.id].missing);

  canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const [x, y] = canvasPoint(e);
    const hit = hitTest(x, y);
    hideTip();
    if (hit) state.drag = { kind: 'node', from: hit, sx: x, sy: y, moved: false };
    else state.drag = { kind: 'pan', sx: x, sy: y, cam0: { ...state.cam }, moved: false };
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    const d = state.drag;
    const [x, y] = canvasPoint(e);
    if (!d) {
      if (e.target === canvas) onHover(x, y, e);
      return;
    }
    if (Math.hypot(x - d.sx, y - d.sy) > 2) d.moved = true;
    if (d.kind === 'pan') {
      canvas.classList.add('panning');
      state.camTarget = null;
      state.cam.x = d.cam0.x - (x - d.sx) / zoom();
      state.cam.y = d.cam0.y - (y - d.sy) / zoom();
      state._dirty = true;
    } else if (d.kind === 'node' && (d.from.type === 'planet' || d.from.type === 'cluster')) {
      d.cur = [x, y];
      const t = d.moved ? hitTest(x, y, (hit) => isPlanetOrSun(hit) && hit.id !== d.from.id) : null;
      state.dropTarget = t && !(d.from.type === 'cluster' && t.type === 'sun') ? t : null;
    }
  });

  window.addEventListener('mouseup', () => {
    const d = state.drag;
    state.drag = null;
    canvas.classList.remove('panning');
    if (!d) return;
    const target = state.dropTarget;
    state.dropTarget = null;
    if (d.kind === 'node') {
      if (!d.moved) onClick(d.from);
      else if (target) onNodeDrop(d.from, target);
    }
  });

  function copyResume(id) {
    const n = nodes()[id];
    if (!n || !n.session_id) return toast('Only planets have a session to resume');
    copyText(`claude --resume ${n.session_id}`);
  }

  canvas.addEventListener('dblclick', (e) => {
    const [x, y] = canvasPoint(e);
    const hit = hitTest(x, y);
    if (hit && hit.type === 'planet') copyResume(hit.id);
  });

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const [x, y] = canvasPoint(e);
    const lines = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    const delta = Math.max(-200, Math.min(200, e.deltaY * lines));
    setZoom(state.z * Math.exp(-delta * WHEEL_SENSITIVITY), x, y);
  }, { passive: false });

  canvas.addEventListener('mouseleave', () => {
    state.hover = null;
    hideTip();
  });

  canvas.addEventListener('dragover', (e) => {
    if (!e.dataTransfer.types.includes('text/webtree-session')) return;
    e.preventDefault();
    const [x, y] = canvasPoint(e);
    state.dropTarget = hitTest(x, y, isPlanetOrSun);
    e.dataTransfer.dropEffect = state.dropTarget ? 'move' : 'none';
  });

  canvas.addEventListener('dragleave', () => {
    state.dropTarget = null;
  });

  canvas.addEventListener('drop', (e) => {
    e.preventDefault();
    const sid = e.dataTransfer.getData('text/webtree-session');
    const [x, y] = canvasPoint(e);
    const target = hitTest(x, y, isPlanetOrSun);
    state.dropTarget = null;
    if (sid && target) placeSession(sid, target.id);
  });

  function onClick(hit) {
    if (hit.type === 'sun') select({ type: 'sun', id: 'sun' });
    else if (hit.type === 'cluster' || hit.type === 'cluster-label') {
      state.collapsedByUser.delete(hit.id);
      state.expanded.add(hit.id);
      relayout();
      select({ type: 'cluster', id: hit.id });
    } else if (hit.type === 'review') select({ type: 'node', id: hit.target });
    else select({ type: 'node', id: hit.id });
  }

  function onNodeDrop(from, target) {
    if (target.type === 'sun') {
      if (confirm(`Move "${titleOf(from.id)}" to the top level (under the sun)?`)) {
        act(() => api('POST', `/api/nodes/${enc(from.id)}/move`, { parent: 'sun' }), 'Moved');
      }
      return;
    }
    const a = nodes()[from.id];
    const b = nodes()[target.id];
    if (a && b && a.parent === b.parent) {
      openModal(
        h('h2', null, 'Siblings'),
        h('div', null, `"${titleOf(from.id)}" and "${titleOf(target.id)}" share a parent.`),
        h('div', { class: 'row', style: 'margin-top:10px' },
          h('button', { class: 'primary', onclick: () => act(() => api('POST', '/api/groups', { node_ids: [from.id, target.id] }), 'Placed side by side').then(closeModal) }, 'Place side by side'),
          h('button', { onclick: () => { closeModal(); openPullDialog(from.id, target.id); } }, 'Pull context instead'),
          h('button', { onclick: closeModal }, 'Cancel')),
      );
      return;
    }
    openPullDialog(from.id, target.id);
  }

  let tipReq = 0;
  function onHover(x, y, e) {
    const hit = hitTest(x, y);
    canvas.classList.toggle('over-node', !!hit);
    const key = hit ? hit.type + ':' + hit.id : null;
    if (key !== state.hover) {
      state.hover = key;
      if (!hit) return hideTip();
      showTip(tipFor(hit), e);
      if (hit.type === 'planet') {
        const n = nodes()[hit.id];
        if (n && n.session_id) {
          const req = ++tipReq;
          api('GET', `/api/sessions/${enc(n.session_id)}/stats`).then((st) => {
            state.stats[n.session_id] = st;
            if (req === tipReq && state.hover === key) showTip(tipFor(hit), null);
          }).catch(() => {});
        }
      }
    } else if (hit) moveTip(e);
  }

  function tipFor(hit) {
    if (hit.type === 'sun') return [h('div', { class: 't' }, 'THE SUN'), h('div', null, 'Overall + per-project memory. Click to open.')];
    if (hit.type === 'cluster' || hit.type === 'cluster-label') {
      const c = clusters()[hit.id];
      return [h('div', { class: 't' }, c.name), h('div', null, `${c.members.length} planets in ${shortProject(c.project)}`), h('div', { class: 'n' }, 'click to open; drag onto a planet to pull')];
    }
    if (hit.type === 'review') {
      const rv = ((state.view && state.view.reviews) || []).find((r) => r.id === hit.id);
      if (!rv) return ['review'];
      return [h('div', { class: 't' }, 'REVIEWER: ' + (busy('reviews', rv.id) ? 'running' : rv.status)), h('div', null, rv.problem.slice(0, 200)), h('div', { class: 'n' }, rv.reviewer === 'fresh' ? 'fresh agent' : 'from ' + titleOf(rv.reviewer))];
    }
    const n = nodes()[hit.id];
    if (!n) return [''];
    if (n.kind === 'cloud') {
      return [h('div', { class: 't' }, 'CLOUD (staged)'), h('div', null, n.note || '(no note)'), n.error ? h('div', { style: 'color:var(--c8)' }, n.error) : null];
    }
    if (n.missing) return [h('div', { class: 't' }, titleOf(n.id)), h('div', null, 'transcript missing')];
    const st = state.stats[n.session_id] || n.session || {};
    return [
      h('div', { class: 't' }, titleOf(n.id)),
      h('div', null, `Lifetime tokens: ${fmtTokens(st.lifetime_tokens)}`),
      h('div', null, `Transcript: ${fmtMB(st.file_size)}`),
      h('div', null, `Context: ${st.context_pct !== undefined ? st.context_pct : n.context_pct}% (${(st.tier_name || n.tier_name || '').toUpperCase()})`),
      n.sun_drift ? h('div', { style: 'color:var(--c9)' }, 'memory changed since creation') : null,
    ];
  }

  function showTip(content, e) {
    const tip = $('#tip');
    tip.replaceChildren(...[content].flat().filter(Boolean));
    tip.classList.remove('hidden');
    if (e) moveTip(e);
  }

  function moveTip(e) {
    const tip = $('#tip');
    const x = Math.min(e.clientX + 16, window.innerWidth - tip.offsetWidth - 8);
    const y = Math.min(e.clientY + 16, window.innerHeight - tip.offsetHeight - 8);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }

  function hideTip() {
    $('#tip').classList.add('hidden');
  }

  // ---------- selection + side panel ----------

  function select(sel) {
    state.selected = sel;
    if (sel && sel.type === 'node') {
      const n = nodes()[sel.id];
      if (n && n.kind === 'planet') {
        state.focusPlanet = sel.id;
        if (n.session_id && !state.summaries[n.session_id]) loadSummary(n.session_id, true);
      }
    }
    if (sel && sel.type === 'sun') loadSun();
    renderPanel(true);
    renderList();
  }

  function panelSignature() {
    const sel = state.selected;
    if (!sel) return '';
    const v = state.view || {};
    const base = { sel, busy: v.busy, pending: state.pending, clusters: v.clusters, signals: v.signals };
    if (sel.type === 'node') {
      const n = nodes()[sel.id];
      const sid = n && n.session_id;
      return JSON.stringify({
        ...base,
        n,
        reviews: (v.reviews || []).filter((r) => r.target === sel.id),
        pulls: (v.pulls || []).filter((p) => p.target === sel.id || p.source === sel.id),
        sum: state.summaries[sid],
        tr: state.transcripts[sid],
        rp: state.reviewPrompts,
        names: Object.keys(nodes()).length,
      });
    }
    if (sel.type === 'sun') {
      return JSON.stringify({ sel, focus: state.focusPlanet, data: !!state.sun.data, open: [...state.sun.open], po: [...state.sun.projectsOpen], files: Object.keys(state.sun.files) });
    }
    return JSON.stringify({ ...base, n: Object.keys(nodes()).length, expanded: clusterOpen(sel.id) });
  }

  function renderPanel(force) {
    const panel = $('#panel');
    const sel = state.selected;
    if (!sel) {
      panel.classList.add('hidden');
      state.panelSig = '';
      return;
    }
    const sig = panelSignature();
    if (!force && sig === state.panelSig) return;
    const active = document.activeElement;
    if (!force && panel.contains(active) && /INPUT|TEXTAREA|SELECT/.test(active.tagName)) return;
    state.panelSig = sig;
    let content;
    if (sel.type === 'sun') content = sunPanel();
    else if (sel.type === 'cluster') content = clusterPanel(sel.id);
    else {
      const n = nodes()[sel.id];
      content = n.kind === 'cloud' ? cloudPanel(n) : planetPanel(n);
    }
    const scroll = panel.scrollTop;
    panel.replaceChildren(h('button', { class: 'close small', onclick: () => select(null) }, 'X'), ...content);
    panel.classList.remove('hidden');
    panel.scrollTop = scroll;
  }

  function kv(pairs) {
    return h('div', { class: 'kv' }, pairs.filter(Boolean).map(([k, v]) => [h('div', { class: 'k' }, k), h('div', { class: 'v' }, v === undefined || v === null || v === '' ? '-' : v)]));
  }

  function swatches(current, onPick) {
    const wrap = h('div', { class: 'swatches' });
    for (const [id, sch] of Object.entries(state.schemes)) {
      const sw = h('div', { class: 'swatch' + (id === current ? ' on' : ''), title: sch.name },
        sch.colors.map((i) => h('span', { style: `background:${state.M[i]}` })));
      sw.addEventListener('click', () => {
        wrap.querySelectorAll('.swatch').forEach((x) => x.classList.remove('on'));
        sw.classList.add('on');
        onPick(id);
      });
      wrap.append(sw);
    }
    return wrap;
  }

  function nodeLink(id) {
    if (!id) return '-';
    if (id === 'sun') return h('span', { class: 'link', onclick: () => select({ type: 'sun', id: 'sun' }) }, 'Sun');
    return h('span', { class: 'link', onclick: () => select({ type: 'node', id }) }, titleOf(id));
  }

  async function loadSummary(sid, cachedOnly) {
    if (!cachedOnly) state.summaries[sid] = { loading: true };
    renderPanel(false);
    try {
      const r = await api('GET', `/api/sessions/${enc(sid)}/summary?level=brief${cachedOnly ? '&cached_only=true' : ''}`);
      if (r.summary || !cachedOnly) state.summaries[sid] = { text: r.summary };
      else if (!state.summaries[sid]) state.summaries[sid] = { none: true };
    } catch (e) {
      state.summaries[sid] = { error: e.message };
    }
    renderPanel(false);
  }

  function summarySection(sid) {
    const sm = state.summaries[sid];
    const btn = h('button', { class: 'small', onclick: () => loadSummary(sid, false) }, 'Summarize (brief)');
    if (!sm || sm.none) return [h('div', { class: 'muted' }, 'No summary yet (costs one small model call).'), btn];
    if (sm.loading) return h('div', null, h('span', { class: 'spin' }), 'summarizing...');
    if (sm.error) return [h('div', { class: 'error' }, sm.error), btn];
    return h('div', null, sm.text);
  }

  function planetPanel(n) {
    const s = n.session || {};
    const v = state.view;
    const reviews = (v.reviews || []).filter((r) => r.target === n.id);
    const pullsIn = (v.pulls || []).filter((p) => p.target === n.id);
    const pullsOut = (v.pulls || []).filter((p) => p.source === n.id);
    const sameProject = Object.entries(clusters()).filter(([, c]) => c.project === n.project);
    const out = [
      h('h2', null, titleOf(n.id)),
      h('div', { class: 'muted' }, `PLANET - ${(n.tier_name || '?').toUpperCase()}${n.cluster ? ' - in cluster' : ''}`),
    ];
    if (n.missing) out.push(h('div', { class: 'error' }, 'Transcript file is missing.'));
    if (s.session_id) out.push(h('h3', null, 'Summary'), summarySection(s.session_id));
    out.push(
      h('h3', null, 'Details'),
      kv([
        ['Parent', nodeLink(n.parent)],
        ['Created', fmtDate(n.created)],
        ['Project', shortProject(n.project)],
        ['Cwd', s.cwd],
        ['Branch', s.git_branch],
        ['Model', s.model],
        ['Tier', `${(n.tier_name || '?').toUpperCase()} - ${n.context_pct !== undefined ? n.context_pct + '% context' : '?'}`],
        ['Lifetime', fmtTokens(s.lifetime_tokens) + ' tokens'],
        ['Size', fmtMB(s.file_size)],
        ['Messages', s.message_count],
        ['Session', s.session_id],
        n.cluster ? ['Cluster', h('span', { class: 'link', onclick: () => select({ type: 'cluster', id: n.cluster }) }, titleOf(n.cluster))] : null,
      ]),
    );
    if (n.sun_drift) {
      out.push(h('div', { class: 'warn' }, 'Sun drift: this session predates changes to its memory (overall or project layer changed since it was created).'));
    }
    out.push(h('div', { class: 'row' }, h('span', { class: 'link', onclick: () => { state.focusPlanet = n.id; select({ type: 'sun', id: 'sun' }); } }, 'Show what this session loads (sun)')));

    out.push(h('h3', null, 'Palette'), swatches(n.palette, (id) => act(() => api('POST', `/api/nodes/${enc(n.id)}/palette`, { palette: id }))));

    const note = h('textarea', { rows: 2, placeholder: 'note...' }, n.note || '');
    out.push(h('h3', null, 'Note'), note, h('div', { class: 'row' }, h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/note`, { note: note.value }), 'Note saved') }, 'Save note')));

    const live = !n.missing && n.session_id;
    out.push(
      h('h3', null, 'Actions'),
      h('div', { class: 'row' },
        h('button', { class: 'primary', disabled: !live, onclick: () => openForkDialog(n) }, 'Fork'),
        h('button', { disabled: !live, onclick: () => openSplitDialog(n) }, 'Split'),
        h('button', { disabled: !live, onclick: () => openPullDialog(n.id, null) }, 'Pull into...'),
        h('button', { disabled: !live, onclick: () => openReviewDialog(n) }, 'Add reviewer'),
      ),
      h('div', { class: 'row' },
        h('button', { disabled: !live, onclick: () => act(async () => copyText((await api('GET', `/api/nodes/${enc(n.id)}/open_command`)).command)) }, 'Copy open-in-terminal'),
        h('button', { class: 'danger', onclick: () => confirm('Return this planet to the drop bin? Its children move up to its parent.') && act(() => api('POST', `/api/nodes/${enc(n.id)}/unplace`), 'Unplaced').then(() => select(null)) }, 'Unplace'),
      ),
      ...sideBySideSection(n),
    );

    const parentSel = h('select', null,
      h('option', { value: 'sun' }, 'Sun (top level)'),
      planets().filter((p) => p.id !== n.id).map((p) => h('option', { value: p.id, selected: p.id === n.parent }, titleOf(p.id).slice(0, 50))));
    out.push(h('div', { class: 'row' }, 'Move under', parentSel, h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/move`, { parent: parentSel.value }), 'Moved') }, 'Move')));
    if (sameProject.length) {
      const clSel = h('select', null, h('option', { value: '' }, '(no cluster)'),
        sameProject.map(([cid, c]) => h('option', { value: cid, selected: cid === n.cluster }, c.name.slice(0, 50))));
      out.push(h('div', { class: 'row' }, 'Cluster', clSel, h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/cluster`, { cluster_id: clSel.value || null }), 'Cluster updated') }, 'Set')));
    }

    out.push(h('h3', null, `Reviewers (${reviews.length})`));
    if (!reviews.length) out.push(h('div', { class: 'muted' }, 'None. "Add reviewer" attaches an outside reviewer satellite.'));
    for (const rv of reviews) out.push(reviewBlock(rv));

    out.push(h('h3', null, 'Pulls'));
    if (!pullsIn.length && !pullsOut.length) out.push(h('div', { class: 'muted' }, 'None. Drag a planet onto another to pull context.'));
    for (const p of pullsIn) out.push(h('div', null, '<- ', nodeOrCluster(p.source), ` (${p.level})`));
    for (const p of pullsOut) out.push(h('div', null, '-> ', nodeLink(p.target), ` (${p.level})`));

    if (s.session_id) {
      const tr = state.transcripts[s.session_id];
      out.push(h('h3', null, 'Transcript preview'));
      if (!tr) out.push(h('button', { class: 'small', onclick: () => loadTranscript(s.session_id) }, 'Preview transcript'));
      else if (tr.loading) out.push(h('div', null, h('span', { class: 'spin' }), 'loading...'));
      else if (tr.error) out.push(h('div', { class: 'error' }, tr.error));
      else out.push(h('pre', null, tr.text + (tr.truncated ? `\n\n... (${tr.total_chars} chars total)` : '')), h('button', { class: 'small', onclick: () => { delete state.transcripts[s.session_id]; renderPanel(true); } }, 'Hide'));
    }
    return out;
  }

  function nodeOrCluster(id) {
    if (clusters()[id]) return h('span', { class: 'link', onclick: () => select({ type: 'cluster', id }) }, 'cluster: ' + titleOf(id));
    return nodeLink(id);
  }

  async function loadTranscript(sid) {
    state.transcripts[sid] = { loading: true };
    renderPanel(true);
    try {
      state.transcripts[sid] = await api('GET', `/api/sessions/${enc(sid)}/transcript`);
    } catch (e) {
      state.transcripts[sid] = { error: e.message };
    }
    renderPanel(true);
  }

  function reviewBlock(rv) {
    const running = busy('reviews', rv.id);
    const status = running && rv.status === 'pending' ? 'running' : rv.status;
    const kids = [
      h('div', null, h('b', null, status.toUpperCase()), ' - ', rv.reviewer === 'fresh' ? 'fresh agent' : nodeLink(rv.reviewer), rv.include === 'summary' ? ' - with summary' : ' - problem only'),
      h('div', { class: 'muted' }, rv.problem.length > 240 ? rv.problem.slice(0, 239) + '...' : rv.problem),
    ];
    if (status === 'pending' || status === 'running') kids.push(h('div', null, h('span', { class: 'spin' }), 'reviewing...'));
    if (status === 'error') {
      kids.push(h('div', { class: 'error' }, rv.error || 'failed'));
      kids.push(h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/reviews/${enc(rv.id)}/run`), 'Retrying review') }, 'Retry'));
    }
    if (status === 'done') {
      const prompt = state.reviewPrompts[rv.id];
      if (!prompt) {
        api('GET', `/api/reviews/${enc(rv.id)}/prompt`).then((r) => {
          state.reviewPrompts[rv.id] = r.prompt;
          renderPanel(false);
        }).catch(() => {});
      } else {
        kids.push(h('pre', null, prompt), h('button', { class: 'small primary', onclick: () => copyText(prompt) }, 'Copy prompt'));
      }
    }
    return h('div', { class: 'review ' + status }, kids);
  }

  function cloudPanel(n) {
    const working = busy('instantiate', n.id) || state.pending['inst:' + n.id];
    let palette = n.palette;
    const note = h('input', { value: n.note || '', placeholder: 'name / intent', style: 'flex:1' });
    const out = [
      h('h2', null, titleOf(n.id)),
      h('div', { class: 'muted' }, 'CLOUD - staged, not yet a conversation'),
      kv([
        ['Parent', nodeLink(n.parent)],
        ['Method', n.method],
        ['Staged', fmtDate(n.created)],
        ['Project', shortProject(n.project)],
      ]),
    ];
    if (n.error) out.push(h('div', { class: 'error' }, 'Last attempt failed: ' + n.error));
    out.push(
      h('h3', null, 'Note'),
      h('div', { class: 'row' }, note, h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/cloud`, { note: note.value }), 'Renamed') }, 'Save')),
      h('h3', null, 'Palette'),
      swatches(palette, (id) => {
        palette = id;
        act(() => api('POST', `/api/nodes/${enc(n.id)}/cloud`, { palette: id }));
      }),
      h('h3', null, 'Instantiate'),
    );
    out.push(...sideBySideSection(n));
    if (working) out.push(h('div', null, h('span', { class: 'spin' }), 'Starting forked conversation (claude --resume --fork-session)...'));
    out.push(h('div', { class: 'row' },
      h('button', { class: 'primary', disabled: !!working, onclick: () => instantiate(n.id, palette) }, 'Instantiate conversation'),
      h('button', { class: 'danger', disabled: !!working, onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/discard`), 'Discarded').then(() => select(null)) }, 'Discard'),
    ));
    return out;
  }

  async function instantiate(id, palette) {
    state.pending['inst:' + id] = true;
    renderPanel(true);
    try {
      await api('POST', `/api/nodes/${enc(id)}/instantiate`, { palette: palette || null });
      toast('Instantiated: the cloud is now a planet', 'info');
    } catch (e) {
      toast(e.message);
    } finally {
      delete state.pending['inst:' + id];
      await refresh(true);
      renderPanel(true);
    }
  }

  function clusterPanel(cid) {
    const c = clusters()[cid];
    const open = clusterOpen(cid);
    const naming = busy('model_name', cid) || state.pending['name:' + cid];
    const name = h('input', { value: c.name, style: 'flex:1' });
    const out = [
      h('h2', null, c.name),
      h('div', { class: 'muted' }, `CLUSTER - ${c.members.length} planets - ${shortProject(c.project)}`),
      h('div', { class: 'row' },
        h('button', { class: 'small', onclick: () => {
          if (open) {
            state.expanded.delete(cid);
            state.collapsedByUser.add(cid);
          } else {
            state.collapsedByUser.delete(cid);
            state.expanded.add(cid);
          }
          relayout();
          renderPanel(true);
        } }, open ? 'Collapse' : 'Expand'),
        h('button', { class: 'small', onclick: () => openPullDialog(cid, null) }, 'Pull cluster into...'),
      ),
      h('h3', null, 'Name (5-10 words)'),
      h('div', { class: 'row' }, name, h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/clusters/${enc(cid)}/rename`, { name: name.value }), 'Renamed') }, 'Rename')),
      h('div', { class: 'row' },
        h('button', { class: 'small', disabled: !!naming, onclick: () => modelName(cid) }, naming ? 'Naming...' : 'Name with model'),
        naming ? h('span', { class: 'spin' }) : null,
        h('button', { class: 'small danger', onclick: () => confirm('Dissolve this cluster? Planets stay in the tree.') && act(() => api('POST', `/api/clusters/${enc(cid)}/dissolve`), 'Dissolved').then(() => select(null)) }, 'Dissolve'),
      ),
      h('h3', null, 'Members'),
    ];
    for (const m of c.members) {
      out.push(h('div', { class: 'row' }, nodeLink(m),
        h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(m)}/cluster`, { cluster_id: null }), 'Removed from cluster') }, 'remove')));
    }
    return out;
  }

  async function modelName(cid) {
    state.pending['name:' + cid] = true;
    renderPanel(true);
    try {
      const r = await api('POST', `/api/clusters/${enc(cid)}/model_name`);
      toast('Named: ' + r.name, 'info');
    } catch (e) {
      toast(e.message);
    } finally {
      delete state.pending['name:' + cid];
      await refresh(true);
      renderPanel(true);
    }
  }

  // ---------- sun panel ----------

  async function loadSun() {
    try {
      state.sun.data = await api('GET', '/api/sun');
    } catch (e) {
      toast(e.message);
    }
    renderPanel(true);
  }

  async function toggleSunFile(path, project) {
    const open = state.sun.open;
    if (open.has(path)) open.delete(path);
    else {
      open.add(path);
      if (!state.sun.files[path]) {
        try {
          const q = `path=${enc(path)}${project ? '&project=' + enc(project) : ''}`;
          state.sun.files[path] = await api('GET', `/api/sun/file?${q}`);
        } catch (e) {
          state.sun.files[path] = { content: 'Error: ' + e.message };
        }
      }
    }
    renderPanel(true);
  }

  function sunFileRows(files, project) {
    if (!files.length) return [h('div', { class: 'muted' }, '(no files)')];
    return files.map((f) => {
      const open = state.sun.open.has(f.path);
      const name = f.path.split('/').slice(-2).join('/');
      const row = h('div', { class: 'file-row', title: f.path, onclick: () => f.exists && toggleSunFile(f.path, project) },
        (open ? 'v ' : '> '), h('span', { class: 'grp' }, f.group + ' '), name, f.exists ? ` (${fmtMB(f.size)})` : ' (missing)');
      const loaded = state.sun.files[f.path];
      return [row, open ? h('pre', null, loaded ? loaded.content : 'loading...') : null];
    });
  }

  function sunPanel() {
    const d = state.sun.data;
    const focus = state.focusPlanet && nodes()[state.focusPlanet];
    const focusProject = focus ? focus.project : null;
    const out = [h('h2', null, 'The Sun'), h('div', { class: 'muted' }, 'What sessions load: overall layer + one section per project. Read-only.')];
    if (focus) {
      out.push(h('div', { class: 'row' }, 'Highlighting what ', nodeLink(focus.id), ' loads.',
        h('button', { class: 'small', onclick: () => { state.focusPlanet = null; renderPanel(true); } }, 'clear')));
    }
    if (!d) return [...out, h('div', null, h('span', { class: 'spin' }), 'loading...')];
    out.push(h('div', { class: 'box' + (focus ? ' hl' : '') }, h('h3', null, 'Overall (every session)'), sunFileRows(d.overall, null)));
    out.push(h('h3', null, 'Projects'));
    const projects = Object.keys(d.projects).sort((a, b) => (b === focusProject) - (a === focusProject) || a.localeCompare(b));
    for (const p of projects) {
      const hl = p === focusProject;
      const open = hl || state.sun.projectsOpen.has(p);
      const head = h('div', { class: 'file-row', onclick: () => {
        if (state.sun.projectsOpen.has(p)) state.sun.projectsOpen.delete(p);
        else state.sun.projectsOpen.add(p);
        renderPanel(true);
      } }, open ? 'v ' : '> ', h('b', null, shortProject(p)), ` (${d.projects[p].length} files)`);
      out.push(h('div', { class: 'box' + (hl ? ' hl' : '') }, head, open ? sunFileRows(d.projects[p], p) : null));
    }
    return out;
  }

  // ---------- modals ----------

  function openModal(...content) {
    $('#modal').replaceChildren(...content.flat());
    $('#modal-back').classList.remove('hidden');
  }

  function closeModal() {
    $('#modal-back').classList.add('hidden');
    $('#modal').replaceChildren();
  }

  $('#modal-back').addEventListener('mousedown', (e) => {
    if (e.target.id === 'modal-back') closeModal();
  });

  function promptResult(title, prompt, extra) {
    openModal(
      h('h2', null, title),
      extra || null,
      h('pre', null, prompt),
      h('div', { class: 'row' }, h('button', { class: 'primary', onclick: () => copyText(prompt) }, 'Copy to clipboard'), h('button', { onclick: closeModal }, 'Close')),
    );
    copyText(prompt);
  }

  function openForkDialog(n) {
    const note = h('input', { placeholder: 'intent for this branch (optional)', style: 'width:100%' });
    let palette = n.palette;
    openModal(
      h('h2', null, 'Fork: stage a cloud'),
      h('div', { class: 'muted' }, `Branch from "${titleOf(n.id)}". Nothing runs until you instantiate the cloud.`),
      h('h3', null, 'Note'), note,
      h('h3', null, 'Palette'), swatches(palette, (id) => { palette = id; }),
      h('div', { class: 'row', style: 'margin-top:10px' },
        h('button', { class: 'primary', onclick: async () => {
          const r = await act(() => api('POST', `/api/nodes/${enc(n.id)}/stage`, { method: 'fork', note: note.value, palette: palette || null }), 'Cloud staged');
          closeModal();
          if (r) select({ type: 'node', id: r.node_id });
        } }, 'Stage cloud'),
        h('button', { onclick: closeModal }, 'Cancel')),
    );
    note.focus();
  }

  function sideBySideSection(n) {
    const siblings = Object.values(nodes()).filter((m) => m.id !== n.id && m.parent === n.parent && (m.kind === 'planet' || m.kind === 'cloud'));
    const mates = n.group ? siblings.filter((m) => m.group === n.group) : [];
    const out = [h('h3', null, 'Side by side')];
    if (mates.length) {
      out.push(h('div', { class: 'muted' }, 'Shares one branch with: '), h('div', null, mates.map((m) => h('div', null, nodeLink(m.id)))));
    } else {
      out.push(h('div', { class: 'muted' }, 'Put this next to a sibling on one shared branch.'));
    }
    const candidates = siblings.filter((m) => !n.group || m.group !== n.group);
    const row = h('div', { class: 'row' });
    if (candidates.length) {
      const sel = h('select', null, candidates.map((m) => h('option', { value: m.id }, titleOf(m.id).slice(0, 50))));
      row.append(sel, h('button', { class: 'small', onclick: () => act(() => api('POST', '/api/groups', { node_ids: [n.id, sel.value] }), 'Placed side by side') }, 'Join'));
    } else if (!mates.length) {
      out.push(h('div', { class: 'muted' }, 'No siblings under the same parent yet.'));
    }
    if (n.group) row.append(h('button', { class: 'small', onclick: () => act(() => api('POST', `/api/nodes/${enc(n.id)}/ungroup`), 'Separated') }, 'Separate'));
    if (row.childNodes.length) out.push(row);
    return out;
  }

  function openSplitDialog(n) {
    const ta = h('textarea', { rows: 5, placeholder: 'one focus per line, e.g.\nfrontend\nbackend' });
    openModal(
      h('h2', null, 'Split'),
      h('div', { class: 'muted' }, 'Stages one fork cloud per focus (2+). You instantiate each one; nothing runs automatically.'),
      ta,
      h('div', { class: 'row', style: 'margin-top:10px' },
        h('button', { class: 'primary', onclick: async () => {
          const focuses = ta.value.split('\n').map((x) => x.trim()).filter(Boolean);
          const r = await act(() => api('POST', `/api/nodes/${enc(n.id)}/split`, { focuses }));
          if (r) {
            toast(`Staged ${r.node_ids.length} clouds`, 'info');
            closeModal();
          }
        } }, 'Stage clouds'),
        h('button', { onclick: closeModal }, 'Cancel')),
    );
    ta.focus();
  }

  function openPullDialog(source, target) {
    const isCluster = !!clusters()[source];
    const targets = planets().filter((p) => p.id !== source);
    if (!targets.length) return toast('No target planet available');
    const sel = h('select', null, targets.map((p) => h('option', { value: p.id, selected: p.id === target }, titleOf(p.id).slice(0, 60))));
    let level = 'compacted';
    const levels = isCluster
      ? h('div', { class: 'muted' }, 'Cluster pull: a brief summary of each member. Pull a member individually for more detail.')
      : h('div', null, Object.entries(LEVEL_NAMES).map(([k, label]) => h('label', null,
        h('input', { type: 'radio', name: 'level', value: k, checked: k === level, onchange: () => { level = k; } }), ' ', label)));
    const status = h('div');
    const go = h('button', { class: 'primary' }, 'Pull');
    go.addEventListener('click', async () => {
      go.disabled = true;
      status.replaceChildren(h('span', { class: 'spin' }), level === 'full' && !isCluster ? 'writing pull file...' : 'summarizing (model call)...');
      try {
        const r = await api('POST', '/api/pull', { source, target: sel.value, level: isCluster ? 'compacted' : level });
        await refresh(true);
        promptResult('Pull ready: paste into the target session', r.prompt, h('div', { class: 'muted' }, `${r.file} (${r.chars} chars)`));
      } catch (e) {
        go.disabled = false;
        status.replaceChildren(h('div', { class: 'error' }, e.message));
      }
    });
    const canMove = !isCluster && target;
    openModal(
      h('h2', null, 'Pull context'),
      h('div', null, 'From: ', h('b', null, (isCluster ? 'cluster: ' : '') + titleOf(source))),
      h('div', { class: 'row' }, 'Into:', sel),
      h('h3', null, 'Amount'), levels, status,
      h('div', { class: 'row', style: 'margin-top:10px' }, go, h('button', { onclick: closeModal }, 'Cancel'),
        canMove ? h('button', { class: 'small', onclick: async () => {
          closeModal();
          await act(() => api('POST', `/api/nodes/${enc(source)}/move`, { parent: sel.value }), 'Moved');
        } }, 'Move under target instead') : null),
    );
  }

  function openReviewDialog(n) {
    const who = h('select', null, h('option', { value: 'fresh' }, 'Fresh agent (brand-new session)'),
      planets().filter((p) => p.id !== n.id).map((p) => h('option', { value: p.id }, 'Fork of: ' + titleOf(p.id).slice(0, 50))));
    const problem = h('textarea', { rows: 5, placeholder: 'What should the reviewer attack?' });
    const include = h('input', { type: 'checkbox', checked: true });
    openModal(
      h('h2', null, 'Add outside reviewer'),
      h('div', { class: 'muted' }, `Reviews the problem of "${titleOf(n.id)}" with its own context. Several can run at once.`),
      h('h3', null, 'Reviewer'), who,
      h('h3', null, 'Problem'), problem,
      h('label', null, include, ' include a short summary of this session'),
      h('div', { class: 'row', style: 'margin-top:10px' },
        h('button', { class: 'primary', onclick: async () => {
          const r = await act(() => api('POST', '/api/reviews', { target: n.id, problem: problem.value, reviewer: who.value, include: include.checked ? 'summary' : 'none' }), 'Reviewer launched');
          if (r) closeModal();
        } }, 'Start review'),
        h('button', { onclick: closeModal }, 'Cancel')),
    );
    problem.focus();
  }

  async function openClustersDialog() {
    openModal(h('h2', null, 'Cluster proposals'), h('div', null, h('span', { class: 'spin' }), 'grouping by topic names...'));
    let proposals;
    try {
      proposals = await api('GET', '/api/clusters/proposals');
    } catch (e) {
      return openModal(h('h2', null, 'Cluster proposals'), h('div', { class: 'error' }, e.message));
    }
    if (!proposals.length) {
      return openModal(h('h2', null, 'Cluster proposals'), h('div', { class: 'muted' }, 'No proposals: a cluster needs enough planets in one project with related topic names.'), h('button', { onclick: closeModal }, 'Close'));
    }
    const blocks = proposals.map((p) => {
      const name = h('input', { value: p.name, style: 'width:100%' });
      const box = h('div', { class: 'box' },
        h('div', { class: 'muted' }, shortProject(p.project) + ` - ${p.members.length} planets`),
        name,
        h('div', { style: 'font-size:11px;margin:4px 0' }, p.members.map((m) => titleOf(m)).join(' | ')),
        h('button', { class: 'small primary', onclick: async (e) => {
          const r = await act(() => api('POST', '/api/clusters', { project: p.project, name: name.value, members: p.members }), 'Cluster created');
          if (r) {
            e.target.disabled = true;
            e.target.textContent = 'accepted';
          }
        } }, 'Accept'));
      return box;
    });
    openModal(
      h('h2', null, `Cluster proposals (${proposals.length})`),
      blocks,
      h('div', { class: 'row' },
        h('button', { class: 'primary', onclick: async () => {
          await act(() => api('POST', '/api/clusters/accept'), 'All proposals accepted');
          closeModal();
        } }, 'Accept all'),
        h('button', { onclick: closeModal }, 'Close')),
    );
  }

  // ---------- drop bin ----------

  async function placeSession(sid, parent) {
    await act(() => api('POST', '/api/place', { session_id: sid, parent }), 'Placed under ' + titleOf(parent));
  }

  const suggestObserver = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      const sid = en.target.dataset.sid;
      suggestObserver.unobserve(en.target);
      loadSuggest(sid, en.target);
    }
  }, { root: null });

  async function loadSuggest(sid, item) {
    const key = sid + '|' + (state.pulse ? state.pulse.mtime : 0);
    let list = state.suggest[key];
    if (!list) {
      try {
        list = await api('GET', `/api/sessions/${enc(sid)}/suggest`);
        state.suggest[key] = list;
      } catch (e) {
        list = [];
      }
    }
    const box = item.querySelector('.sugg');
    if (!box) return;
    box.replaceChildren(...list.map((sg) => h('div', {
      title: `${sg.title} (score ${sg.score}${sg.reasons.length ? '; ' + sg.reasons.join(', ') : ''})`,
      onclick: (e) => {
        e.stopPropagation();
        placeSession(sid, sg.parent);
      },
    }, '-> ', sg.parent === 'sun' ? 'SUN (top level)' : sg.title)));
  }

  const TIER_GLYPH = { 1: '●', 2: '◉', 3: '⬤' };

  function listRows() {
    const ns = nodes();
    const cs = clusters();
    const filter = ($('#list-filter').value || '').trim().toLowerCase();
    const live = Object.fromEntries(Object.entries(ns).filter(([, n]) => n.kind === 'planet' || n.kind === 'cloud'));
    const children = {};
    for (const [id, n] of Object.entries(live)) {
      const parent = live[n.parent] ? n.parent : 'sun';
      (children[parent] = children[parent] || []).push(id);
    }
    const byCreated = (a, b) => (live[a].created || '').localeCompare(live[b].created || '');
    for (const [pid, kids] of Object.entries(children)) {
      kids.sort(byCreated);
      const out = [];
      for (const id of kids) {
        if (out.includes(id)) continue;
        const g = live[id].group;
        out.push(...(g ? kids.filter((m) => live[m].group === g) : [id]));
      }
      children[pid] = out;
    }
    const clusterTop = {};
    for (const [cid, c] of Object.entries(cs)) {
      const members = new Set(c.members);
      for (const m of c.members) if (live[m] && !members.has(live[m].parent)) clusterTop[m] = cid;
    }
    let keep = new Set(Object.keys(live));
    if (filter) {
      keep = new Set();
      const matched = Object.keys(live).filter((id) => titleOf(id).toLowerCase().includes(filter) || (live[id].note || '').toLowerCase().includes(filter));
      for (const [cid, c] of Object.entries(cs)) if (c.name.toLowerCase().includes(filter)) matched.push(...c.members.filter((m) => live[m]));
      for (let id of matched) {
        while (live[id] && !keep.has(id)) {
          keep.add(id);
          id = live[id].parent;
        }
      }
    }
    const rows = [{ id: 'sun', type: 'sun', depth: 0 }];
    const add = (id, depth) => {
      rows.push({ id, type: live[id].kind, depth });
      if (state.listCollapsed.has(id)) return;
      for (const kid of children[id] || []) if (keep.has(kid) && !clusterTop[kid]) add(kid, depth + 1);
    };
    for (const [cid, c] of Object.entries(cs)) {
      const tops = c.members.filter((m) => clusterTop[m] === cid && keep.has(m)).sort(byCreated);
      if (!tops.length) continue;
      rows.push({ id: cid, type: 'cluster', depth: 1 });
      if (!state.listCollapsed.has(cid)) for (const m of tops) add(m, 2);
    }
    for (const id of children.sun || []) if (keep.has(id) && !clusterTop[id]) add(id, 1);
    return { rows, children };
  }

  function listLabel(row) {
    const n = nodes()[row.id];
    if (row.type === 'sun') return [h('span', { class: 'g', style: 'color:var(--c10)' }, '☀'), ' SUN'];
    if (row.type === 'cluster') {
      const c = clusters()[row.id];
      return [h('span', { class: 'g', style: 'color:var(--c14)' }, '▣'), ` ${c.name} (${c.members.length})`];
    }
    if (row.type === 'cloud') return [n.group ? h('span', { class: 'gb' }, '┃') : null, h('span', { class: 'g' }, '☁'), ' ', h('i', null, n.note || 'cloud'), n.error ? h('span', { style: 'color:var(--c8)' }, ' ✗') : null];
    const sig = (state.view && state.view.signals) || {};
    const col = (n.colors && n.colors[0]) || 'var(--c6)';
    return [
      n.group ? h('span', { class: 'gb' }, '┃') : null,
      h('span', { class: 'g', style: `color:${col}` }, sig.planet_size === false ? '●' : TIER_GLYPH[n.tier] || '●'),
      sig.planet_size === false ? ' ' : h('span', { class: 'pct' }, ` ${Math.round(n.context_pct || 0)}% `),
      titleOf(row.id),
      n.badge ? h('span', { style: 'color:var(--c8)' }, ' [J]') : null,
      n.sun_drift ? h('span', { style: 'color:var(--c10)' }, ' Δsun') : null,
    ];
  }

  function renderList() {
    if (!state.view) return;
    const { rows, children } = listRows();
    const sel = state.selected && state.selected.id;
    const sig = JSON.stringify([rows, sel, state.view.mtime, state.view.busy, [...state.listCollapsed]]);
    if (sig === state.listSig) return;
    state.listSig = sig;
    const wrap = $('#list-items');
    const scroll = wrap.scrollTop;
    wrap.replaceChildren(...rows.map((row) => {
      const hasKids = row.type === 'cluster' || (children[row.id] || []).length > 0;
      const collapsed = state.listCollapsed.has(row.id);
      const toggle = row.type !== 'sun' && hasKids
        ? h('span', { class: 'tog', onclick: (e) => {
            e.stopPropagation();
            if (collapsed) state.listCollapsed.delete(row.id);
            else state.listCollapsed.add(row.id);
            renderList();
          } }, collapsed ? '▸' : '▾')
        : h('span', { class: 'tog' }, ' ');
      return h('div', {
        class: `li li-${row.type}${row.id === sel ? ' sel' : ''}`,
        style: `padding-left:${6 + row.depth * 12}px`,
        'data-id': row.id,
        onmouseenter: () => {
          state.listHover = row.id;
          panTo(row.id);
          state._dirty = true;
        },
        onmouseleave: () => {
          if (state.listHover === row.id) state.listHover = null;
          state._dirty = true;
        },
        onclick: () => {
          if (row.type === 'sun') select({ type: 'sun', id: 'sun' });
          else if (row.type === 'cluster') select({ type: 'cluster', id: row.id });
          else select({ type: 'node', id: row.id });
          panTo(row.id);
        },
        ondblclick: () => {
          if (row.type === 'planet') copyResume(row.id);
        },
      }, toggle, ...listLabel(row));
    }));
    wrap.scrollTop = scroll;
  }

  function renderBin() {
    const v = state.view;
    const filter = $('#bin-filter').value.trim().toLowerCase();
    const items = (v.bin || []).filter((b) => !filter || (b.title + ' ' + b.project + ' ' + b.first_prompt).toLowerCase().includes(filter));
    const sig = JSON.stringify([filter, v.mtime, items.map((b) => [b.session_id, b.title, b.context_pct])]);
    $('#bin-count').textContent = `${(v.bin || []).length} unplaced`;
    if (sig === state.binSig) return;
    state.binSig = sig;
    const wrap = $('#bin-items');
    const scroll = wrap.scrollLeft;
    wrap.replaceChildren(...items.map((b) => {
      const el = h('div', { class: 'bin-item', draggable: 'true', 'data-sid': b.session_id },
        h('div', { class: 't' }, b.title),
        h('div', { class: 'm' }, `${shortProject(b.project)} - ${fmtDate(b.created)}`),
        h('div', { class: 'm' }, `${b.context_pct}% ctx - ${fmtMB(b.file_size)}`),
        h('div', { class: 'sugg' }, h('span', { class: 'muted' }, '...')));
      el.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/webtree-session', b.session_id);
        e.dataTransfer.effectAllowed = 'move';
        hideTip();
      });
      el.addEventListener('mouseenter', (e) => binHover(b, e));
      el.addEventListener('mousemove', moveTip);
      el.addEventListener('mouseleave', () => {
        binHoverId = null;
        hideTip();
      });
      suggestObserver.observe(el);
      return el;
    }));
    wrap.scrollLeft = scroll;
  }

  let binHoverId = null;
  function binHover(b, e) {
    binHoverId = b.session_id;
    const content = () => {
      const sm = state.summaries[b.session_id];
      return [
        h('div', { class: 't' }, b.title),
        h('div', { class: 'n' }, `${shortProject(b.project)} - ${b.git_branch || ''}`),
        h('div', null, `Lifetime ${fmtTokens(b.lifetime_tokens)} tokens - ${fmtMB(b.file_size)} - ${b.context_pct}% ctx`),
        sm && sm.text ? h('div', null, 'Summary: ' + sm.text) : h('div', { class: 'muted' }, (b.first_prompt || '').slice(0, 300) || '(no prompt)'),
      ];
    };
    showTip(content(), e);
    if (!state.summaries[b.session_id]) {
      api('GET', `/api/sessions/${enc(b.session_id)}/summary?level=brief&cached_only=true`).then((r) => {
        if (r.summary) state.summaries[b.session_id] = { text: r.summary };
        if (binHoverId === b.session_id) showTip(content(), null);
      }).catch(() => {});
    }
  }

  $('#bin-filter').addEventListener('input', () => renderBin());
  $('#bin-items').addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      $('#bin-items').scrollLeft += e.deltaY;
      e.preventDefault();
    }
  }, { passive: false });

  // ---------- settings + toolbar ----------

  function renderSettings() {
    const box = $('#settings');
    if (!box.classList.contains('hidden') && box.contains(document.activeElement)) return;
    const sig = (state.view && state.view.signals) || {};
    const labels = { planet_size: 'Planet size by context window', jupiter_badge: 'Badge at Jupiter tier' };
    box.replaceChildren(
      h('div', { class: 'muted' }, 'SIGNALS'),
      Object.entries(sig).map(([k, v]) => h('label', null,
        h('input', { type: 'checkbox', checked: !!v, onchange: (e) => act(() => api('POST', '/api/signals', { name: k, enabled: e.target.checked })) }),
        ' ', labels[k] || k)),
      h('div', { class: 'muted', style: 'margin-top:6px' }, 'DISPLAY'),
      h('label', null, h('input', { type: 'checkbox', checked: state.showLabels, onchange: (e) => { state.showLabels = e.target.checked; state._dirty = true; } }), ' Labels'),
      h('label', null, h('input', { type: 'checkbox', checked: state.animate, onchange: (e) => { state.animate = e.target.checked; state._dirty = true; } }), ' Animation'),
    );
  }

  $('#btn-settings').addEventListener('click', () => $('#settings').classList.toggle('hidden'));
  document.addEventListener('mousedown', (e) => {
    if (!e.target.closest('.menu')) $('#settings').classList.add('hidden');
  });
  $('#btn-fit').addEventListener('click', fit);
  $('#list-filter').addEventListener('input', renderList);
  $('#btn-zoom-in').addEventListener('click', () => setZoom(state.z * BUTTON_ZOOM_STEP));
  $('#btn-zoom-out').addEventListener('click', () => setZoom(state.z / BUTTON_ZOOM_STEP));
  $('#btn-clusters').addEventListener('click', openClustersDialog);
  $('#btn-sun').addEventListener('click', () => select({ type: 'sun', id: 'sun' }));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('#modal-back').classList.contains('hidden')) closeModal();
      else select(null);
    }
  });

  new ResizeObserver(resize).observe($('#sky-wrap'));
  resize();
  refresh(true);
  setInterval(() => refresh(false), PULSE_MS);
  requestAnimationFrame(loop);
})();
