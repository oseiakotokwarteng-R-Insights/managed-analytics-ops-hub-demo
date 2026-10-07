import { getJSON, esc, n0, pct, usdK, usd, dshort, dmon, chip, confChip, whName, lineChart, hBars, on } from '../lib.js';
import { openSku } from '../sku.js';

export async function render(root) {
  const [st, idx, sc] = await Promise.all([getJSON('stock.json'), getJSON('skus.json'), getJSON('scorecard.json')]);
  const F = Object.fromEntries(idx.fields.map((f, i) => [f, i]));
  const months = [...new Set(st.count_accuracy.map(r => r.month))].sort();
  const accAll = months.map(m => { const rs = st.count_accuracy.filter(r => r.month === m); const n = rs.reduce((a, r) => a + r.items_counted, 0); return rs.reduce((a, r) => a + r.exact_rate * r.items_counted, 0) / n; });
  const acc5 = months.map(m => st.count_accuracy.find(r => r.month === m && r.wh_code === 'WH-05')?.exact_rate ?? null);
  const accOther = months.map(m => { const rs = st.count_accuracy.filter(r => r.month === m && r.wh_code !== 'WH-05'); const n = rs.reduce((a, r) => a + r.items_counted, 0); return rs.reduce((a, r) => a + r.exact_rate * r.items_counted, 0) / n; });
  const mx = Math.max(...st.by_wh.map(w => w.est_value));
  root.innerHTML = `
    <h1 class="view-title">Stock you can promise</h1>
    <p class="lede">One estimate per item and warehouse, rebuilt from the ERP, the warehouse systems, the legacy database and the count sheets. Search any item to see it today and on any past date.</p>
    <div class="card"><label for="q" class="k note" style="display:block;font-weight:700;margin-bottom:6px">FIND AN ITEM</label>
      <div class="controls" style="margin:0"><input type="search" id="q" placeholder="Item number or words, e.g. shingle, NF-20219" autocomplete="off" enterkeyhint="search"></div>
      <ul class="list" id="results" style="margin-top:8px"></ul></div>
    <div class="sec"><h2>By warehouse</h2>
      <div class="grid c2 c3d">${st.by_wh.map(w => `<div class="card"><div class="row"><span class="t">${esc(w.name)}</span>${chip(w.system_of_record === 'LEGACY' ? 'Legacy system' : 'Modern WMS', w.system_of_record === 'LEGACY' ? 'warn' : 'mute')}</div>
        <div class="kv" style="grid-template-columns:1fr 1fr"><div><div class="k">Stock value</div><div class="v num">${usdK(w.est_value)}</div></div><div><div class="k">Can promise</div><div class="v num">${n0(w.atp_units)} u</div></div>
        <div><div class="k">Need a look</div><div class="v num">${n0(w.at_risk + w.out_of_stock)}</div></div><div><div class="k">Check-this share</div><div class="v num">${pct(w.suspect_share, 1)}</div></div></div>
        <div style="margin-top:8px" class="note">System books ${usdK(w.recorded_value)}; we estimate ${usdK(w.est_value)}. Average ${n0(w.avg_days_since_count)} days since last count.</div></div>`).join('')}</div></div>
    <div class="sec"><h2>How far can you trust the record?</h2>
      <div class="card"><h3>Does the book match what was counted?</h3><p class="sub">Share of counted items where the warehouse book was exactly right, by month. Albuquerque’s May dip is the phantom-stock incident, found by a count.</p>
        ${lineChart([{ name: 'Other warehouses', color: 'var(--series2)', values: accOther }, { name: 'Albuquerque (legacy system)', color: 'var(--series3)', values: acc5 }], months, { yMin: 0.3, yMax: 1, yFmt: v => Math.round(v * 100) + '%', xFmt: dmon, ticks: 4, label: 'Count accuracy by month' })}</div>
      <div class="card"><h3>Confidence in today’s estimate</h3><p class="sub">${pct(st.agree_with_recorded, 0)} of positions equal the system’s own number. The rest differ, which is where reconciling the sources earns its keep.</p>
        ${hBars(st.confidence_mix.map(c => ({ label: { verified: 'Counted recently', carried: 'Carried forward from the last count', suspect: 'Check this: evidence conflicts' }[c.confidence], value: c.pairs, color: { verified: 'var(--good)', carried: 'var(--series1)', suspect: 'var(--series3)' }[c.confidence] })), { label: 'Confidence mix' })}
        <p class="note">Scored against the hidden truth: ${(sc.headlines.tiers || []).map(t => `${t.tier} positions exact on ${t.exact}% of days`).join(', ')}.</p></div></div>
    <div class="sec"><h2>Where our estimate and the system disagree most</h2><p class="sub">Largest dollar gaps today. Tap to see why.</p>
      <div class="card pad0"><ul class="list">${st.biggest_gaps.slice(0, 8).map(g => `<li><button class="li-btn" data-item="${esc(g.item_no)}" data-wh="${g.wh_code}"><div class="row"><span class="t">${esc(g.description)}</span><span class="num"><b>${usd(g.gap_value)}</b></span></div>
        <div class="row"><span class="m">${esc(g.item_no)} · ${esc(whName(g.wh_code))}</span><span class="m num">we say ${n0(g.est_on_hand)}, system says ${n0(g.book_recorded_qty)}</span></div></button></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>By category</h2><div class="card">${hBars(st.by_category.slice(0, 8).map(c => ({ label: c.category, value: c.est_value, text: usdK(c.est_value), note: c.at_risk ? `${n0(c.at_risk)} positions need attention` : '' })), { label: 'Stock value by category' })}</div></div>`;

  const q = root.querySelector('#q'), res = root.querySelector('#results');
  const show = txt => {
    const t = txt.trim().toLowerCase();
    if (t.length < 2) { res.innerHTML = ''; return; }
    const words = t.split(/\s+/);
    const hits = idx.skus.filter(s => { const hay = (s.i + ' ' + s.d + ' ' + s.c).toLowerCase(); return words.every(w => hay.includes(w)); }).slice(0, 12);
    res.innerHTML = hits.length ? hits.map(s => { const tot = s.w.reduce((a, r) => a + (r ? Math.max(0, r[F.est]) : 0), 0); const worst = s.w.some(r => r && r[F.risk] === 2) ? chip('Out of stock somewhere', 'bad') : s.w.some(r => r && r[F.risk] === 1) ? chip('At risk somewhere', 'warn') : '';
      return `<li style="padding:0"><button class="li-btn" data-item="${esc(s.i)}"><div class="row"><span class="t">${esc(s.d)}</span><span class="num m">${n0(tot)} units</span></div><div class="row"><span class="m">${esc(s.i)} · ${esc(s.c)}</span>${worst}</div></button></li>`; }).join('') : '<li class="empty">No items match</li>';
    on(res, '[data-item]', 'click', (e, el) => openSku(el.dataset.item));
  };
  q.addEventListener('input', () => show(q.value));
  on(root, '.sec [data-item]', 'click', (e, el) => openSku(el.dataset.item, el.dataset.wh));
}
