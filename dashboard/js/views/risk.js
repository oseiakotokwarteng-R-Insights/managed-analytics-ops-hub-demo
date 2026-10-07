import { getJSON, esc, n0, n1, pct, usd, usdK, dshort, chip, riskChip, confChip, whName, hBars, on } from '../lib.js';
import { openSku } from '../sku.js';

const state = { tab: 'risk', wh: 'all', kind: 'all', shown: 20 };

export async function render(root) {
  const [rk, inb, meta] = await Promise.all([getJSON('risk.json'), getJSON('inbound.json'), getJSON('meta.json')]);
  const draw = () => {
    root.innerHTML = `
      <h1 class="view-title">Risk and inbound</h1>
      <p class="lede">What will run out in the next 14 days, what is already out, and whether more is on the way. Suggestions only use warehouses holding more than 45 days of cover.</p>
      <div class="controls"><div class="seg" role="group" aria-label="Section"><button data-tab="risk" aria-pressed="${state.tab === 'risk'}">Run-out risk</button><button data-tab="inbound" aria-pressed="${state.tab === 'inbound'}">Inbound</button></div></div>
      <div id="body"></div>`;
    on(root, '[data-tab]', 'click', (e, el) => { state.tab = el.dataset.tab; state.shown = 20; draw(); });
    (state.tab === 'risk' ? risk : inbound)(root.querySelector('#body'));
  };
  function risk(el) {
    const sum = Object.fromEntries(rk.summary.map(r => [r.risk, r]));
    let rows = rk.rows.filter(r => (state.wh === 'all' || r.wh_code === state.wh) && (state.kind === 'all' || r.risk === state.kind));
    const withT = rows.filter(r => r.transfer_from).length;
    el.innerHTML = `
      <div class="grid c3">
        <div class="card"><div class="k note">WILL RUN OUT WITHIN 14 DAYS</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(sum.at_risk?.pairs)}</div><div class="note">item-warehouse pairs, after counting promised inbound</div></div>
        <div class="card"><div class="k note">ALREADY OUT OF STOCK</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(sum.out_of_stock?.pairs)}</div><div class="note">with recent demand</div></div>
        <div class="card"><div class="k note">TRANSFER AVAILABLE</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(rk.rows.filter(r => r.transfer_from).length)}</div><div class="note">another warehouse has more than 45 days of cover</div></div></div>
      <div class="controls" style="margin-top:14px"><select id="f-wh" aria-label="Warehouse"><option value="all">All warehouses</option>${meta.warehouses.map(w => `<option value="${w.wh_code}" ${state.wh === w.wh_code ? 'selected' : ''}>${esc(w.name)}</option>`).join('')}</select>
        <select id="f-kind" aria-label="Kind"><option value="all">At risk and out</option><option value="at_risk" ${state.kind === 'at_risk' ? 'selected' : ''}>At risk only</option><option value="out_of_stock" ${state.kind === 'out_of_stock' ? 'selected' : ''}>Out of stock only</option></select></div>
      <p class="note">${n0(rows.length)} shown, ${n0(withT)} with a transfer suggestion. Ranked by sales value at risk over the next 14 days.</p>
      <div class="card pad0"><ul class="list">${rows.slice(0, state.shown).map((r, i) => `<li style="padding:0"><button class="li-btn" data-item="${esc(r.item_no)}" data-wh="${r.wh_code}">
        <div class="row"><span class="t">${esc(r.description)}</span>${riskChip(r.risk)}</div>
        <div class="row"><span class="m">${esc(r.item_no)} · ${esc(whName(r.wh_code))}</span><span class="m num">${usdK(r.revenue_at_risk_14d)} at risk</span></div>
        <div class="m" style="margin-top:4px">${r.est_on_hand <= 0 ? 'Estimated empty.' : `${n0(r.est_on_hand)} on hand, ${n1(r.days_of_cover)} days of cover.`} Sells ${n1(r.daily_rate)}/day. ${r.inbound_14d_qty ? `${n0(r.inbound_14d_qty)} promised in ${r.first_inbound_in_days} days.` : 'Nothing promised in the next 14 days.'}
        ${r.transfer_from ? `<b> Move ${n0(r.transfer_qty)} from ${esc(whName(r.transfer_from))}.</b>` : ''} ${r.confidence === 'suspect' ? chip('estimate uncertain', 'warn') : ''}</div></button></li>`).join('') || '<li class="empty">Nothing matches these filters</li>'}</ul></div>
      ${rows.length > state.shown ? '<button class="btn more-btn" id="more">Show more</button>' : ''}
      <p class="note" style="margin-top:12px">A pair needs at least 3 units sold in the last 28 days to be judged; slower movers are left out. Backtested against the hidden truth in the scorecard.</p>`;
    on(el, '[data-item]', 'click', (e, b) => openSku(b.dataset.item, b.dataset.wh));
    el.querySelector('#f-wh').onchange = e => { state.wh = e.target.value; state.shown = 20; draw(); };
    el.querySelector('#f-kind').onchange = e => { state.kind = e.target.value; state.shown = 20; draw(); };
    const more = el.querySelector('#more'); if (more) more.onclick = () => { state.shown += 25; draw(); };
  }
  function inbound(el) {
    const s = inb.summary;
    const worst = inb.vendors.slice(0, 6), best = inb.vendors.slice(-4).reverse();
    el.innerHTML = `
      <div class="grid c3">
        <div class="card"><div class="k note">OPEN PO LINES</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(s.open_lines)}</div><div class="note">${usdK(s.open_value)} on order</div></div>
        <div class="card"><div class="k note">OVERDUE</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(s.overdue_lines)}</div><div class="note">${usdK(s.overdue_value)}, ${n1(s.avg_days_overdue)} days late on average</div></div>
        <div class="card"><div class="k note">DUE IN NEXT 14 DAYS</div><div class="v num" style="font-size:1.9rem;font-weight:750">${n0(inb.due_next_14.reduce((a, r) => a + r.lines, 0))}</div><div class="note">${usdK(inb.due_next_14.reduce((a, r) => a + r.total_value, 0))} across ${inb.due_next_14.length} warehouses</div></div></div>
      <div class="sec"><h2>Overdue purchase orders</h2><p class="sub">Past the supplier’s promised date and not yet received. Largest first.</p>
        <div class="card pad0"><ul class="list">${inb.overdue.slice(0, 10).map(r => `<li><div class="row"><span class="t">${esc(r.description)}</span><span class="num"><b>${usd(r.open_value)}</b></span></div>
          <div class="row"><span class="m">${esc(r.po_no)} · ${esc(r.vendor_name || 'vendor')} → ${esc(whName(r.wh_code))}</span>${chip(`${r.days_overdue} d late`, r.days_overdue > 7 ? 'bad' : 'warn')}</div></li>`).join('')}</ul></div></div>
      <div class="sec"><h2>Supplier delivery performance</h2><p class="sub">Received on or before the promised date, last 180 days (vendors with 25+ lines).</p>
        <div class="grid c2"><div class="card"><h3>Slowest</h3>${hBars(worst.map(v => ({ label: v.vendor_name || v.vendor_no, value: v.on_time_rate, text: pct(v.on_time_rate, 0), color: 'var(--series3)', note: `${n0(v.lines_received)} lines, ${v.avg_days_vs_promise > 0 ? '+' : ''}${n1(v.avg_days_vs_promise)} days vs promise` })), { max: 1, label: 'Slowest suppliers' })}</div>
        <div class="card"><h3>Most reliable</h3>${hBars(best.map(v => ({ label: v.vendor_name || v.vendor_no, value: v.on_time_rate, text: pct(v.on_time_rate, 0), color: 'var(--good)', note: `${n0(v.lines_received)} lines, ${v.avg_days_vs_promise > 0 ? '+' : ''}${n1(v.avg_days_vs_promise)} days vs promise` })), { max: 1, label: 'Most reliable suppliers' })}</div></div></div>`;
  }
  draw();
}
