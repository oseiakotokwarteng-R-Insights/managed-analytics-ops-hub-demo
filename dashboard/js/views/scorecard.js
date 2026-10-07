import { getJSON, esc, n0, n1, pct, usdK, chip, on } from '../lib.js';

const kind = r => ({ PASS: 'good', MET: 'good', FAIL: 'bad', MISSED: 'warn', INFO: 'mute' }[r] || 'mute');
const state = { filter: 'all', source: 'all' };

export async function render(root) {
  const [sc, me] = await Promise.all([getJSON('scorecard.json'), getJSON('manual_effort.json')]);
  const crit = sc.criteria || [], cls = sc.classes || [], scn = sc.scenarios || [], miss = sc.known_misses || [];
  const metC = crit.filter(r => r.result === 'MET').length, metK = cls.filter(r => r.met).length, metS = scn.filter(r => r.met).length;
  const draw = () => {
    const rows = cls.filter(r => (state.filter === 'all' || (state.filter === 'missed' && !r.met)) && (state.source === 'all' || r.source === state.source));
    const sources = [...new Set(cls.map(r => r.source))];
    root.innerHTML = `
      <h1 class="view-title">Scorecard</h1>
      <p class="lede">The source data is synthetic, so the right answer is known for every row. Everything below compares what the pipeline did with that hidden answer key, against targets that were written down <b>before anything was built</b>. Misses are shown as measured, in colour, not explained away.</p>
      <div class="grid c2 c4d">
        <div class="card"><div class="k note">SUCCESS CRITERIA MET</div><div class="v num" style="font-size:1.9rem;font-weight:750">${metC} of ${crit.length}</div><div class="note">from the project spec</div></div>
        <div class="card"><div class="k note">DEFECT CLASSES AT TARGET</div><div class="v num" style="font-size:1.9rem;font-weight:750">${metK} of ${cls.length}</div><div class="note">each against its own target</div></div>
        <div class="card"><div class="k note">SCENARIOS MET</div><div class="v num" style="font-size:1.9rem;font-weight:750">${metS} of ${scn.length}</div><div class="note">the five demo stories</div></div>
        <div class="card"><div class="k note">DEFECTS PLANTED</div><div class="v num" style="font-size:1.9rem;font-weight:750">120,776</div><div class="note">across 38 kinds, in 5 source systems</div></div></div>
      <div class="sec"><h2>The eight success criteria</h2>
        <div class="card pad0"><ul class="list">${crit.map((r, i) => `<li><div class="row"><span class="t">${i + 1}. ${esc(r.measure)}</span>${chip(r.result, kind(r.result))}</div>
          <div class="note">Target: ${esc(r.target)}</div><div class="m" style="margin-top:4px">${esc(r.measured)}</div></li>`).join('')}</ul></div></div>
      <div class="sec"><h2>The five demo stories</h2>
        ${scn.map(r => `<div class="card" style="margin-bottom:12px"><div class="row"><h3>${esc(r.id)}: ${esc(r.name)}</h3>${chip(r.met ? 'MET' : 'MISSED', r.met ? 'good' : 'warn')}</div><div class="note">${esc(r.when)}</div>
          <p style="margin:8px 0 4px"><b>Expected:</b> ${esc(r.expected)}</p><p style="margin:0 0 4px"><b>Target:</b> ${esc(r.target)}</p><p class="m" style="margin:0"><b>Measured:</b> ${esc(r.measured)}</p></div>`).join('')}</div>
      <div class="sec"><h2>Every defect class</h2><p class="sub">Share of planted defects the pipeline handled the way the catalog says it should: fixed correctly, quarantined, flagged, or sent to a person. The black tick is the catalog's target.</p>
        <div class="controls"><div class="seg" role="group" aria-label="Filter"><button data-f="all" aria-pressed="${state.filter === 'all'}">All ${cls.length}</button><button data-f="missed" aria-pressed="${state.filter === 'missed'}">Missed ${cls.length - metK}</button></div>
          <select id="src" aria-label="Source system"><option value="all">All systems</option>${sources.map(s => `<option ${state.source === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></div>
        <div class="card pad0"><ul class="list">${rows.map(r => `<li style="padding:0"><details><summary style="cursor:pointer;padding:12px 14px;list-style:none;min-height:48px">
            <div class="row"><span class="t">${esc(r.id)} · ${esc(r.name)}</span>${chip(r.met ? 'MET' : 'MISSED', r.met ? 'good' : 'warn')}</div>
            <div style="position:relative;height:10px;background:var(--soft);border-radius:5px;margin:8px 0 4px"><div style="height:10px;width:${Math.max(0, Math.min(100, (r.rate * 100 - 80) * 5)).toFixed(1)}%;background:${r.met ? 'var(--good)' : 'var(--series3)'};border-radius:5px"></div>
              <div style="position:absolute;top:-3px;left:${Math.max(0, Math.min(100, (r.target * 100 - 80) * 5)).toFixed(1)}%;width:2px;height:16px;background:var(--ink)"></div></div>
            <div class="row"><span class="note num">${(r.rate * 100).toFixed(2)}% of ${n0(r.n)} · target ${(r.target * 100).toFixed(1)}%${r.kind === 'precision' ? ' (precision)' : ''}</span><span class="note">${esc(r.source)}</span></div></summary>
            <div style="padding:0 14px 12px"><p class="m" style="margin:0 0 4px">${esc(r.note || '')}</p>${r.wrong_repairs ? `<p class="note" style="margin:0">Wrong repairs: ${n0(r.wrong_repairs)}</p>` : ''}</div></details></li>`).join('') || '<li class="empty">Nothing here</li>'}</ul></div>
        <p class="note">Bars start at 80%.</p></div>
      <div class="sec"><h2>What it cannot see, by design</h2><p class="sub">Three kinds of problem pass every check, and the scorecard says so. The fix for each is a business process, not more pipeline.</p>
        <div class="card pad0"><ul class="list">${miss.map(r => `<li><div class="row"><span class="t">${esc(r.id)}: ${esc(r.what)}</span><span class="note num">${n0(r.rows)} rows</span></div><div class="m">Control: ${esc(r.control)}</div></li>`).join('')}</ul></div></div>
      <div class="sec"><h2>Manual work replaced <span class="chip info" style="vertical-align:middle">MODELED</span></h2>
        <p class="sub">An estimate, not a measurement. Counts are real (from the cleaned tables); the minutes per item are assumptions, shown so you can change them.</p>
        <div class="card"><div class="kv"><div><div class="k">Work the pipeline does</div><div class="v num">${n0(me.hours_automated)} h</div></div><div><div class="k">Still for people</div><div class="v num">${n0(me.hours_remaining)} h</div></div></div></div>
        <div class="card pad0" style="margin-top:12px"><ul class="list">${me.rows.map(r => `<li><div class="row"><span class="t" style="font-weight:600">${esc(r.label)}</span><b class="num">${n0(r.hours)} h</b></div><div class="note num">${n0(r.items)} items × ${r.minutes_per_item} min · ${esc(r.basis)}${r.is_remaining_manual ? ' · remaining manual work' : ''}</div></li>`).join('')}</ul></div></div>
      <div class="sec"><h2>Every check, by build phase</h2>${sc.phases.map(p => `<details class="card" style="padding:0;margin-bottom:10px"><summary style="cursor:pointer;padding:14px;min-height:48px;list-style:none"><div class="row"><b>Phase ${p.phase}: ${esc(p.name)}</b><span>${chip(`${p.pass + p.met} ok`, 'good')} ${p.fail + p.missed ? chip(`${p.fail + p.missed} missed`, 'warn') : ''}</span></div></summary>
        <ul class="list" style="border-top:1px solid var(--line)">${p.checks.map(c => `<li><div class="row"><span class="t" style="font-weight:600">${esc(c.check)}</span>${chip(c.result, kind(c.result))}</div><div class="m">${esc(c.measured)}</div><div class="note">Needed: ${esc(c.criterion)}</div></li>`).join('')}</ul></details>`).join('')}</div>`;
    on(root, '[data-f]', 'click', (e, el) => { state.filter = el.dataset.f; draw(); });
    root.querySelector('#src').onchange = e => { state.source = e.target.value; draw(); };
  };
  draw();
}
