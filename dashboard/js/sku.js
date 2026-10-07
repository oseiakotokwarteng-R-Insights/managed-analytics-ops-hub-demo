// Item detail sheet: today's position in every warehouse, and the stock history "as of" any past date.
import { getJSON, esc, n0, n1, usd, dshort, addDays, lineChart, riskChip, confChip, confShort, chip, whName } from './lib.js';

const sheetBg = document.getElementById('sheetbg');
const sheet = document.getElementById('sheet');
const RISK = ['ok', 'at_risk', 'out_of_stock', 'low_demand'];
const CONF = ['verified', 'carried', 'suspect'];
let lastFocus = null;

export function closeSku() {
  sheetBg.classList.remove('open');
  sheetBg.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  if (lastFocus) lastFocus.focus();
}
sheetBg.addEventListener('click', e => { if (e.target === sheetBg) closeSku(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && sheetBg.classList.contains('open')) closeSku(); });

function decode(h, days) {
  const est = new Array(days).fill(null), rec = new Array(days).fill(null), conf = new Array(days).fill(null);
  let a = 0, b = 0;
  h.e.forEach((d, i) => { a += d; est[h.s + i] = a; });
  h.r.forEach((d, i) => { b += d; rec[h.s + i] = b; });
  let p = h.s;
  for (let i = 0; i < h.c.length; i += 2) for (let k = 0; k < h.c[i + 1]; k++) conf[p++] = h.c[i];
  return { est, rec, conf };
}

