// Router, navigation and theme. Each view is a module exporting render(root).
import { getJSON, getOptional, dshort, addDays, WH_NAMES } from './lib.js';

const ICON = {
  home: '<path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10" />',
  stock: '<path d="M3 7l9-4 9 4-9 4-9-4zM3 12l9 4 9-4M3 17l9 4 9-4" />',
  risk: '<path d="M12 3l10 18H2L12 3zM12 10v5M12 18v.5" />',
  exceptions: '<circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 16.5v.5" />',
  freight: '<path d="M2 6h12v10H2zM14 9h4l4 4v3h-8zM6 19a2 2 0 100-4 2 2 0 000 4zM18 19a2 2 0 100-4 2 2 0 000 4z" />',
  health: '<path d="M3 12h4l2-6 4 12 2-6h6" />',
  scorecard: '<path d="M5 3h14v18H5zM9 8h6M9 12h6M9 16h3" />',
  roadmap: '<path d="M4 20c4 0 4-8 8-8s4-8 8-8M4 20h.01M20 4h.01" />',
  more: '<circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" />',
};
const svg = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;
const ROUTES = [
  { id: 'overview', label: 'Overview', icon: 'home', mod: './views/overview.js', main: true },
  { id: 'stock', label: 'Stock', icon: 'stock', mod: './views/stock.js', main: true },
  { id: 'risk', label: 'Risk & inbound', short: 'Risk', icon: 'risk', mod: './views/risk.js', main: true },
  { id: 'exceptions', label: 'Exceptions', icon: 'exceptions', mod: './views/exceptions.js', main: true },
  { id: 'freight', label: 'Freight', icon: 'freight', mod: './views/freight.js' },
  { id: 'health', label: 'Pipeline health', icon: 'health', mod: './views/health.js' },
  { id: 'scorecard', label: 'Scorecard', icon: 'scorecard', mod: './views/scorecard.js' },
  { id: 'roadmap', label: 'Roadmap', icon: 'roadmap', mod: './views/roadmap.js' },
];
const main = document.getElementById('main');
const nav = document.getElementById('nav');
const more = document.getElementById('more');
let phantom = false, asOf = '';

function buildNav(current) {
  const mains = ROUTES.filter(r => r.main), rest = ROUTES.filter(r => !r.main);
  const dot = r => (r.id === 'exceptions' && phantom ? '<span class="dot" title="An alert needs attention"></span>' : '');
  nav.innerHTML = mains.map(r => `<a href="#/${r.id}" ${current === r.id ? 'aria-current="page"' : ''}>${svg(r.icon)}<span>${r.short || r.label}</span>${dot(r)}</a>`).join('') +
    rest.map(r => `<a class="only-desktop" href="#/${r.id}" ${current === r.id ? 'aria-current="page"' : ''}>${svg(r.icon)}<span>${r.label}</span></a>`).join('') +
    `<button class="more-toggle only-mobile" id="more-toggle" aria-expanded="false" aria-controls="more">${svg('more')}<span>More</span></button>`;
  more.innerHTML = rest.map(r => `<a href="#/${r.id}" role="menuitem" ${current === r.id ? 'aria-current="page"' : ''}>${svg(r.icon)}${r.label}</a>`).join('');
  document.getElementById('more-toggle').onclick = e => { const open = more.classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', open); };
  if (rest.some(r => r.id === current)) document.getElementById('more-toggle').setAttribute('aria-current', 'page');
}
more.addEventListener('click', () => more.classList.remove('open'));

async function route() {
  more.classList.remove('open');
  const id = (location.hash.replace(/^#\/?/, '').split('?')[0]) || 'overview';
  const r = ROUTES.find(x => x.id === id) || ROUTES[0];
  document.title = `${r.label} · Operations Hub Demo`;
  buildNav(r.id);
  main.innerHTML = '<div class="loading">Loading…</div>';
  try {
    const mod = await import(r.mod);
    await mod.render(main);
    main.insertAdjacentHTML('afterbegin', `<p class="asof-line">Data as of <b>${dshort(asOf)}</b> · all figures synthetic</p>`);
    main.insertAdjacentHTML('beforeend', '<p class="foot">All data in this demo is synthetic. Northfield Supply Co. is a made-up company; every defect in the source systems was planted and then scored against the answer key.</p>');
  } catch (e) {
    console.error(e);
    main.innerHTML = `<div class="card"><h2>This view could not load</h2><p class="note">${String(e.message).replace(/</g, '&lt;')}</p></div>`;
  }
  window.scrollTo(0, 0);
  main.focus({ preventScroll: true });
}

function theme() {
  const k = 'opshub-theme';
  let saved = null;
  try { saved = localStorage.getItem(k); } catch (e) { /* storage may be blocked */ }
  if (saved) document.documentElement.dataset.theme = saved;
  document.getElementById('theme').onclick = () => {
    const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
    const next = dark ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(k, next); } catch (e) { /* ignore */ }
  };
}

(async function init() {
  theme();
  const [meta, ov, live] = await Promise.all([getJSON('meta.json'), getJSON('overview.json'), getOptional('live.json')]);
  if (live && live.days_live > 0) { const el = document.getElementById('live'); el.hidden = false; el.textContent = `LIVE · day ${live.days_live}`; el.title = `The demo clock advances one simulated day per real day. Latest run finished for ${live.sim_date}.`; }
  meta.warehouses.forEach(w => { WH_NAMES[w.wh_code] = w.name; });
  asOf = meta.as_of;
  phantom = !!ov.phantom && ov.phantom.last_alert_date >= addDays(meta.as_of, -3);
  document.getElementById('asof').innerHTML = `Data as of<br><b>${dshort(meta.as_of)}</b>`;
  window.addEventListener('hashchange', route);
  route();
})().catch(e => { main.innerHTML = `<div class="card"><h2>The data files did not load</h2><p class="note">${String(e.message)}. Serve this folder over HTTP and run the exporter first.</p></div>`; });
