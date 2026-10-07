# System 1 — Data Dictionary

Generated from the built warehouse by `python -m generator.data_dictionary`. All data is synthetic. Row counts are as of the end of history (2026-09-30), before the live clock moves.

Where to start: the **marts** answer the business questions; **core** holds the cleaned facts they are built from; **ops** explains whether today's numbers can be trusted; **raw** is the unaltered evidence.

108 tables and views are documented.


## Raw layer (`raw`)

Files exactly as received, every column text, append-only. Each row carries `_file_id` and `_row_num` so any figure can be traced to the file and line it came from. `raw._load_*`, `_file_registry`, `_schema_drift` and `_alerts` are the loader's own audit trail.

### `raw._alerts`

Table, 4 rows. Loader alerts: held files, failures, releases.

| Column | Type |
|---|---|
| `alert_id` | BIGINT |
| `run_id` | BIGINT |
| `as_of` | DATE |
| `severity` | VARCHAR |
| `table_name` | VARCHAR |
| `rel_path` | VARCHAR |
| `code` | VARCHAR |
| `message` | VARCHAR |
| `resolved_run_id` | BIGINT |
| `resolved_as_of` | DATE |

### `raw._file_registry`

Table, 9,057 rows. The current state of every file the loader has seen.

| Column | Type |
|---|---|
| `rel_path` | VARCHAR |
| `table_name` | VARCHAR |
| `sha256` | VARCHAR |
| `version` | INTEGER |
| `size_bytes` | BIGINT |
| `mtime_ns` | BIGINT |
| `status` | VARCHAR |
| `file_id` | BIGINT |
| `updated_run_id` | BIGINT |

### `raw._load_files`

Table, 9,061 rows. One row per file version loaded (or held, or failed).

| Column | Type |
|---|---|
| `file_id` | BIGINT |
| `run_id` | BIGINT |
| `table_name` | VARCHAR |
| `rel_path` | VARCHAR |
| `sha256` | VARCHAR |
| `version` | INTEGER |
| `size_bytes` | BIGINT |
| `rows_loaded` | BIGINT |
| `status` | VARCHAR |
| `contract_version` | VARCHAR |
| `arrival` | DATE |
| `loaded_ts` | TIMESTAMP |
| `duration_ms` | DOUBLE |
| `profile_json` | VARCHAR |
| `message` | VARCHAR |

### `raw._load_runs`

Table, 730 rows. One row per nightly load run.

| Column | Type |
|---|---|
| `run_id` | BIGINT |
| `as_of` | DATE |
| `run_ts` | TIMESTAMP |
| `finished_ts` | TIMESTAMP |
| `status` | VARCHAR |
| `files_seen` | INTEGER |
| `files_loaded` | INTEGER |
| `files_held` | INTEGER |
| `files_failed` | INTEGER |
| `files_released` | INTEGER |
| `rows_loaded` | BIGINT |
| `duration_s` | DOUBLE |

### `raw._schema_drift`

Table, 5 rows. Every column-layout change the loader noticed, and what it did about it.

| Column | Type |
|---|---|
| `drift_id` | BIGINT |
| `run_id` | BIGINT |
| `detected_as_of` | DATE |
| `table_name` | VARCHAR |
| `rel_path` | VARCHAR |
| `kind` | VARCHAR |
| `added` | VARCHAR |
| `missing` | VARCHAR |
| `action` | VARCHAR |
| `resolved_run_id` | BIGINT |
| `resolved_as_of` | DATE |
| `resolution` | VARCHAR |

### `raw.carrier_a_shipments`

Table, 68,947 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `bol_no` | VARCHAR |
| `pro_no` | VARCHAR |
| `shipper_ref` | VARCHAR |
| `service` | VARCHAR |
| `origin` | VARCHAR |
| `destination` | VARCHAR |
| `pieces` | VARCHAR |
| `weight_lb` | VARCHAR |
| `status` | VARCHAR |
| `events` | VARCHAR |
| `charges` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.carrier_b_charges`

Table, 23,880 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `charge_code` | VARCHAR |
| `amount` | VARCHAR |
| `invoice_no` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.carrier_b_shipments`

Table, 10,002 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `reference` | VARCHAR |
| `ship_ts_local` | VARCHAR |
| `service` | VARCHAR |
| `weight_lb` | VARCHAR |
| `pieces` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |
| `service_level` | VARCHAR |
| `delivery_type` | VARCHAR |
| `wt_lbs` | VARCHAR |
| `dim_weight` | VARCHAR |

### `raw.carrier_b_tracking`

Table, 56,886 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `event_ts_local` | VARCHAR |
| `status` | VARCHAR |
| `location` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_customer_master`

Table, 1,600 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `cust_acct` | VARCHAR |
| `name` | VARCHAR |
| `cust_type` | VARCHAR |
| `ship_to_city` | VARCHAR |
| `default_wh` | VARCHAR |
| `terms` | VARCHAR |
| `discount_pct` | VARCHAR |
| `created_date` | VARCHAR |
| `inactive_date` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_item_master`

Table, 2,800 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `description` | VARCHAR |
| `category` | VARCHAR |
| `uom` | VARCHAR |
| `case_qty` | VARCHAR |
| `case_uom` | VARCHAR |
| `list_price` | VARCHAR |
| `std_cost` | VARCHAR |
| `weight_lb` | VARCHAR |
| `vendor_no` | VARCHAR |
| `status` | VARCHAR |
| `superseded_by` | VARCHAR |
| `created_date` | VARCHAR |
| `wms_item_id` | VARCHAR |
| `wms_link_date` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_po_header`

Table, 66,418 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `extract_date` | VARCHAR |
| `po_no` | VARCHAR |
| `vendor_no` | VARCHAR |
| `ship_to_wh` | VARCHAR |
| `po_date` | VARCHAR |
| `promised_date` | VARCHAR |
| `status` | VARCHAR |
| `received_date` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_po_line`

Table, 146,315 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `extract_date` | VARCHAR |
| `po_no` | VARCHAR |
| `line_no` | VARCHAR |
| `item_no` | VARCHAR |
| `qty_ordered` | VARCHAR |
| `uom` | VARCHAR |
| `unit_cost` | VARCHAR |
| `qty_received` | VARCHAR |
| `received_date` | VARCHAR |
| `status` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_sales_order_header`

Table, 208,319 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `extract_date` | VARCHAR |
| `order_no` | VARCHAR |
| `cust_acct` | VARCHAR |
| `order_ts_local` | VARCHAR |
| `req_date` | VARCHAR |
| `ship_via` | VARCHAR |
| `status` | VARCHAR |
| `last_modified` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_sales_order_line`

