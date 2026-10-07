import { getJSON, getOptional, esc, n0, pct, chip, colChart, usdK } from '../lib.js';

export async function render(root) {
  const [sc, ov, st, cfg] = await Promise.all([getJSON('scorecard.json'), getJSON('overview.json'), getJSON('stock.json'), fetch('config.json', { cache: 'no-cache' }).then(r => r.json()).catch(() => ({}))]);
  const contact = cfg.contact && cfg.contact.url ? cfg.contact : null;
  const pairs = st.by_wh.reduce((a, w) => a + w.pairs, 0), avgDays = st.by_wh.reduce((a, w) => a + w.avg_days_since_count * w.pairs, 0) / pairs;
  const d = sc.headlines.decay || [];
  const ep = ov.phantom;
  root.innerHTML = `
    <h1 class="view-title">What this means for a business like yours</h1>
    <p class="lede">The hub is the foundation. The roadmap below shows where a company usually starts and where this demo’s own results say to invest next.</p>
    <div class="card"><h2>A finding from this data: count more often</h2>
      <p style="margin:0 0 8px">Even after reconciling five systems, our stock estimate is exact on <b>${sc.headlines.estimate_exact}%</b> of days. About two-thirds of the remaining error is shrink that no system writes down. Only a physical count reveals them, and accuracy visibly decays as an item goes uncounted:</p>
      ${colChart(d.map(x => x.exact), d.map(x => x.label.replace('never counted', 'never')), { yMin: 90, yMax: 100, yFmt: v => Math.round(v) + '%', h: 170, ticks: 6, label: 'Accuracy by days since last count', colors: d.map((x, i) => (i >= d.length - 2 ? 'var(--series3)' : 'var(--series1)')) })}
      <p class="note">Share of days the estimate is exactly right, by time since the item was last counted (scored against the hidden truth; the axis starts at 90%). “Never counted” items are a separate group, not the oldest.</p>
      <p style="margin:8px 0 0"><b>The lever is a smarter count schedule</b>, not more modeling: count fast movers and items flagged “check this” first. Today the average position went ${n0(avgDays)} days since its last count.</p></div>
    <div class="sec"><h2>The maturity path</h2>
      <ol class="list" style="counter-reset:s">
        ${[['1', 'Get one trusted number', 'Land every source, reconcile identities, log every fix. This is what you are looking at.', 'Done in the demo'],
           ['2', 'Make exceptions routine', 'Named owners, suggested actions and alerts so problems are caught the night they start, not at the next count.', 'Done in the demo'],
           ['3', 'Decide with evidence', 'Forecast demand, size safety stock, test pricing and promotions to find what actually changes outcomes.', 'Beyond this demo'],
           ['4', 'Plan the counting and the network', 'Risk-ranked cycle counts, transfers between warehouses, supplier scorecards tied to dollars.', 'Next step suggested by the data above'],
           ['5', 'Run it live', 'Nightly refresh, monitoring, cost controls and a runbook so the team owns it without us.', 'Packaging phase']]
          .map(([n, t, b, tag]) => `<li><div class="row"><span class="t"><span class="chip info" style="margin-right:8px">${n}</span>${t}</span></div><div class="m" style="margin-top:4px">${b}</div><div style="margin-top:6px">${chip(tag, tag.startsWith('Done') ? 'good' : 'mute')}</div></li>`).join('')}</ol></div>
    <div class="sec"><h2>What it took to find ${ep ? usdK(ep.stuck_order_value) : 'the money'} of stuck orders</h2>
      <div class="card"><p style="margin:0">No new system. The phantom-stock alert uses data the company already had: order dates, ship dates and the book. It only needed them in one place, reconciled, and watched every night.</p></div></div>
    <div class="card sec"><h2>Want this on your data?</h2><p style="margin:0 0 10px">Managed Analytics builds this for small and mid-sized companies, as a fixed-scope project or a fractional data team. Start with one painful question; we will show you the answer on your own records.</p>${contact ? `<a class="btn primary" href="${esc(contact.url)}" rel="noopener">${esc(contact.label || 'Get in touch')}</a>` : ''}</div>`;
}
