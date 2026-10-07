import { getJSON, esc, n0, n1, pct, usd, usdK, dshort, dmon, addDays, chip, whName, lineChart, hBars, on } from '../lib.js';
import { openSku } from '../sku.js';

export async function render(root) {
  const [ex, ov] = await Promise.all([getJSON('exceptions.json'), getJSON('overview.json')]);
  const ep = ex.phantom_episodes[0];
  const open = ep && ep.last_alert_date >= addDays(ex.as_of, -3);
  let phantom = '';
  if (ep) {
    const sw = ex.stuck_weekly, weeks = sw.weeks;
    const wh = ep.wh_code;
    const others = weeks.map(w => Math.max(...Object.keys(sw.series).filter(k => k !== wh).map(k => sw.series[k][w]?.[0] ?? 0)));
    const mine = weeks.map(w => sw.series[wh][w]?.[0] ?? null);
    const winStart = addDays(ep.est_start, -90), winEnd = addDays(ep.last_alert_date, 60);
    const keep = weeks.map((w, i) => (w >= winStart && w <= winEnd ? i : -1)).filter(i => i >= 0);
    const wk = keep.map(i => weeks[i]);
    const nearest = d => wk.reduce((b, w) => (Math.abs(new Date(w) - new Date(d)) < Math.abs(new Date(b) - new Date(d)) ? w : b), wk[0]);
    phantom = `
      <div class="banner ${open ? 'bad' : 'warn'}"><div class="row"><h3>Phantom stock at ${esc(ep.wh_name)}</h3>${chip(open ? 'OPEN' : 'RESOLVED', open ? 'bad' : 'good')}</div>
        <p style="margin:6px 0 0">Orders kept arriving for ${n0(ep.affected_skus)} items, and the system kept saying they were in stock, but the orders did not ship. The stock had gone and nothing had recorded it.</p>
        <div class="kv"><div><div class="k">Trouble began</div><div class="v">${dshort(ep.est_start)}</div></div><div><div class="k">Alert raised</div><div class="v">${dshort(ep.alert_date)}</div></div>
          <div><div class="k">Orders stuck</div><div class="v num">${n0(ep.stuck_order_lines)} · ${usdK(ep.stuck_order_value)}</div></div><div><div class="k">Book value at risk</div><div class="v num">${usdK(ep.book_value_at_risk)}</div></div></div>
        ${open ? '' : `<p class="note" style="margin:10px 0 0">The alert cleared on ${dshort(ep.last_alert_date)} as the stuck orders shipped.</p>`}
        ${ep.first_confirming_count ? `<p class="note" style="margin:10px 0 0">A physical count confirmed it on <b>${dshort(ep.first_confirming_count)}</b>, ${n0(ep.alert_days_before_count)} days after this alert fired. The alert needs no count: it watches for orders that sit unshipped while the books say the stock is there.</p>` : ''}</div>
      <div class="card"><h3>Orders stuck while the book said “in stock”</h3><p class="sub">Weekly average of order lines older than 7 days and still unshipped. Dashed line: the alert threshold learned from the first year of history.</p>
        ${lineChart([{ name: ep.wh_name, color: 'var(--series3)', values: keep.map(i => mine[i]), width: 2.4 }, { name: 'Busiest other warehouse', color: 'var(--series2)', values: keep.map(i => others[i]) }], wk,
          { thresholds: [{ y: sw.threshold[wh], label: 'alert threshold' }], markers: [{ x: nearest(ep.est_start), label: 'began', color: 'var(--ink)' }, { x: nearest(ep.alert_date), label: 'alert', color: 'var(--bad)', dy: 12 }], xFmt: dmon, ticks: 5, label: 'Stuck order lines per week' })}</div>
      <div class="sec"><h2>Items affected</h2><p class="sub">The largest of ${n0(ep.affected_skus)} items with three or more stuck orders. Tap one to see its stock history.</p>
        <div class="card pad0"><ul class="list">${ex.phantom_skus.slice(0, 8).map(s => `<li style="padding:0"><button class="li-btn" data-item="${esc(s.item_no)}" data-wh="${ep.wh_code}"><div class="row"><span class="t">${esc(s.description)}</span><span class="num"><b>${usdK(s.stuck_value)}</b></span></div>
          <div class="row"><span class="m">${esc(s.item_no)} · ${n0(s.stuck_lines)} stuck orders since ${dshort(s.first_stuck_order)}</span><span class="m num">book said ${n0(s.book_qty_on_alert)}</span></div></button></li>`).join('')}</ul></div></div>`;
  }
  const q = ex.review_queue;
  const totalQ = q.reduce((a, r) => a + r.n, 0);
  const byOwner = Object.entries(q.reduce((m, r) => (m[r.owner] = (m[r.owner] || 0) + r.n, m), {})).sort((a, b) => b[1] - a[1]);
  root.innerHTML = `
    <h1 class="view-title">Exceptions</h1>
    <p class="lede">What the pipeline would not decide for itself, and what it caught that no single system could. Nothing here has been silently dropped or guessed.</p>
    ${phantom || '<div class="banner good"><h3>No phantom-stock episodes</h3></div>'}
    <div class="sec"><h2>Handled automatically, with a trail</h2><div class="card pad0"><ul class="list">${ex.handling_summary.map(h => `<li><div class="row"><span>${esc(h.what)}</span><b class="num">${n0(h.n)}</b></div></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>Waiting for a person: ${n0(totalQ)} items</h2><p class="sub">Every one has a named owner and a suggested action. By owner:</p>
      <div class="card">${hBars(byOwner.map(([o, n]) => ({ label: o, value: n })), { label: 'Review items by owner' })}</div>
      <div class="card pad0" style="margin-top:12px"><ul class="list">${q.map(r => `<li><details><summary style="cursor:pointer;min-height:44px;display:flex;align-items:center;gap:8px;flex-wrap:wrap"><b>${esc(r.reason_code.replace(/_/g, ' ').toLowerCase())}</b> ${chip(n0(r.n), 'mute')} ${chip(r.severity, r.severity === 'warning' ? 'warn' : 'info')} ${chip(r.disposition, 'mute')}</summary>
        <p class="note" style="margin:6px 0">Owner: <b>${esc(r.owner)}</b>. Suggested action: ${esc(r.suggested_action)}.</p>
        ${(ex.review_samples[r.reason_code] || []).map(s => `<div class="note num" style="padding:3px 0;border-top:1px solid var(--line)">${esc(s.source_key)}: ${esc(s.detail)}</div>`).join('')}</details></li>`).join('')}</ul></div></div>`;
  on(root, '[data-item]', 'click', (e, el) => openSku(el.dataset.item, el.dataset.wh));
}