Table, 645,442 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `extract_date` | VARCHAR |
| `order_no` | VARCHAR |
| `line_no` | VARCHAR |
| `item_no` | VARCHAR |
| `qty_ordered` | VARCHAR |
| `qty_shipped` | VARCHAR |
| `uom` | VARCHAR |
| `unit_price` | VARCHAR |
| `ship_wh` | VARCHAR |
| `status` | VARCHAR |
| `last_ship_date` | VARCHAR |
| `last_modified` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_vendor_master`

Table, 140 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `vendor_no` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `quoted_lead_time_days` | VARCHAR |
| `is_import` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.erp_warehouse_master`

Table, 6 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `timezone` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.legacy_inv_trans`

Table, 80,754 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `trans_id` | VARCHAR |
| `item_code` | VARCHAR |
| `trans_type` | VARCHAR |
| `trans_date` | VARCHAR |
| `qty` | VARCHAR |
| `unit_cost` | VARCHAR |
| `ref_no` | VARCHAR |
| `party_id` | VARCHAR |
| `entry_terminal` | VARCHAR |
| `memo` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.legacy_item_cost`

Table, 14,000 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `item_code` | VARCHAR |
| `vendor_id` | VARCHAR |
| `std_cost` | VARCHAR |
| `eff_date` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.legacy_vendor`

Table, 147 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `vendor_id` | VARCHAR |
| `vendor_name` | VARCHAR |
| `address` | VARCHAR |
| `city_state` | VARCHAR |
| `phone` | VARCHAR |
| `terms` | VARCHAR |
| `status` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.sheet_cells`

Table, 33,764 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `sheet_kind` | VARCHAR |
| `sheet_name` | VARCHAR |
| `sheet_row` | VARCHAR |
| `c1` | VARCHAR |
| `c2` | VARCHAR |
| `c3` | VARCHAR |
| `c4` | VARCHAR |
| `c5` | VARCHAR |
| `c6` | VARCHAR |
| `c7` | VARCHAR |
| `c8` | VARCHAR |
| `c9` | VARCHAR |
| `c10` | VARCHAR |
| `cell_types` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `raw.wms_events`

Table, 1,844,284 rows. Rows exactly as received from the source files, all text, with file and row lineage.

| Column | Type |
|---|---|
| `event_id` | VARCHAR |
| `warehouse` | VARCHAR |
| `event_type` | VARCHAR |
| `event_ts` | VARCHAR |
| `published_at` | VARCHAR |
| `item_id` | VARCHAR |
| `quantity` | VARCHAR |
| `direction` | VARCHAR |
| `uom` | VARCHAR |
| `bin` | VARCHAR |
| `ref_type` | VARCHAR |
| `ref_no` | VARCHAR |
| `operator` | VARCHAR |
| `reason` | VARCHAR |
| `schema_version` | VARCHAR |
| `batch_id` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |


## Staging (`staging`)

One model per source table: types fixed, names made consistent, nothing joined or judged yet.

### `staging.stg_carrier_a__shipment_versions`

View, 68,947 rows. Carrier A emits the non-standard JSON token NaN for unknown cities; normalise to null before parsing.

| Column | Type |
|---|---|
| `bol_no` | VARCHAR |
| `pro_no` | VARCHAR |
| `shipper_ref` | VARCHAR |
| `service` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `pieces` | INTEGER |
| `weight_lb` | DOUBLE |
| `status` | VARCHAR |
| `events_json` | VARCHAR |
| `charges_json` | VARCHAR |
| `n_events` | UBIGINT |
| `has_charges` | BOOLEAN |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_carrier_b__charge`

View, 23,880 rows.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `charge_code` | VARCHAR |
| `amount` | DOUBLE |
| `invoice_no` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_carrier_b__shipment`

View, 10,002 rows. Carrier B before and after the 2026-06-04 schema change, mapped to one shape per contract v1 / v2.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `reference` | VARCHAR |
| `ship_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `weight_lb` | DOUBLE |
| `dim_weight_lb` | DOUBLE |
| `pieces` | INTEGER |
| `service_level` | VARCHAR |
| `delivery_type` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `is_contract_v2` | BOOLEAN |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_carrier_b__tracking`

View, 56,886 rows.

| Column | Type |
|---|---|
| `tracking_no` | VARCHAR |
| `event_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `status` | VARCHAR |
| `location` | VARCHAR |

### `staging.stg_erp__customer`

View, 1,600 rows.

| Column | Type |
|---|---|
| `cust_acct` | VARCHAR |
| `name` | VARCHAR |
| `cust_type` | VARCHAR |
| `ship_to_city` | VARCHAR |
| `default_wh` | VARCHAR |
| `terms` | VARCHAR |
| `discount_pct` | DOUBLE |
| `created_date` | DATE |
| `inactive_date` | DATE |

### `staging.stg_erp__item`

View, 2,800 rows. ERP item master: the system of record for item identity. Latest snapshot wins.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `description` | VARCHAR |
| `category` | VARCHAR |
| `uom` | VARCHAR |
| `case_qty` | INTEGER |
| `case_uom` | VARCHAR |
| `list_price` | DOUBLE |
| `std_cost` | DOUBLE |
| `weight_lb` | DOUBLE |
| `vendor_no` | VARCHAR |
| `status` | VARCHAR |
| `superseded_by` | VARCHAR |
| `created_date` | DATE |
| `wms_item_id` | BIGINT |
| `wms_link_date` | DATE |

### `staging.stg_erp__po_header_versions`

View, 66,418 rows.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `vendor_no` | VARCHAR |
| `ship_to_wh` | VARCHAR |
| `po_date` | DATE |
| `promised_date` | DATE |
| `status` | VARCHAR |
| `received_date` | DATE |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_erp__po_line_versions`

View, 146,315 rows.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `qty_ordered` | DOUBLE |
| `unit_cost` | DOUBLE |
| `qty_received` | DOUBLE |
| `received_date` | DATE |
| `status` | VARCHAR |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_erp__so_header_versions`

View, 208,319 rows.

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `cust_acct` | VARCHAR |
| `order_ts_local` | TIMESTAMP |
| `req_date` | DATE |
| `ship_via` | VARCHAR |
| `status` | VARCHAR |
| `last_modified_local` | TIMESTAMP |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_erp__so_line_versions`

View, 645,442 rows. Every version of every sales-order line, as extracted nightly. Quantities may be in cases (uom = 'CS').

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `qty_ordered` | DOUBLE |
| `qty_shipped` | DOUBLE |
| `uom` | VARCHAR |
| `unit_price` | DOUBLE |
| `ship_wh` | VARCHAR |
| `status` | VARCHAR |
| `last_ship_date` | DATE |
| `last_modified_local` | TIMESTAMP |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `staging.stg_erp__vendor`

View, 140 rows.

| Column | Type |
|---|---|
| `vendor_no` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `quoted_lead_time_days` | INTEGER |
| `is_import` | BOOLEAN |

