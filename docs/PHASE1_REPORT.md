# System 1 — Phase 1 Report: Synthetic Universe

Result: **ALL CHECKS PASS** (38/38). Reproducibility tests were run in this pass.

## Volumes

| Table | Rows |
|---|---|
| Order lines | 609,574 |
| Orders | 182,521 |
| Stock movements | 718,851 |
| Purchase orders | 33,541 |
| PO lines | 73,858 |
| Transfers | 11,936 |
| Shipments (all modes) | 241,060 |
| Freight charge lines | 63,821 |
| Daily on-hand rows | 9,276,840 |

External-feed freight shipments (Carrier A + Carrier B): 28,183 (spec estimated ~125k; the simulated business ships far less by carrier because own fleet and will-call carry most deliveries).

## Checks

| Check | Measured | Criterion | Result |
|---|---|---|---|
| stock ledger reconciles to daily on-hand truth | 0 mismatches of 9,276,840 SKU-warehouse-days | 0 | PASS |
| on-hand never negative | min 0 | >= 0 | PASS |
| no line ships more than ordered | 0 lines | 0 | PASS |
| every ship movement references a known order line | 0 orphans | 0 | PASS |
| receipt movements equal PO-line received quantities (completed receipts) | 0 mismatches; 1,290 PO lines still in transit at end | 0 | PASS |
| completed transfers move identical quantity out and in | 0 unbalanced | 0 | PASS |
| foreign keys resolve (lines, orders, POs, charges) | 0 orphans | 0 | PASS |
| no duplicate SKU within an order (keeps defect E2 distinguishable) | 0 duplicates | 0 | PASS |
| no shipping on closed days, no receiving on non-receiving days | 0 violations | 0 | PASS |
| SKU lifecycle respected (no demand outside intro/discontinue window) | 0 violations | 0 | PASS |
| movement local times stay 07:00-17:59 in every month for every warehouse (DST handled; LV/ABQ/ELP shift 1h in UTC) | local hours 7-17 across 72 warehouse-months; Jan+Jul checked 12 | 07-17 | PASS |
| order lines in window | 608,957 | 612,000 ±3% | PASS |
| orders in window | 181,960 | 180,000 ±5% | PASS |
| lines per order | 3.35 | 3.4 ±0.2 | PASS |
| annual revenue (ordered, window average) | $49.6M | $48M ±6% | PASS |
| active SKUs at end of history | 2,500 | 2,500 | PASS |
| total SKUs incl. discontinued | 2,800 | 2,800 | PASS |
| SKUs with an ambiguous legacy code (feeds defect L1) | 6.1% | ~6% (5-7%) | PASS |
| warehouses / customers / vendors | 6 / 1,600 / 140 | 6 / 1,600 / 140 | PASS |
| same-day full line fill rate | 95.5% | 92-99% | PASS |
| inventory turns (COGS / average inventory) | 3.83 (avg inventory $9.9M) | 3-8 | PASS |
| shrink as % of average inventory value per year | 0.30% | 0.2-0.45% | PASS |
| external carrier freight as % of revenue | 6.7% ($3.3M/yr) | 2-7% | PASS |
| A-item SKU-warehouse-days at zero stock | 2.2% | 0.5-5% | PASS |
| seasonality: Roofing July / January lines | 2.73x | 2.0-3.2x | PASS |
| seasonality: Insulation January / July lines | 1.99x | 1.6-2.6x | PASS |
| seasonality: HVAC peaks in both summer and winter (bimodal) | peaks/shoulder-spring = 1.81x | > 1.15x | PASS |
| Pareto: top 20% of SKUs share of lines | 66% | 65-90% | PASS |
| Saturday volume relative to Tue-Thu | 0.34 | 0.35 ±0.12 | PASS |
| customer concentration: top 10% of accounts' revenue share | 41% | 30-65% | PASS |
| share of lines backordered at any point | 4.5% | <= 8% | PASS |
| S1 Albuquerque phantom stock: true on-hand collapses after the loss | 125 -> 6.9 units/SKU | post <= 15% of pre | PASS |
| S1: unfilled demand accumulated while the book showed stock | 6,248 backordered units at discovery | >= 1,000 | PASS |
| S1: stock recovers after discovery and restock | 89 units/SKU 45d after discovery | >= 50% of pre-loss | PASS |
| S5 Las Vegas surge: out-of-stock share, surge window vs same window prior year | 17.8% vs 3.3% | >= 3x and >= 8% | PASS |
| S5: demand multiplier realised (surge YoY / same SKUs' non-surge YoY, which controls for growth and noise) | 2.60x (869 vs 287 lines) | 2.0-2.8x (nominal 2.4) | PASS |
| same seed reproduces every truth table bit-for-bit | 20/20 tables identical | all | PASS |
| live clock: resuming from saved state matches a continuous run (3 days) | identical | identical | PASS |
