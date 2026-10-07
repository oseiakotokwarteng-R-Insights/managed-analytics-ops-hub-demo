import { getJSON, esc, n0, n1, pct, usdK, usd, dshort, chip } from '../lib.js';

export async function render(root) {
  const [o, sc, st] = await Promise.all([getJSON('overview.json'), getJSON('scorecard.json'), getJSON('stock.json')]);
  const cnt = st.count_accuracy.filter(r => r.month >= '2025-10-01');
  const counted = cnt.reduce((a, r) => a + r.items_counted, 0), exact = cnt.reduce((a, r) => a + r.exact_rate * r.items_counted, 0) / counted;
  const h = sc.headlines, ep = o.phantom;
  const healthy = o.health_today.health === 'green';
  const card = (n, href, ask, big, why, extra = '') => `<a class="card q" href="#/${href}"><div class="qn">Question ${n}${extra}</div><div class="ask">${ask}</div><div class="big num">${big}</div><div class="why">${why}</div></a>`;
  root.innerHTML = `
    <h1 class="view-title">Eight questions, answered from five messy systems</h1>
    <p class="lede">A distributor runs on an ERP, a warehouse system, two freight carriers, an old Access-style database and spreadsheets. None agree. This hub reconciles them every night and answers the questions below. Tap any card to go deeper.</p>
    <div class="banner ${healthy ? 'good' : 'warn'}"><div class="row"><h3>Last night’s run: ${healthy ? 'all clear' : esc(o.health_today.health)}</h3>${chip(`${o.health_30d.green} green · ${o.health_30d.amber} amber · ${o.health_30d.red} red in the last 30 nights`, 'mute')}</div>
      <div class="note">${o.streams - o.streams_late} of ${o.streams} source feeds on time · ${o.layers_ok} of ${o.layers} row-count checks balance · ${o.tests.passed} of ${o.tests.n} model tests pass</div></div>
    <div class="grid c2 c4d">
      ${card(1, 'stock', 'How many can I promise today?', n0(o.atp_units), `units available to promise across ${n0(o.skus)} items and 6 warehouses. Look up any item as of any past date.`)}
      ${card(2, 'risk', 'What is about to run out?', n0(o.at_risk + o.out_of_stock), `item-warehouse pairs: ${n0(o.at_risk)} will run out within 14 days and ${n0(o.out_of_stock)} already have. Transfers suggested.`)}
      ${card(3, 'stock', 'How accurate are our records?', pct(exact, 0), `of ${n0(counted)} physical counts in the last 12 months matched the book exactly. Our rebuilt estimate is right on ${h.estimate_exact}% of days against ${h.recorded_exact}% for the systems’ own number.`)}
      ${card(4, 'risk', 'What is inbound, and what is late?', n0(o.inbound.open_lines), `open purchase-order lines worth ${usdK(o.inbound.open_value)}; ${n0(o.inbound.overdue_lines)} are overdue (${usdK(o.inbound.overdue_value)}).`)}
      ${card(5, 'freight', 'What does freight cost?', usdK(o.freight_30d.cost), `over the last 30 days on ${n0(o.freight_30d.shipments)} shipments; ${pct(o.freight_30d.slow_rate)} ran slow. ${usdK(o.recoverable_freight)} of duplicate carrier charges flagged for dispute.`)}
      ${card(6, 'exceptions', 'Which orders did bad records hurt?', ep ? n0(ep.stuck_order_lines) : '0', ep ? `order lines at ${esc(ep.wh_name)} sat unshipped because the book showed stock that was gone (${usdK(ep.stuck_order_value)}). Flagged ${n0(ep.alert_days_before_count)} days before a count found it.` : 'No phantom-stock episodes found.')}
      ${card(7, 'health', 'Can I trust today’s numbers?', healthy ? 'Yes' : 'Check', `freshness, completeness, quarantine counts and ${n0(o.review_rows)} rows routed to a named owner. Failures are shown, not hidden.`)}
      ${card(8, 'scorecard', 'How much manual work does this replace?', `${n0(o.manual.automated)} h`, `modeled estimate over two years (assumptions shown); ${n0(o.manual.remaining)} h of judgment calls remain for people.`, ' ' + chip('MODELED', 'info'))}
    </div>
    <div class="card sec"><h2>What makes this demo different</h2>
      <p style="margin:0 0 8px">Every defect was planted on purpose, in the style real systems produce them, and logged in a hidden answer key. The scorecard compares what the pipeline found and fixed against that key, <b>including the targets it missed</b>.</p>
      <a class="btn" href="#/scorecard">See the scorecard</a> <a class="btn" href="#/roadmap">What this means for your business</a></div>`;
}