### `staging.stg_erp__warehouse`

View, 6 rows.

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `timezone` | VARCHAR |

### `staging.stg_legacy__trans`

Table, 80,754 rows. Legacy inventory transactions: text columns parsed. Dates follow the entering terminal's format (T1 MM/DD/YY, T2 DD-Mon-YYYY); a blank terminal leaves the date ambiguous when both readings are valid and differ (resolved against ERP evidence downstream).

| Column | Type |
|---|---|
| `trans_id` | VARCHAR |
| `legacy_code` | VARCHAR |
| `trans_type` | VARCHAR |
| `trans_date_raw` | VARCHAR |
| `terminal` | VARCHAR |
| `d_mdy` | DATE |
| `d_dmy` | DATE |
| `d_mon` | DATE |
| `qty_raw` | VARCHAR |
| `qty` | INTEGER |
| `unit_cost` | DOUBLE |
| `ref_no` | VARCHAR |
| `party_id` | VARCHAR |
| `memo` | VARCHAR |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |
| `dump_date` | DATE |
| `trans_date` | DATE |
| `date_ambiguous` | BOOLEAN |

### `staging.stg_legacy__vendor`

View, 147 rows.

| Column | Type |
|---|---|
| `vendor_id` | VARCHAR |
| `vendor_name` | VARCHAR |
| `address` | VARCHAR |
| `city_state` | VARCHAR |
| `phone` | VARCHAR |
| `terms` | VARCHAR |
| `status` | VARCHAR |

### `staging.stg_sheets__count_row`

Table, 23,541 rows. Cycle-count sheets. Structure is interpreted here: find the header row (names vary by branch and month), keep rows that carry a numeric count, drop category banners, subtotal formulas, blank rows and notes.

| Column | Type |
|---|---|
| `rel_path` | VARCHAR |
| `sheet_row` | INTEGER |
| `wh_code` | VARCHAR |
| `file_month` | VARCHAR |
| `sku_raw` | VARCHAR |
| `description` | VARCHAR |
| `bin` | VARCHAR |
| `uom` | VARCHAR |
| `counted_qty` | DOUBLE |
| `counted_by` | VARCHAR |
| `date_raw` | VARCHAR |
| `date_type` | VARCHAR |
| `count_date` | DATE |
| `note` | VARCHAR |

### `staging.stg_sheets__price_row`

View, 5,935 rows.

| Column | Type |
|---|---|
| `rel_path` | VARCHAR |
| `sheet_row` | INTEGER |
| `vendor_name` | VARCHAR |
| `item_no` | VARCHAR |
| `override_cost` | DOUBLE |
| `effective_date` | DATE |
| `entered_on` | TIMESTAMP |
| `entered_by` | VARCHAR |

### `staging.stg_wms__event`

Table, 1,811,717 rows. WMS events, de-duplicated on event_id (at-least-once delivery re-sends the same event), typed, with the local business date.

| Column | Type |
|---|---|
| `event_id` | VARCHAR |
| `wh_code` | VARCHAR |
| `event_type` | VARCHAR |
| `event_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `published_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `item_id` | BIGINT |
| `quantity` | INTEGER |
| `direction` | VARCHAR |
| `bin` | VARCHAR |
| `ref_type` | VARCHAR |
| `ref_no` | VARCHAR |
| `reason` | VARCHAR |
| `n_copies` | BIGINT |
| `local_date` | DATE |


## Intermediate (`intermediate`)

Working steps that resolve identities, repair what the evidence supports and match records across systems. Not meant to be read directly.

### `intermediate.int_book_daily`

Table, 584,124 rows. The systems' own book quantity (everything recorded plus inferred movements), cumulative by item, warehouse and day.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `local_date` | DATE |
| `cum_book` | HUGEINT |

### `intermediate.int_carrier_a__charge`

Table, 40,008 rows.

| Column | Type |
|---|---|
| `bol_no` | VARCHAR |
| `line_id` | VARCHAR |
| `charge_code` | VARCHAR |
| `amount` | DOUBLE |

### `intermediate.int_carrier_a__event`

Table, 105,827 rows.

| Column | Type |
|---|---|
| `bol_no` | VARCHAR |
| `event_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `status` | VARCHAR |
| `location` | VARCHAR |

### `intermediate.int_carrier_a__latest`

Table, 18,181 rows. A shipment appears in several daily files as it progresses (and in re-sent files). Keep the most complete version.

| Column | Type |
|---|---|
| `bol_no` | VARCHAR |
| `pro_no` | VARCHAR |
| `shipper_ref` | VARCHAR |
| `service` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `pieces` | INTEGER |
| `weight_lb` | DOUBLE |
| `status` | VARCHAR |
| `events_json` | VARCHAR |
| `charges_json` | VARCHAR |
| `n_events` | UBIGINT |
| `has_charges` | BOOLEAN |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `intermediate.int_doc_shipped_weight`

Table, 239,683 rows. What each order shipped (by ship date) and each PO received (by receipt date), in pounds. Used as evidence when matching carrier shipments.

| Column | Type |
|---|---|
| `doc_no` | VARCHAR |
| `d` | DATE |
| `w` | DOUBLE |

### `intermediate.int_erp__po_header_current`

Table, 33,541 rows.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `vendor_no` | VARCHAR |
| `ship_to_wh` | VARCHAR |
| `po_date` | DATE |
| `promised_date` | DATE |
| `status` | VARCHAR |
| `received_date` | DATE |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `intermediate.int_erp__po_line_current`

Table, 73,858 rows.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `qty_ordered` | DOUBLE |
| `unit_cost` | DOUBLE |
| `qty_received` | DOUBLE |
| `received_date` | DATE |
| `status` | VARCHAR |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `intermediate.int_erp__so_header_current`

Table, 183,658 rows.

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `cust_acct` | VARCHAR |
| `order_ts_local` | TIMESTAMP |
| `req_date` | DATE |
| `ship_via` | VARCHAR |
| `status` | VARCHAR |
| `last_modified_local` | TIMESTAMP |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `intermediate.int_erp__so_line_current`

Table, 613,308 rows. Latest version of every sales-order line (nightly extracts carry every change).

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `qty_ordered` | DOUBLE |
| `qty_shipped` | DOUBLE |
| `uom` | VARCHAR |
| `unit_price` | DOUBLE |
| `ship_wh` | VARCHAR |
| `status` | VARCHAR |
| `last_ship_date` | DATE |
| `last_modified_local` | TIMESTAMP |
| `extract_date` | DATE |
| `_file_id` | BIGINT |
| `_row_num` | INTEGER |

### `intermediate.int_erp__so_line_first`

Table, 613,308 rows. First version of every line: the quantity as originally entered (before any post-shipment change).

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no_first` | VARCHAR |
| `qty_ordered_first` | DOUBLE |
| `uom_first` | VARCHAR |

