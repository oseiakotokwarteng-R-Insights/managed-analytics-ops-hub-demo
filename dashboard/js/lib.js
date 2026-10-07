// Small helpers shared by every view: data loading, formatting, DOM building and hand-rolled SVG charts (no libraries).
const cache = new Map();
export function getJSON(name) {
  if (!cache.has(name)) cache.set(name, fetch(`data/${name}`, { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(`${name}: ${r.status}`); return r.json(); }));
  return cache.get(name);
}

export const getOptional = name => getJSON(name).catch(() => null);
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
export const n0 = v => (v == null ? '–' : nf0.format(v));
export const n1 = v => (v == null ? '–' : nf1.format(v));
export const pct = (v, d = 1) => (v == null ? '–' : (v * 100).toFixed(d) + '%');
export const usd = (v, d = 0) => (v == null ? '–' : (v < 0 ? '-$' : '$') + new Intl.NumberFormat('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }).format(Math.abs(v)));
export function usdK(v) {
  if (v == null) return '–';
  const a = Math.abs(v), s = v < 0 ? '-' : '';
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e4) return `${s}$${Math.round(a / 1e3)}k`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}k`;
  return `${s}$${Math.round(a)}`;
}
export const dshort = iso => (iso ? new Date(iso + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }) : '–');
export const dmon = iso => (iso ? new Date(iso + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' }) : '');
export const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

export function html(strings, ...vals) { return strings.reduce((a, s, i) => a + s + (i < vals.length ? vals[i] : ''), ''); }
export const chip = (text, kind = 'mute') => `<span class="chip ${kind}">${esc(text)}</span>`;
export const riskChip = r => ({ ok: chip('OK', 'good'), at_risk: chip('At risk', 'warn'), out_of_stock: chip('Out of stock', 'bad'), low_demand: chip('Slow mover', 'mute') }[r] || chip(r));
export const confChip = c => ({ verified: chip('Counted recently', 'good'), carried: chip('Carried forward', 'info'), suspect: chip('Check this', 'warn') }[c] || chip(c));
export const confShort = c => ({ verified: chip('counted', 'good'), carried: chip('carried', 'info'), suspect: chip('check', 'warn') }[c] || chip(c));
export const WH_NAMES = {};
export const whName = code => WH_NAMES[code] || code;

export function setView(root, markup) { root.innerHTML = markup; }
export function on(root, selector, event, fn) { root.querySelectorAll(selector).forEach(el => el.addEventListener(event, e => fn(e, el))); }

// ---------------------------------------------------------------------------------------------------------------- charts
let W = 640;
const cw = () => Math.max(290, Math.min(640, (document.documentElement.clientWidth || 640) - 56));
function scale(min, max, a, b) { const k = max === min ? 0 : (b - a) / (max - min); return v => a + (v - min) * k; }
function niceMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); const f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; }

// series: [{name, color, values:[...], dashed, width}], x: labels array (ISO dates or strings), opts {h, yFmt, yMin, yMax, thresholds:[{y,label,color}], markers:[{x,label}], area}
export function lineChart(series, x, opts = {}) {
  W = cw();
  const h = opts.h || 190, m = { l: 44, r: 10, t: 10, b: 24 }, n = x.length;
  const vals = series.flatMap(s => s.values.filter(v => v != null));
  const ymin = opts.yMin ?? Math.min(0, ...vals);
  const ymax = opts.yMax ?? niceMax(Math.max(...vals, ...(opts.thresholds || []).map(t => t.y), 0.0001) * 1.05);
  const sx = scale(0, Math.max(1, n - 1), m.l, W - m.r), sy = scale(ymin, ymax, h - m.b, m.t);
  const fmt = opts.yFmt || n0;
  let g = '';
  for (let i = 0; i <= 4; i++) { const v = ymin + (ymax - ymin) * i / 4, y = sy(v); g += `<line class="grid-l" x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}"/><text x="${m.l - 6}" y="${y + 3.5}" text-anchor="end">${esc(fmt(v))}</text>`; }
  const ticks = opts.ticks || 5;
  for (let i = 0; i < ticks; i++) { const idx = Math.round(i * (n - 1) / (ticks - 1)); const lab = opts.xFmt ? opts.xFmt(x[idx]) : x[idx]; g += `<text x="${sx(idx)}" y="${h - 6}" text-anchor="${i === 0 ? 'start' : i === ticks - 1 ? 'end' : 'middle'}">${esc(lab)}</text>`; }
  (opts.thresholds || []).forEach(t => { const y = sy(t.y); g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}" stroke="${t.color || 'var(--bad)'}" stroke-dasharray="5 4" stroke-width="1.3"/><text x="${W - m.r}" y="${y - 4}" text-anchor="end" style="fill:${t.color || 'var(--bad)'}">${esc(t.label || '')}</text>`; });
  (opts.markers || []).forEach(k => { const idx = x.indexOf(k.x); if (idx < 0) return; const xx = sx(idx); g += `<line x1="${xx}" x2="${xx}" y1="${m.t}" y2="${h - m.b}" stroke="${k.color || 'var(--muted)'}" stroke-dasharray="3 3"/><text x="${xx + 4}" y="${m.t + 10 + (k.dy || 0)}" style="fill:${k.color || 'var(--muted)'}">${esc(k.label)}</text>`; });
  series.forEach((s, si) => {
    let d = '', pen = false;
    s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${sx(i).toFixed(1)} ${sy(v).toFixed(1)}`; pen = true; });
    if (opts.area && si === 0) g += `<path d="${d}L${sx(n - 1).toFixed(1)} ${sy(ymin)}L${sx(0).toFixed(1)} ${sy(ymin)}Z" fill="${s.color}" opacity=".12"/>`;
    g += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" ${s.dashed ? 'stroke-dasharray="5 4"' : ''}/>`;
  });
  if (opts.cursor != null) { const xx = sx(opts.cursor); g += `<line x1="${xx}" x2="${xx}" y1="${m.t}" y2="${h - m.b}" stroke="var(--ink)" stroke-width="1.2"/>`; series.forEach(s => { const v = s.values[opts.cursor]; if (v != null) g += `<circle cx="${xx}" cy="${sy(v)}" r="4" fill="${s.color}" stroke="var(--card)" stroke-width="1.5"/>`; }); }
  return `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(opts.label || 'line chart')}">${g}</svg>${legend(series)}`;
}
const legend = series => (series.length > 1 || series[0]?.legend ? `<div class="legend">${series.map(s => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join('')}</div>` : '');

