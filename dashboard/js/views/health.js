import { getJSON, getOptional, esc, n0, pct, dshort, dmon, chip, lineChart, nightStrip, addDays } from '../lib.js';

const KIND = { ERROR: 'bad', WARNING: 'warn', INFO: 'info' };
const TYPE = { load_or_schema: 'File held (schema changed)', stream_stale: 'Feed went quiet', volume_anomaly: 'Unusual volume', duplicate_file: 'File sent twice', value_format_drift: 'Value format changed', dq_rate_out_of_control: 'Defect rate jumped', model_test_failed: 'Model test failed' };
const METRIC = { wms_duplicate_delivery_rate: 'Warehouse events delivered twice', wms_late_arrival_rate: 'Warehouse events arriving 6+ hours late', erp_duplicate_line_rate: 'Re-keyed duplicate order lines', freight_reference_unmatched_rate: 'Shipments we could not match to an order', count_sku_unresolved_rate: 'Count-sheet items we could not identify', legacy_unparseable_quantity_rate: 'Legacy rows with unreadable quantities' };

export async function render(root) {
  const [h, live] = await Promise.all([getJSON('health.json'), getOptional('live.json')]);
  const st = h.nights.status, cnt = c => [...st].filter(x => x === c).length;
  const today = h.today, ok = today.health === 'green';
  const late = h.freshness.filter(f => f.is_late);
  const openAlerts = h.alerts.filter(a => !a.resolved_as_of || a.resolved_as_of > h.as_of);
  root.innerHTML = `
    <h1 class="view-title">Pipeline health</h1>
    <p class="lede">Can I trust today’s numbers? Every night the pipeline checks every feed, every layer and every defect rate, and writes the result here. Failures are shown as plainly as successes.</p>
    <div class="banner ${ok ? 'good' : today.health === 'red' ? 'bad' : 'warn'}"><div class="row"><h3>Last night, ${dshort(today.as_of)}: ${ok ? 'all clear' : today.health}</h3>${chip(`run ${today.run_status}`, 'mute')}</div>
      <div class="kv"><div><div class="k">Feeds on time</div><div class="v num">${h.freshness.length - late.length} of ${h.freshness.length}</div></div><div><div class="k">Open alerts</div><div class="v num">${openAlerts.length}</div></div>
        <div><div class="k">Row checks balance</div><div class="v num">${h.layers.filter(l => l.ok).length} of ${h.layers.length}</div></div><div><div class="k">Model tests passing</div><div class="v num">${h.tests.passed} of ${h.tests.n}</div></div></div></div>
    ${live && live.runs.length ? `<div class="card"><h3>Live clock</h3><p class="sub">The demo advances one simulated day per real day. Each night: release the day's files, load them, rebuild every model and test, refresh alerts and re-export. Budget: ${live.sla_minutes} minutes.</p>
      <div class="kv"><div><div class="k">Simulated date</div><div class="v">${dshort(live.sim_date)}</div></div><div><div class="k">Days live</div><div class="v num">${live.days_live}</div></div></div>
      <ul class="list" style="margin-top:8px">${live.runs.slice().reverse().slice(0, 6).map(r => `<li style="padding:8px 0"><div class="row"><span class="t">${dshort(r.to)}${r.days > 1 ? ` (caught up ${r.days} days)` : ''}</span>${chip(r.status === 'OK' ? (r.within_sla ? `${Math.round(r.seconds / 60 * 10) / 10} min` : `${Math.round(r.seconds / 60)} min, over budget`) : 'failed', r.status === 'OK' && r.within_sla ? 'good' : 'bad')}</div>
        <div class="note">${r.steps && r.steps.release_and_load ? `${n0(r.steps.release_and_load.files_loaded)} files, ${n0(r.steps.release_and_load.rows)} rows loaded` : ''}${r.error ? esc(r.error) : ''}</div></li>`).join('')}</ul></div>` : ''}
    <div class="card"><h3>Every night of history</h3><p class="sub">${n0(st.length)} nights: <b>${cnt('g')}</b> green, <b>${cnt('a')}</b> amber (warnings), <b>${cnt('r')}</b> red (error-level incident). Each square is a night, weeks run left to right, ${dshort(h.nights.start)} to ${dshort(h.as_of)}.</p>${nightStrip(st)}
      <div class="legend"><span><i style="background:var(--good)"></i>clean</span><span><i style="background:#e0a800"></i>warnings open</span><span><i style="background:var(--bad)"></i>error open</span></div></div>
    <div class="sec"><h2>Alert log</h2><p class="sub">Everything the monitors raised, newest first. Each one matches an incident that was planted in the data.</p>
      <div class="card pad0"><ul class="list">${h.alerts.map(a => `<li><div class="row"><span class="t">${esc(TYPE[a.alert_type] || a.alert_type)}</span>${chip(a.severity, KIND[a.severity])}</div>
        <div class="m">${esc(a.message)}</div><div class="note" style="margin-top:3px">Raised ${dshort(a.opened_as_of)}${a.resolved_as_of ? ', cleared ' + dshort(a.resolved_as_of) : ', still open'}</div></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>Source feeds</h2><p class="sub">How long since each feed last delivered, against what its owner promises.</p>
      <div class="card pad0"><ul class="list">${h.freshness.map(f => `<li><div class="row"><span class="t">${esc(f.description)}</span>${chip(f.is_late ? 'late' : 'on time', f.is_late ? 'bad' : 'good')}</div>
        <div class="row"><span class="m">${esc(f.stream)} · ${esc(f.owner)}${f.critical ? ' · stock-critical' : ''}</span><span class="m num">${f.days_since_last_arrival}d since last (allowed ${f.max_expected_gap_days}d)</span></div></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>Defect rates, week by week</h2><p class="sub">An alert fires when a weekly rate leaves its normal band (dashed). The spike is the Flagstaff outage catching up.</p>
      <div class="grid c2">${Object.entries(h.metrics).map(([k, rows]) => `<div class="card"><h3 style="font-size:.92rem">${esc(METRIC[k] || k)}</h3>${lineChart([{ name: 'weekly rate', color: 'var(--series1)', values: rows.map(r => r.rate) }, { name: 'normal level', color: 'var(--series2)', dashed: true, values: rows.map(r => r.p0), width: 1.4 }], rows.map(r => r.week), { yFmt: v => (v * 100).toFixed(v < .01 ? 2 : 1) + '%', yMin: 0, h: 140, ticks: 3, xFmt: dmon, label: k })}</div>`).join('')}</div></div>
    <div class="sec"><h2>Nothing goes missing between layers</h2><div class="card pad0"><ul class="list">${h.layers.map(l => `<li><div class="row"><span>${esc(l.check_name)}</span>${chip(l.ok ? 'balanced' : 'OFF BY ' + l.diff, l.ok ? 'good' : 'bad')}</div><div class="note num">${n0(l.left_count)} in, ${n0(l.right_count)} out</div></li>`).join('')}</ul></div></div>
    <div class="sec"><h2>The checks, in plain words</h2><div class="card pad0"><ul class="list">${h.catalog.map(c => `<li><div class="t">${esc(c.check_name.replace(/_/g, ' '))}</div><div class="m">${esc(c.scope)}. Rule: ${esc(c.rule)}. Raises: ${esc(c.raises)}.</div></li>`).join('')}</ul></div></div>`;
}