### `intermediate.int_input_gaps`

Table, 1,118 rows. Item/warehouse/day combinations where a recorded movement could not be used (unparseable quantity, unresolved item). Stock estimates are flagged from that day until the next count.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `local_date` | DATE |
| `reason` | VARCHAR |

### `intermediate.int_legacy__resolved`

Table, 80,754 rows. Resolve each legacy transaction to an ERP item and a calendar date. date: ambiguous DD/MM vs MM/DD readings are settled against ERP evidence (order ship dates, PO receipt dates) when available. item: the 8-char code can map to several revisions. Tiers: (1) only one candidate exists on that date, (2) the candidate that the referenced PO / order / hub transfer actually contains, (3) otherwise left unresolved (review queue).

| Column | Type |
|---|---|
| `trans_id` | VARCHAR |
| `date_resolved` | DATE |
| `date_ambiguous` | BOOLEAN |
| `date_unresolved` | BOOLEAN |
| `n_candidates_at_date` | BIGINT |
| `item_no` | VARCHAR |
| `item_resolution` | VARCHAR |
| `candidate_items` | VARCHAR[] |

### `intermediate.int_shipment_raw`

Table, 28,183 rows. Both carriers in one shape, before reference matching and cleaning.

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `shipment_key` | VARCHAR |
| `ref_raw` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `weight_lb_reported` | DOUBLE |
| `pieces_reported` | INTEGER |
| `pickup_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `delivered_ts_raw` | TIMESTAMP WITH TIME ZONE |

### `intermediate.int_shipment_ref_match`

Table, 28,183 rows. F2: carrier references arrive with case, hyphen and zero-padding variants, and the occasional keyed digit error. A keyed error can land exactly on ANOTHER valid order number, so no match is trusted on the number alone. A document is accepted only if its evidence agrees with the shipment: ship date (orders) or receipt date (POs) within a day, the shipped/received weight, and the cities. 1. normalise the reference and test the document it names; 2. if that fails the evidence (or does not exist), take the single document one edit away that does agree; 3. otherwise review. Nothing is guessed.

| Column | Type |
|---|---|
| `shipment_key` | VARCHAR |
| `carrier` | VARCHAR |
| `ref_raw` | VARCHAR |
| `ref_norm` | VARCHAR |
| `doc_no` | VARCHAR |
| `match_method` | VARCHAR |
| `status` | VARCHAR |

### `intermediate.int_stream_gaps`

Table, 0 rows. A warehouse feed that has gone quiet: from the first expected working day (Monday to Saturday, not a holiday) with no events at all, up to the build date. While it lasts, that warehouse's stock estimates cannot be trusted and are marked suspect. When the feed catches up, the next build has events for those days and the flag disappears.

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `local_date` | DATE |

### `intermediate.int_wms__order_items`

Table, 541,702 rows. What the warehouse actually picked for each order, by ERP item. Independent evidence about what was ordered.

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `item_no` | VARCHAR |
| `picked_qty` | HUGEINT |

### `intermediate.int_wms__receipt_fix`

Table, 514 rows. W5: a receipt keyed under the wrong item. The WMS receipt carries the PO number; the ERP PO lists the items actually ordered. A receipt whose item is not on its PO, while exactly one PO line has no receipt that fits the quantity, was keyed to the wrong item.

| Column | Type |
|---|---|
| `event_id` | VARCHAR |
| `po_no` | VARCHAR |
| `recorded_item_no` | VARCHAR |
| `corrected_item_no` | VARCHAR |
| `quantity` | INTEGER |
| `local_date` | DATE |
| `wh_code` | VARCHAR |
| `status` | VARCHAR |
| `rule` | VARCHAR |


## Core (`core`)

Conformed dimensions and facts, plus the reconciliation tables that list what disagrees. The review queue lives here.

### `core.dim_customer`

Table, 1,600 rows.

| Column | Type |
|---|---|
| `cust_acct` | VARCHAR |
| `name` | VARCHAR |
| `cust_type` | VARCHAR |
| `ship_to_city` | VARCHAR |
| `default_wh` | VARCHAR |
| `default_wh_missing` | BOOLEAN |
| `terms` | VARCHAR |
| `discount_pct` | DOUBLE |
| `created_date` | DATE |
| `inactive_date` | DATE |

### `core.dim_sku`

Table, 2,800 rows. One row per ERP item. The ERP is the system of record for item identity; every other system maps to item_no through core.xwalk_sku.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `description` | VARCHAR |
| `category` | VARCHAR |
| `uom` | VARCHAR |
| `case_qty` | INTEGER |
| `case_uom` | VARCHAR |
| `list_price` | DOUBLE |
| `std_cost` | DOUBLE |
| `weight_lb` | DOUBLE |
| `vendor_no` | VARCHAR |
| `status` | VARCHAR |
| `superseded_by` | VARCHAR |
| `predecessor_item_no` | VARCHAR |
| `created_date` | DATE |
| `wms_item_id` | BIGINT |
| `wms_link_date` | DATE |
| `legacy_code` | VARCHAR |

### `core.dim_vendor`

Table, 140 rows.

| Column | Type |
|---|---|
| `vendor_no` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `quoted_lead_time_days` | INTEGER |
| `is_import` | BOOLEAN |

### `core.dim_warehouse`

Table, 6 rows.

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `name` | VARCHAR |
| `city` | VARCHAR |
| `timezone` | VARCHAR |
| `system_of_record` | VARCHAR |

### `core.fct_count`

Table, 23,541 rows. Cycle counts: the independent physical observations. Each row is repaired or excluded by explicit rules: X2 typo in the SKU           -> repaired when exactly one ERP item is a single edit away, else unresolved X5 date outside the sheet's month -> not used as an anchor (date cannot be trusted) X3 cases counted but entered as each -> detected by comparing with the book; quantity multiplied by the case size

| Column | Type |
|---|---|
| `count_key` | VARCHAR |
| `wh_code` | VARCHAR |
| `item_no` | VARCHAR |
| `sku_raw` | VARCHAR |
| `sku_resolution` | VARCHAR |
| `count_date` | DATE |
| `eod_date` | DATE |
| `date_in_sheet_month` | BOOLEAN |
| `counted_qty_raw` | DOUBLE |
| `book_before` | HUGEINT |
| `case_qty` | INTEGER |
| `counted_by` | VARCHAR |
| `uom_suspect` | BOOLEAN |
| `counted_qty` | DOUBLE |
| `is_anchor` | BOOLEAN |
| `excluded_reason` | VARCHAR |

### `core.fct_freight_charge`

Table, 63,888 rows. F7: a charge line repeated with the same code and amount on the same shipment is flagged as a suspected duplicate bill (recoverable).

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `shipment_key` | VARCHAR |
| `line_id` | VARCHAR |
| `charge_code` | VARCHAR |
| `amount` | DOUBLE |
| `is_suspect_duplicate` | BOOLEAN |

### `core.fct_order_line`

Table, 613,308 rows. Clean sales-order lines. Each ERP defect has an explicit rule; nothing is changed silently (see the flag columns). E1 successor item keyed as its predecessor -> remapped when the warehouse picked the successor for that order E2 re-keyed duplicates                     -> exact duplicates dropped (is_duplicate); 11-25 minute near-matches only flagged E3 zero/negative quantity                  -> excluded E4 ship-from warehouse null/invalid        -> filled from the customer's default warehouse, else from a sibling line E5 quantity in cases                       -> converted to units with the item master's case size; E5b (no case size) excluded E6 quantity changed after shipment         -> both

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `line_no` | INTEGER |
| `cust_acct` | VARCHAR |
| `item_no` | VARCHAR |
| `item_no_as_entered` | VARCHAR |
| `wh_code` | VARCHAR |
| `order_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `qty_ordered_units` | DOUBLE |
| `qty_ordered_units_original` | DOUBLE |
| `qty_shipped_units` | DOUBLE |
| `unit_price` | DOUBLE |
| `status` | VARCHAR |
| `last_ship_date` | DATE |
| `flag_item_remapped` | BOOLEAN |
| `flag_wh_filled` | BOOLEAN |
| `flag_uom_converted` | BOOLEAN |
| `flag_modified_after_entry` | BOOLEAN |
| `is_duplicate` | BOOLEAN |
| `flag_near_duplicate` | BOOLEAN |
| `exclude_reason` | VARCHAR |

