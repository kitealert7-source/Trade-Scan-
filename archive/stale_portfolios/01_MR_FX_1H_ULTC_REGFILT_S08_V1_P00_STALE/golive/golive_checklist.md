# Go-Live Checklist

- Generated UTC: `2026-03-11T13:32:05Z`
- Selected profile: `FIXED_USD_V1`
- Symbol count: `6`

## Artifact Integrity

- [ ] `run_manifest.json` exists and `directive_sha256` matches approved directive.
- [ ] `selected_profile.json` `profile_hash` verified at engine startup.
- [ ] `symbols_manifest.json` equals approved execution universe.
- [ ] `enriched_trade_log.csv` has `stage1_join_status=OK` for all rows.
- [ ] `broker_specs_snapshot/` exists with one YAML per symbol.
- [ ] `conversion_data_manifest.json` exists and pair_count is expected.

## Operational Readiness

- [ ] Broker account configuration matches `broker_specs_snapshot` constraints.
- [ ] Signal guard enabled (`signal_hash` verification).
- [ ] Kill-switch thresholds reviewed and accepted.
- [ ] Monitoring/alert channel tested.
- [ ] Dry-run startup completed without warnings.

## Sign-off

- [ ] Research sign-off
- [ ] Risk sign-off
- [ ] Operations sign-off