// bars: [{label, value, color, note}]; horizontal bars scale to the container and read well on a phone
export function hBars(rows, opts = {}) {
  const max = opts.max ?? Math.max(...rows.map(r => r.value), 0.0001), fmt = opts.fmt || n0;
  return `<div role="img" aria-label="${esc(opts.label || 'bar chart')}">${rows.map(r => `<div style="margin:9px 0"><div class="row"><span class="t" style="font-weight:600;font-size:.88rem">${esc(r.label)}</span><span class="num" style="font-size:.88rem">${esc(r.text ?? fmt(r.value))}</span></div>` +
    `<div style="height:9px;background:var(--soft);border-radius:5px;margin-top:4px"><div style="height:9px;width:${Math.max(0, Math.min(100, 100 * r.value / max)).toFixed(1)}%;background:${r.color || 'var(--series1)'};border-radius:5px"></div></div>${r.note ? `<div class="note" style="margin-top:2px">${esc(r.note)}</div>` : ''}</div>`).join('')}</div>`;
}

export function colChart(values, labels, opts = {}) {
  W = cw();
  const h = opts.h || 150, m = { l: 36, r: 6, t: 8, b: 22 }, n = values.length, ymax = opts.yMax ?? niceMax(Math.max(...values.filter(v => v != null), 0.0001) * 1.05), fmt = opts.yFmt || n0;
  const ymin = opts.yMin ?? 0, bw = (W - m.l - m.r) / n, sy = scale(ymin, ymax, h - m.b, m.t);
  let g = '';
  for (let i = 0; i <= 3; i++) { const v = ymin + (ymax - ymin) * i / 3, y = sy(v); g += `<line class="grid-l" x1="${m.l}" x2="${W - m.r}" y1="${y}" y2="${y}"/><text x="${m.l - 5}" y="${y + 3.5}" text-anchor="end">${esc(fmt(v))}</text>`; }
  values.forEach((v, i) => { if (v == null) return; const c = opts.colors ? opts.colors[i] : 'var(--series1)'; g += `<rect x="${m.l + i * bw + bw * .15}" y="${sy(Math.max(v, ymin))}" width="${bw * .7}" height="${Math.max(0, h - m.b - sy(Math.max(v, ymin)))}" rx="2" fill="${c}"/>`; });
  const every = Math.ceil(n / (opts.ticks || 6));
  labels.forEach((l, i) => { if (i % every === 0) g += `<text x="${m.l + i * bw + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(l)}</text>`; });
  return `<svg class="chart" viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(opts.label || 'column chart')}">${g}</svg>`;
}

// status string of g/a/r characters, one per night, laid out in weeks (7 rows) like a contribution calendar
export function nightStrip(status) {
  const cells = [...status].map(c => `<i class="${c === 'a' ? 'a' : c === 'r' ? 'r' : ''}"></i>`).join('');
  return `<div class="scroll"><div class="strip" style="min-width:${Math.ceil(status.length / 7) * 7}px" role="img" aria-label="Nightly status history">${cells}</div></div>`;
}