### `core.fct_po_line`

Table, 73,858 rows.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `vendor_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `po_date` | DATE |
| `promised_date` | DATE |
| `header_received_date` | DATE |
| `qty_ordered` | DOUBLE |
| `unit_cost` | DOUBLE |
| `qty_received_erp` | DOUBLE |
| `received_date` | DATE |
| `status` | VARCHAR |

### `core.fct_shipment`

Table, 28,183 rows. One row per carrier shipment, matched to its order or PO. F4: an impossible delivery time is dropped (flagged), never trusted. F5: a missing weight is imputed from the matched document's item weights (flagged and sourced).

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `shipment_key` | VARCHAR |
| `ref_raw` | VARCHAR |
| `doc_no` | VARCHAR |
| `match_method` | VARCHAR |
| `match_status` | VARCHAR |
| `direction` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `pickup_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `delivered_ts_utc` | TIMESTAMP WITH TIME ZONE |
| `flag_delivery_time_invalid` | BOOLEAN |
| `weight_lb_reported` | DOUBLE |
| `weight_lb` | DOUBLE |
| `weight_source` | VARCHAR |
| `pieces` | INTEGER |
| `flag_pieces_missing` | BOOLEAN |

### `core.fct_stock_movement`

Table, 728,935 rows. The canonical stock ledger: every movement that changes (or that the systems claim changed) stock, by item and warehouse. Recorded movements come from the WMS and the legacy system; inferred movements fill gaps proven by cross-system evidence.

| Column | Type |
|---|---|
| `movement_id` | VARCHAR |
| `source_system` | VARCHAR |
| `wh_code` | VARCHAR |
| `item_no` | VARCHAR |
| `recorded_item_no` | VARCHAR |
| `local_date` | DATE |
| `ts_utc` | TIMESTAMP WITH TIME ZONE |
| `movement_type` | VARCHAR |
| `qty_delta` | INTEGER |
| `is_count_adjustment` | BOOLEAN |
| `ref_no` | VARCHAR |
| `is_inferred` | BOOLEAN |
| `inference_rule` | VARCHAR |
| `evidence_score` | DOUBLE |
| `quality_flag` | VARCHAR |

### `core.recon_legacy_vendor_ref`

Table, 429 rows. L4: legacy receipts whose vendor id is not in the legacy vendor master. The movement is valid; the vendor is repaired from the ERP PO.

| Column | Type |
|---|---|
| `trans_id` | VARCHAR |
| `po_no` | VARCHAR |
| `legacy_vendor_id` | VARCHAR |
| `vendor_from_po` | VARCHAR |
| `status` | VARCHAR |

### `core.recon_price_conflicts`

Table, 211 rows. Vendor price overrides typed twice with different prices for the same vendor, item and effective date (defect X6). Documented rule: the later entry is the price in force; the conflict goes to purchasing so someone confirms it.

| Column | Type |
|---|---|
| `row_key` | VARCHAR |
| `vendor_name` | VARCHAR |
| `item_no` | VARCHAR |
| `effective_date` | DATE |
| `override_cost` | DOUBLE |
| `entered_on` | TIMESTAMP |
| `entered_by` | VARCHAR |
| `n_prices` | BIGINT |
| `is_price_in_force` | BOOLEAN |

### `core.recon_receipt_variance`

Table, 635 rows. C1: the ERP receipt quantity disagrees with what the warehouse system recorded receiving. The warehouse is the physical record.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `received_date` | DATE |
| `qty_ordered` | DOUBLE |
| `qty_received_erp` | DOUBLE |
| `qty_received_warehouse` | HUGEINT |
| `variance` | DOUBLE |

### `core.recon_transfer_exceptions`

Table, 150 rows. C3: transfer-outs the receiving side never recorded. The destination is not in the out-event, so these stay as in-transit exceptions.

| Column | Type |
|---|---|
| `event_id` | VARCHAR |
| `ref_no` | VARCHAR |
| `from_wh` | VARCHAR |
| `out_date` | DATE |
| `item_no` | VARCHAR |
| `quantity` | INTEGER |
| `exception_type` | VARCHAR |

### `core.review_queue`

Table, 4,178 rows. Everything the pipeline would not decide on its own. Nothing here has been silently dropped or guessed. Each reason code is governed in ref.dq_reason_codes (severity, owner, suggested action).

| Column | Type |
|---|---|
| `source_system` | VARCHAR |
| `source_key` | VARCHAR |
| `reason_code` | VARCHAR |
| `detail` | VARCHAR |
| `defect_class` | VARCHAR |
| `severity` | VARCHAR |
| `disposition` | VARCHAR |
| `owner_role` | VARCHAR |
| `suggested_action` | VARCHAR |

### `core.xwalk_sku`

Table, 8,400 rows. Identifier crosswalk to the ERP item number. valid_from is when the mapping became usable; a legacy code can map to several items.

| Column | Type |
|---|---|
| `source_system` | VARCHAR |
| `source_key` | VARCHAR |
| `valid_from` | DATE |
| `item_no` | VARCHAR |
| `match_method` | VARCHAR |

### `core.xwalk_vendor`

Table, 147 rows. Legacy vendor ids -> ERP vendor. Exact name match for the original rows; duplicate legacy rows merge when address and phone agree (strong), and go to review when only the name is similar (weak).

