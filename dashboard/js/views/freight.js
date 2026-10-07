import { getJSON, esc, n0, n1, pct, usd, usdK, dshort, dmon, chip, lineChart, hBars, colChart } from '../lib.js';

const CHARGE = { LH: 'Line-haul', FSC: 'Fuel surcharge', BASE: 'Base rate', FUEL: 'Fuel', LFT: 'Liftgate', OVS: 'Oversize', RES: 'Residential', RESI: 'Residential', LTD: 'Limited access', DET: 'Detention' };

export async function render(root) {
  const f = await getJSON('freight.json');
  const A = f.by_carrier.find(c => c.carrier === 'CARRIER_A'), B = f.by_carrier.find(c => c.carrier === 'CARRIER_B');
  const nm = c => (c === 'CARRIER_A' ? 'Carrier A (freight / LTL)' : 'Carrier B (parcel)');
  const rec = f.duplicates.reduce((a, r) => a + r.recoverable, 0);
  const lastYear = f.duplicates.filter(r => r.month >= f.weeks[0]).reduce((a, r) => a + r.recoverable, 0);
  const std = Object.fromEntries(f.standards.map(s => [s.direction, s.max_transit_days]));
  const carrierCard = (c, name, color) => `<div class="card"><h3>${name}</h3><div class="kv"><div><div class="k">Spend, 12 months</div><div class="v num">${usdK(c.cost)}</div></div><div><div class="k">Shipments</div><div class="v num">${n0(c.shipments)}</div></div>
    <div><div class="k">Per 100 lb</div><div class="v num">${usd(c.cost_per_100lb, 2)}</div></div><div><div class="k">Per order</div><div class="v num">${usd(c.cost_per_order, 2)}</div></div>
    <div><div class="k">Per unit shipped</div><div class="v num">${usd(c.cost_per_unit, 2)}</div></div><div><div class="k">Ran slow</div><div class="v num">${pct(c.slow_rate)}</div></div></div></div>`;
  const wk = f.weeks;
  root.innerHTML = `
    <h1 class="view-title">Freight</h1>
    <p class="lede">Two carriers, two file formats, references typed by hand. Matched to the orders and purchase orders they belong to, then priced per order, per unit and per lane.</p>
    <div class="grid c2">${carrierCard(A, nm('CARRIER_A'))}${carrierCard(B, nm('CARRIER_B'))}</div>
    <div class="banner warn sec" style="margin-top:16px"><h3>Recoverable: ${usdK(rec)} in duplicate charge lines</h3><p style="margin:4px 0 0">${n0(f.duplicates.reduce((a, r) => a + r.lines, 0))} charge lines repeat another line on the same shipment, all from Carrier A. ${usdK(lastYear)} falls in the last 12 months. Flagged for dispute, not deleted.</p></div>
    <div class="grid c2 sec">
      <div class="card"><h3>Cost per 100 lb, weekly</h3><p class="sub">Carrier A moves heavy freight; Carrier B parcels cost more per pound.</p>
        ${lineChart([{ name: 'Carrier A', color: 'var(--series1)', values: f.series.CARRIER_A.cost_per_100lb }], wk, { yFmt: v => '$' + n0(v), xFmt: dmon, ticks: 4, label: 'Carrier A cost per 100 lb' })}
        ${lineChart([{ name: 'Carrier B', color: 'var(--series3)', values: f.series.CARRIER_B.cost_per_100lb }], wk, { yFmt: v => '$' + n0(v), xFmt: dmon, ticks: 4, label: 'Carrier B cost per 100 lb', h: 150 })}</div>
      <div class="card"><h3>Share of shipments that ran slow</h3><p class="sub">Slow = outbound later than ${std.outbound} days or inbound later than ${std.inbound} (assumed standards; the feeds carry no promised dates).</p>
        ${lineChart([{ name: 'Carrier A', color: 'var(--series1)', values: f.series.CARRIER_A.slow_rate }, { name: 'Carrier B', color: 'var(--series3)', values: f.series.CARRIER_B.slow_rate }], wk, { yFmt: v => Math.round(v * 100) + '%', yMin: 0, xFmt: dmon, ticks: 4, label: 'Slow share by week' })}</div></div>
    <div class="sec"><h2>Where the money goes: busiest lanes</h2><p class="sub">Last 90 days. Cost per 100 lb in brackets.</p>
      <div class="card pad0"><ul class="list">${f.lanes.slice(0, 10).map(l => `<li><div class="row"><span class="t">${esc(l.lane)}</span><b class="num">${usdK(l.cost)}</b></div>
        <div class="row"><span class="m">${nm(l.carrier).split(' (')[0]} · ${esc(l.direction)} · ${n0(l.shipments)} shipments</span><span class="m num">${usd(l.cost_per_100lb, 2)}/100 lb · ${l.slow_shipments ? Math.round(100 * l.slow_shipments / l.timed_shipments) + '% slow' : 'none slow'}</span></div></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>What the invoices are made of</h2><p class="sub">Last 12 months, duplicates excluded.</p>
      <div class="grid c2">${['CARRIER_A', 'CARRIER_B'].map(c => { const rows = f.charges.filter(r => r.carrier === c).slice(0, 6); return `<div class="card"><h3>${nm(c).split(' (')[0]}</h3>${hBars(rows.map(r => ({ label: CHARGE[r.charge_code] || r.charge_code, value: r.amount, text: usdK(r.amount), note: `${n0(r.lines)} lines` })), { label: 'Charges by type' })}</div>`; }).join('')}</div></div>`;
}