export async function openSku(item, wh) {
  lastFocus = document.activeElement;
  sheet.innerHTML = '<div class="loading">Loading item…</div>';
  sheetBg.classList.add('open');
  sheetBg.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  const [idx, hist, meta] = await Promise.all([getJSON('skus.json'), getJSON(`sku/${item}.json`), getJSON('meta.json')]);
  const s = idx.skus.find(x => x.i === item);
  const whs = meta.warehouses.map(w => w.wh_code);
  const F = Object.fromEntries(idx.fields.map((f, i) => [f, i]));
  const days = hist.days, start = hist.start;
  const dec = {};
  whs.forEach(w => { if (hist.wh[w]) dec[w] = decode(hist.wh[w], days); });
  let selWh = wh && dec[wh] ? wh : (whs.find(w => dec[w]) || whs[0]);
  let cursor = days - 1;

  const today = s.w.map((r, i) => (r ? { wh: whs[i], est: r[F.est], atp: r[F.atp], risk: RISK[r[F.risk]], conf: CONF[r[F.conf]], rate: r[F.rate], cover: r[F.cover_days], committed: r[F.committed], rec: r[F.recorded], last: r[F.last_count], tf: r[F.transfer_from], tq: r[F.transfer_qty], inb: r[F.inbound_14d] } : null)).filter(Boolean);

  const labels = Array.from({ length: days }, (_, i) => addDays(start, i));
  const asOfTable = () => {
    const rows = whs.filter(w => dec[w] && dec[w].est[cursor] != null).map(w => ({ wh: w, est: dec[w].est[cursor], rec: dec[w].rec[cursor], conf: CONF[dec[w].conf[cursor]] }));
    const total = rows.reduce((a, r) => a + Math.max(0, r.est), 0);
    document.getElementById('sk-date').textContent = dshort(addDays(start, cursor));
    document.getElementById('sk-total').textContent = `All warehouses: ${n0(total)} units`;
    document.getElementById('sk-asof').innerHTML = rows.map(r => `<tr><td>${esc(whName(r.wh))}</td><td class="r num"><b>${n0(r.est)}</b></td><td class="r num">${n0(r.rec)}</td><td>${confShort(r.conf)}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">No stock record on this date</td></tr>';
  };
  const chart = () => {
    const e = dec[selWh];
    document.getElementById('sk-chart').innerHTML = lineChart([{ name: 'Our estimate', color: 'var(--series1)', values: e.est }, { name: 'What the system said', color: 'var(--series2)', values: e.rec, dashed: true, width: 1.6 }], labels,
      { cursor, yMin: Math.min(0, ...e.est.filter(v => v != null)), xFmt: iso => dshort(iso).replace(/, \d{4}/, ' ’' + iso.slice(2, 4)), label: 'Stock history' });
  };
  function draw() {
    sheet.innerHTML = `
      <div class="sheet-head"><div style="min-width:0"><div class="note num">${esc(item)} · ${esc(s.c)}</div><h2 style="margin:2px 0 0">${esc(s.d)}</h2></div><button class="x" aria-label="Close" id="sk-close">&times;</button></div>
      <h3>Today, ${dshort(meta.as_of)}</h3>
      <p class="sub">Our estimate is rebuilt from every source system. “System says” is the number the warehouse system itself carries.</p>
      <div class="grid c2">${today.map(r => `<div class="card"><div class="row"><span class="t">${esc(whName(r.wh))}</span>${riskChip(r.risk)}</div>
        <div class="kv" style="grid-template-columns:1fr 1fr"><div><div class="k">Estimated on hand</div><div class="v num">${n0(r.est)}</div></div><div><div class="k">System says</div><div class="v num">${n0(r.rec)}</div></div>
        <div><div class="k">Can promise</div><div class="v num">${n0(r.atp)}</div></div><div><div class="k">Sells per day</div><div class="v num">${n1(r.rate)}</div></div></div>
        <div style="margin-top:8px">${confChip(r.conf)} ${r.cover != null ? chip(`${n1(r.cover)} days of cover`, r.cover <= 14 ? 'warn' : 'mute') : ''} ${r.inb ? chip(`${n0(r.inb)} due within 14 days`, 'info') : ''}</div>
        ${r.est < 0 ? '<p class="note" style="margin:8px 0 0">Negative estimate: the records for this item contradict each other. It is flagged for a recount.</p>' : ''}
        ${r.tf ? `<p class="note" style="margin:8px 0 0"><b>Suggestion:</b> move ${n0(r.tq)} from ${esc(whName(r.tf))}, which holds more than 45 days of cover.</p>` : ''}
        <p class="note" style="margin:8px 0 0">${r.last ? 'Last counted ' + dshort(r.last) : 'Never counted'}${r.committed ? ` · ${n0(r.committed)} committed to open orders` : ''}</p></div>`).join('')}</div>
      <h3 style="margin-top:22px">Stock on any past date</h3>
      <p class="sub">Drag to move through ${n0(days)} days of history. The estimate is recomputed from the records as they stood.</p>
      <div class="card">
        <div class="row"><b id="sk-date"></b><span class="note" id="sk-total"></span></div>
        <input type="range" min="0" max="${days - 1}" value="${cursor}" id="sk-range" aria-label="Date">
        <div class="scroll"><table class="tbl"><thead><tr><th>Warehouse</th><th class="r">Estimate</th><th class="r">System said</th><th>Confidence</th></tr></thead><tbody id="sk-asof"></tbody></table></div>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="controls" style="margin-bottom:6px"><label class="note" for="sk-wh" style="align-self:center">Warehouse</label><select id="sk-wh">${whs.filter(w => dec[w]).map(w => `<option value="${w}" ${w === selWh ? 'selected' : ''}>${esc(whName(w))}</option>`).join('')}</select></div>
        <div id="sk-chart"></div>
      </div>`;
    document.getElementById('sk-close').onclick = closeSku;
    document.getElementById('sk-range').oninput = ev => { cursor = +ev.target.value; asOfTable(); chart(); };
    document.getElementById('sk-wh').onchange = ev => { selWh = ev.target.value; chart(); };
    asOfTable(); chart();
  }
  draw();
  sheet.scrollTop = 0;
  document.getElementById('sk-close').focus();
}