| Column | Type |
|---|---|
| `legacy_vendor_id` | VARCHAR |
| `vendor_no` | VARCHAR |
| `match_method` | VARCHAR |
| `confidence` | DOUBLE |
| `status` | VARCHAR |


## Quarantine (`quarantine`)

Rows set aside with a reason code instead of being used or silently dropped.

### `quarantine.q_count_row`

Table, 273 rows.

| Column | Type |
|---|---|
| `count_key` | VARCHAR |
| `wh_code` | VARCHAR |
| `sku_raw` | VARCHAR |
| `count_date` | DATE |
| `counted_qty_raw` | DOUBLE |
| `reason_code` | VARCHAR |

### `quarantine.q_legacy_trans`

Table, 690 rows. Legacy rows kept out of the ledger, with the reason. They stay here (and in core.review_queue) until a person or a later rule resolves them.

| Column | Type |
|---|---|
| `trans_id` | VARCHAR |
| `legacy_code` | VARCHAR |
| `trans_type` | VARCHAR |
| `trans_date_raw` | VARCHAR |
| `qty_raw` | VARCHAR |
| `ref_no` | VARCHAR |
| `item_resolution` | VARCHAR |
| `candidate_items` | VARCHAR[] |
| `reason_code` | VARCHAR |


## Marts (`marts`)

The answers: stock by day, risk, inbound, freight, phantom-stock alerts. The dashboard reads only these (and the ops layer).

### `marts.mart_count_accuracy`

Table, 138 rows. How accurate the system book is, measured by the physical counts: per warehouse and month, the share of counted items where the book was exactly right, and the net and absolute variance in units and dollars at standard cost. Only counts usable as anchors are included (bad sheets are quarantined).

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `month` | TIMESTAMP |
| `items_counted` | BIGINT |
| `exact_rate` | DOUBLE |
| `net_variance_units` | DOUBLE |
| `net_variance_value` | DOUBLE |
| `abs_variance_value` | DOUBLE |
| `short_items` | BIGINT |
| `over_items` | BIGINT |

### `marts.mart_count_interval`

Table, 5 rows.

| Column | Type |
|---|---|
| `interval_band` | VARCHAR |
| `counts` | BIGINT |
| `book_exact_rate` | DOUBLE |
| `book_too_high_rate` | DOUBLE |

### `marts.mart_freight_lane`

Table, 301 rows. Lanes over the last 90 days: where the freight money goes, what it costs per 100 lb, and where shipments run slow.

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `lane` | VARCHAR |
| `direction` | VARCHAR |
| `shipments` | BIGINT |
| `cost` | DOUBLE |
| `weight_lb` | DOUBLE |
| `cost_per_100lb` | DOUBLE |
| `median_transit_days` | DOUBLE |
| `slow_shipments` | BIGINT |
| `timed_shipments` | BIGINT |

### `marts.mart_freight_shipment`

Table, 28,183 rows. One row per delivered-or-moving shipment with its cost (suspect duplicate charge lines excluded and shown separately), transit time and whether it was slow against the assumed service standard (seed ref.service_standards). Shipments with an impossible delivery time keep their cost but have no transit time.

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `shipment_key` | VARCHAR |
| `doc_no` | VARCHAR |
| `direction` | VARCHAR |
| `origin_city` | VARCHAR |
| `dest_city` | VARCHAR |
| `lane` | VARCHAR |
| `pickup_date` | DATE |
| `pickup_week` | TIMESTAMP |
| `weight_lb` | DOUBLE |
| `pieces` | INTEGER |
| `transit_days` | BIGINT |
| `is_slow` | BOOLEAN |
| `cost` | DOUBLE |
| `duplicate_cost` | DOUBLE |
| `order_units` | DOUBLE |

### `marts.mart_freight_weekly`

Table, 549 rows. Freight by week, carrier and direction: volume, cost, cost per 100 lb, cost per order and per unit shipped (outbound orders), slow rate, and recoverable duplicate charges.

| Column | Type |
|---|---|
| `carrier` | VARCHAR |
| `direction` | VARCHAR |
| `week` | TIMESTAMP |
| `shipments` | BIGINT |
| `weight_lb` | DOUBLE |
| `cost` | DOUBLE |
| `duplicate_cost` | DOUBLE |
| `cost_per_100lb` | DOUBLE |
| `order_shipments` | BIGINT |
| `cost_per_order` | DOUBLE |
| `cost_per_unit` | DOUBLE |
| `timed_shipments` | BIGINT |
| `slow_shipments` | BIGINT |

### `marts.mart_ghost_stock_daily`

Table, 4,380 rows. For every warehouse and every night: how many order lines were stuck that night (7 to 60 days old, not shipped, stock said to be on hand), and over how many SKUs. Lines open for more than 60 days are treated as dead (never closed in the ERP) and stop counting, so old leftovers do not pile up in the baseline. The alert threshold is learned per warehouse from the first 12 months of history, before any incident: twice that warehouse's busiest night (at least 5 lines), and the stuck lines must span at least 3 SKUs.

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `as_of` | DATE |
| `n_lines` | BIGINT |
| `n_skus` | BIGINT |
| `stuck_value` | DOUBLE |
| `threshold` | BIGINT |
| `is_alert` | BOOLEAN |

### `marts.mart_ghost_stock_episode`

Table, 1 rows. Phantom-stock episodes: runs of alert nights at one warehouse (gaps of up to 3 quiet nights are bridged). For each episode: alert_date            the night the alert fired; est_start             when the trouble most likely began. Among the SKUs with 3 or more stuck lines, each SKU's start is its first stuck line that is followed by another stuck line (isolated late orders are ordinary); the episode start is the third earliest of those, so one or two coincidences cannot move it; affected SKUs, stuck order lines and their value, and the value the book still claims for those SKUs on the alert date; first_confirming_count the date by which counts had found at least 5 of those SKUs far below the

| Column | Type |
|---|---|
| `wh_code` | VARCHAR |
| `wh_name` | VARCHAR |
| `alert_date` | DATE |
| `last_alert_date` | DATE |
| `est_start` | DATE |
| `affected_skus` | BIGINT |
| `stuck_order_lines` | BIGINT |
| `stuck_order_value` | DOUBLE |
| `book_value_at_risk` | DOUBLE |
| `first_confirming_count` | DATE |
| `alert_days_before_count` | BIGINT |

### `marts.mart_ghost_stock_line`

Table, 1,090 rows. Order lines the records say should have shipped at once but did not: the estimated stock on the order date covered the quantity, yet the line shipped more than 7 days later (or has not shipped). A few of these are ordinary delays; a cluster at one warehouse means the stock on the book is not really there.

| Column | Type |
|---|---|
| `order_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `order_date` | DATE |
| `last_ship_date` | DATE |
| `status` | VARCHAR |
| `qty_ordered_units` | DOUBLE |
| `qty_shipped_units` | DOUBLE |
| `unit_price` | DOUBLE |
| `line_value` | DOUBLE |
| `est_on_hand_at_order` | DOUBLE |
| `book_at_order` | HUGEINT |
| `days_open` | BIGINT |

### `marts.mart_inbound_open`

Table, 1,290 rows. Purchase-order lines still open at the end of history: what is coming, when it was promised, and how overdue it is.

| Column | Type |
|---|---|
| `po_no` | VARCHAR |
| `line_no` | INTEGER |
| `item_no` | VARCHAR |
| `description` | VARCHAR |
| `vendor_no` | VARCHAR |
| `vendor_name` | VARCHAR |
| `wh_code` | VARCHAR |
| `po_date` | DATE |
| `promised_date` | DATE |
| `qty_ordered` | DOUBLE |
| `unit_cost` | DOUBLE |
| `open_value` | DOUBLE |
| `days_overdue` | BIGINT |

### `marts.mart_manual_effort`

Table, 14 rows. MODELED estimate, not a measurement: how much manual reconciliation the pipeline replaces. Each handling count comes from the cleaned tables; minutes per item are assumptions in seed ref.manual_effort_assumptions (shown in the dashboard). Rows the pipeline could not settle (review queue) are the work that remains.

| Column | Type |
|---|---|
| `handling_key` | VARCHAR |
| `label` | VARCHAR |
| `minutes_per_item` | DOUBLE |
| `basis` | VARCHAR |
| `items` | BIGINT |
| `hours` | DOUBLE |
| `is_remaining_manual` | BOOLEAN |

### `marts.mart_stock_current`

Table, 12,708 rows. The answer to "what can I promise and what is about to run out" for the latest day: one row per SKU and warehouse.

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `description` | VARCHAR |
| `category` | VARCHAR |
| `wh_code` | VARCHAR |
| `as_of` | DATE |
| `est_on_hand` | DOUBLE |
| `confidence` | VARCHAR |
| `book_recorded_qty` | HUGEINT |
| `est_minus_recorded` | DOUBLE |
| `last_anchor_date` | DATE |
| `days_since_anchor` | BIGINT |
| `committed_units` | DOUBLE |
| `available_to_promise` | DOUBLE |
| `daily_rate` | DOUBLE |
| `days_of_cover` | DOUBLE |
| `inbound_14d_qty` | DOUBLE |
| `first_inbound_in_days` | BIGINT |
| `risk` | VARCHAR |
| `std_cost` | DOUBLE |
| `list_price` | DOUBLE |
| `transfer_from` | VARCHAR |
| `transfer_qty` | INTEGER |

### `marts.mart_stock_daily`

Table, 9,289,548 rows. Estimated physical stock by item, warehouse and day. book_recorded_qty  what the source systems recorded, exactly as recorded (no corrections, no inference): the baseline to beat. book_qty           the ledger after corrections and evidence-based inference, including the systems' own count adjustments. est_on_hand        physical estimate: opening balance + movements (excluding the systems' count adjustments, which re-state a count), re-anchored to the counted quantity on each valid count (counts observe the end of the previous day). flags              retro_variance: a later count showed this estimate was off; input_gap: a movement in the window could not be used; stream_stale: the warehous

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `local_date` | DATE |
| `book_recorded_qty` | HUGEINT |
| `book_qty` | HUGEINT |
| `est_on_hand` | DOUBLE |
| `last_anchor_date` | DATE |
| `days_since_anchor` | BIGINT |
| `flag_retro_variance` | BOOLEAN |
| `flag_input_gap` | BOOLEAN |
| `flag_negative_episode` | BOOLEAN |
| `flag_stream_stale` | BOOLEAN |
| `confidence` | VARCHAR |

### `marts.mart_stock_risk_daily`

Table, 1,906,200 rows. Per SKU-warehouse-day over the last 150 days: how much stock is estimated on hand, how fast it sells, how much is promised in, and whether it will run out. Demand is the average daily shipments of the previous 28 days; only reliable inbound counts (promised from today to 14 days out).

| Column | Type |
|---|---|
| `item_no` | VARCHAR |
| `wh_code` | VARCHAR |
| `d` | DATE |
| `est_on_hand` | DOUBLE |
| `confidence` | VARCHAR |
| `units_28d` | HUGEINT |
| `daily_rate` | DOUBLE |
| `inbound_14d_qty` | DOUBLE |
| `first_inbound_in_days` | BIGINT |
| `days_of_cover` | DOUBLE |
| `risk` | VARCHAR |

### `marts.mart_vendor_ontime`

Table, 140 rows. Vendor delivery performance over the last 180 days of receipts: on time means received on or before the promised date.

| Column | Type |
|---|---|
| `vendor_no` | VARCHAR |
| `vendor_name` | VARCHAR |
| `lines_received` | BIGINT |
| `on_time_rate` | DOUBLE |
| `avg_days_vs_promise` | DOUBLE |
| `value_received` | DOUBLE |


## Operations (`ops`)

Monitoring: alert log, nightly health, freshness, volume, duplicate files, format drift, weekly defect rates, layer reconciliation, recorded build and test results.

### `ops.alerts_unified`

Table, 13 rows. Every alert from every source in one log. A failed model test is dated to the simulated night of the build that failed and clears on the night the next build passes it. opened_as_of is the night it was raised; resolved_as_of is the night it cleared (null = still open).

| Column | Type |
|---|---|
| `alert_id` | BIGINT |
| `alert_type` | VARCHAR |
| `severity` | VARCHAR |
| `entity` | VARCHAR |
| `alert_code` | VARCHAR |
| `opened_as_of` | DATE |
| `resolved_as_of` | DATE |
| `message` | VARCHAR |

### `ops.dbt_invocation`

Table, 11 rows.

| Column | Type |
|---|---|
| `invocation_id` | VARCHAR |
| `command` | VARCHAR |
| `generated_at` | TIMESTAMP |
| `elapsed_s` | DOUBLE |
| `n_pass` | INTEGER |
| `n_fail` | INTEGER |
| `n_error` | INTEGER |
| `n_skip` | INTEGER |
| `n_warn` | INTEGER |
| `as_of` | DATE |

### `ops.dbt_test_result`

Table, 691 rows.

| Column | Type |
|---|---|
| `invocation_id` | VARCHAR |
| `unique_id` | VARCHAR |
| `name` | VARCHAR |
| `status` | VARCHAR |
| `failures` | BIGINT |
| `execution_time` | DOUBLE |
| `generated_at` | TIMESTAMP |
| `message` | VARCHAR |

### `ops.dq_check_catalog`

Table, 9 rows. Documentation of every automated check: what it watches, how it decides, and what it raises.

| Column | Type |
|---|---|
| `check_name` | VARCHAR |
| `scope` | VARCHAR |
| `rule` | VARCHAR |
| `raises` | VARCHAR |
| `implemented_in` | VARCHAR |

### `ops.dq_metric_weekly`

Table, 2,606 rows. Data-quality rates by week, one series per defect family. Control limits: the median of the previous 12 weeks (robust to one bad week) +/- 5 binomial sigma. A steady background rate is normal and stays quiet; a jump or collapse is what raises an alert. Rules of the road: * a rate is judged only after 12 prior weeks of meaningful volume (at least 100 rows each) exist (burn-in); * only settled weeks (older than 14 days) are judged, because late events and later ERP corrections are still arriving for newer ones; * rates driven by the business calendar (items being superseded, new items launched) and the stock-quality shares are shown but not charted.

| Column | Type |
|---|---|
| `metric` | VARCHAR |
| `week` | DATE |
| `num` | HUGEINT |
| `den` | HUGEINT |
| `rate` | DOUBLE |
| `p0` | DOUBLE |
| `z` | DOUBLE |
| `is_settled` | BOOLEAN |
| `is_out_of_control` | BOOLEAN |

### `ops.duplicate_file_daily`

Table, 3 rows. A different file name carrying exactly the same bytes as an earlier file: the carrier re-sent a file.

| Column | Type |
|---|---|
| `stream` | VARCHAR |
| `rel_path` | VARCHAR |
| `arrival` | DATE |
| `as_of` | DATE |
| `rows_loaded` | BIGINT |
| `duplicate_of` | VARCHAR |

### `ops.format_drift_daily`

Table, 4,194 rows. Value-format monitors: the shape of a column (not its schema) changing under our feet. For each entity the dominant pattern of the last 3 days is compared with the dominant pattern of the 28 days before; a clean switch is drift.

| Column | Type |
|---|---|
| `monitor` | VARCHAR |
| `entity` | VARCHAR |
| `as_of` | DATE |
| `recent_pattern` | VARCHAR |
| `share_recent` | DOUBLE |
| `prior_pattern` | VARCHAR |
| `share_prior` | DOUBLE |
| `is_drift` | BOOLEAN |

### `ops.freshness_daily`

Table, 11,697 rows. For every stream and every night: how old is the newest data that had been loaded by then, against what the stream's owner promises. A file that arrived but was held (schema drift) does not count as fresh until it is released.

| Column | Type |
|---|---|
| `stream` | VARCHAR |
| `as_of` | DATE |
| `last_arrival` | DATE |
| `days_since_last_arrival` | BIGINT |
| `max_expected_gap_days` | INTEGER |
| `critical` | BOOLEAN |
| `is_late` | BOOLEAN |

### `ops.layer_reconciliation`

Table, 9 rows. Nothing may disappear between layers without a recorded reason. Each row compares what went in with what came out plus what was set aside.

| Column | Type |
|---|---|
| `check_name` | VARCHAR |
| `left_count` | BIGINT |
| `right_count` | HUGEINT |
| `diff` | HUGEINT |
| `ok` | BOOLEAN |

### `ops.ops_file_arrival`

Table, 9,057 rows. Every loaded file as an arrival of its stream. loaded_as_of is the nightly run that made it available.

| Column | Type |
|---|---|
| `file_id` | BIGINT |
| `rel_path` | VARCHAR |
| `table_name` | VARCHAR |
| `stream` | VARCHAR |
| `arrival` | DATE |
| `loaded_ts` | TIMESTAMP |
| `loaded_as_of` | DATE |
| `rows_loaded` | BIGINT |
| `sha256` | VARCHAR |
| `status` | VARCHAR |

### `ops.pipeline_health_current`

Table, 1 rows. The latest night, with every alert that is still open.

| Column | Type |
|---|---|
| `as_of` | DATE |
| `health` | VARCHAR |
| `run_status` | VARCHAR |
| `open_errors` | BIGINT |
| `open_warnings` | BIGINT |
| `alert_type` | VARCHAR |
| `severity` | VARCHAR |
| `entity` | VARCHAR |
| `opened_as_of` | DATE |
| `message` | VARCHAR |

### `ops.pipeline_health_daily`

Table, 730 rows. One row per night: did the run work, and is anything wrong anywhere? Red = an error-level alert is open; amber = warnings only; green = clean.

| Column | Type |
|---|---|
| `as_of` | DATE |
| `run_status` | VARCHAR |
| `files_loaded` | INTEGER |
| `files_held` | INTEGER |
| `files_failed` | INTEGER |
| `files_released` | INTEGER |
| `rows_loaded` | BIGINT |
| `duration_s` | DOUBLE |
| `open_errors` | BIGINT |
| `open_warnings` | BIGINT |
| `open_info` | BIGINT |
| `health` | VARCHAR |
| `issues` | VARCHAR |

### `ops.volume_daily`

Table, 8,939 rows. Rows arriving per stream per day against the median of the same weekday over the previous 8 weeks. A quiet spell around a public holiday (the day before to three days after) is expected and is not flagged; a surge never is.

| Column | Type |
|---|---|
| `stream` | VARCHAR |
| `arrival` | DATE |
| `as_of` | DATE |
| `n_rows` | HUGEINT |
| `n_files` | BIGINT |
| `baseline` | DOUBLE |
| `n_baseline` | BIGINT |
| `ratio` | DOUBLE |
| `is_anomaly` | BOOLEAN |


## Reference seeds (`ref`)

Small tables under version control: reason codes and their owners, monitored feeds, holidays, service standards, effort assumptions.

### `ref.closure_days`

Table, 35 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `closure_date` | DATE |
| `name` | VARCHAR |

### `ref.dq_reason_codes`

Table, 14 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `reason_code` | VARCHAR |
| `defect_class` | VARCHAR |
| `severity` | VARCHAR |
| `disposition` | VARCHAR |
| `owner_role` | VARCHAR |
| `suggested_action` | VARCHAR |

### `ref.legacy_category_codes`

Table, 12 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `category` | VARCHAR |
| `code` | VARCHAR |

### `ref.manual_effort_assumptions`

Table, 14 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `handling_key` | VARCHAR |
| `label` | VARCHAR |
| `minutes_per_item` | DOUBLE |
| `basis` | VARCHAR |

### `ref.monitor_streams`

Table, 16 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `stream` | VARCHAR |
| `max_expected_gap_days` | INTEGER |
| `critical` | BOOLEAN |
| `owner` | VARCHAR |
| `description` | VARCHAR |

### `ref.service_standards`

Table, 2 rows. Reference table loaded from a CSV seed under version control.

| Column | Type |
|---|---|
| `direction` | VARCHAR |
| `max_transit_days` | INTEGER |
| `basis` | VARCHAR |
