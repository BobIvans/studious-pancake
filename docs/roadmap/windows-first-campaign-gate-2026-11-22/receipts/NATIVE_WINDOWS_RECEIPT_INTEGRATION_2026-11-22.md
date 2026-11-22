# Native Windows verification receipt (pre-merge integration validation)

- **Commit:** `7d3c693d60cac3e5da37a00b60a6a25807e565bd` (branch `integration/windows-receipt-2026-11-22` = main `0a0c8ad9` + merges of #691/#692/#693/#694/#695/#696/#697)
- **Generated:** 2026-11-22T12:04:23.382911+00:00
- **Scope:** pre-merge validation only (PR-8 #698, NOT FOR MERGE); the authoritative receipt is re-produced on post-merge main.

## OS / toolchain inventory (actual machine, Get-CimInstance)

```
Caption        : �������� Windows 11 Pro
Version        : 10.0.26300
BuildNumber    : 26300
OSArchitecture : 64-ࠧ�來��






Name  : PSVersion
Value : 5.1.26100.9818

Name  : PSEdition
Value : Desktop

Name  : PSCompatibleVersions
Value : {1.0, 2.0, 3.0, 4.0...}

Name  : BuildVersion
Value : 10.0.26100.9818

Name  : CLRVersion
Value : 4.0.30319.42000

Name  : WSManStackVersion
Value : 3.0

Name  : PSRemotingProtocolVersion
Value : 2.3

Name  : SerializationVersion
Value : 1.1.0.1




Python 3.13.15
arch_bits 64
uv: not on PATH
git version 2.55.0.windows.3
true
7d3c693d60cac3e5da37a00b60a6a25807e565bd
```

## Stage receipts

| Stage | Exit code |
|---|---|
| `powershell_inventory` | 0 |
| `toolchain_inventory` | 0 |
| `pip_check` | 0 |
| `compileall` | 0 |
| `verify_repo_skip_dependency_audit` | 1 |
| `pytest_full_offline` | 1 |

## Stage evidence

### pip_check (`pip_check.log`)

```
No broken requirements found.
```

### compileall (`compileall.log`)

```

```

### verify_repo (tail) (`verify_repo.log`)

```
            assert reference is not None
            reference.resolve(environ={})
    
        multiline = _write(tmp_path / "multiline.secret", "secret\nextra\n", mode=0o600)
>       with pytest.raises(SecretResolutionError, match="exactly one line"):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: Regex pattern did not match.
E         Expected regex: 'exactly one line'
E         Actual message: 'file secret grants group/other permissions'

tests\test_pr120_secret_resolver_config_jito.py:66: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_pr120_secret_resolver_config_jito.py::test_secret_resolver_handles_env_and_restrictive_file_without_repr_leak
FAILED tests/test_pr120_secret_resolver_config_jito.py::test_file_secret_reference_rejects_symlink_multiline_and_loose_permissions
======================= 2 failed, 199 passed in 27.37s ========================
```

### pytest_full summary (`pytest_full.log`)

```
FAILED tests/test_super06_research_frontier_closure.py::test_super06_closure_verifier_accepts_current_canonical_owners
FAILED tests/test_super06_research_frontier_closure.py::test_super06_pins_checked_out_canonical_source_blobs
FAILED tests/test_ton_radar_wave2.py::test_wave2_bundle_files_and_hashes_are_intact
==== 43 failed, 6217 passed, 9 skipped, 1 deselected in 546.92s (0:09:06) =====
```


## Full offline pytest classification (this commit, this machine)

`==== 43 failed, 6217 passed, 9 skipped, 1 deselected in 546.92s (0:09:06) =====`

Raw logs are retained with the receipt bundle; SHA-256 of each stage log:

- `os_inventory.txt`: `e8c5ce107ddfd50ae36797e42a63244c6f8c952b0cddd9bc8430e5692cb61470`
- `pip_check.log`: `672aec65a45bed50e70229c70934a7eebf0462595c459b83023027645d57cccf`
- `compileall.log`: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `verify_repo.log`: `f8044e2b52da9e389fe88cbbee16f6e81c58ee554b50e19ce34c054aba377eb9`
- `pytest_full.log`: `1cabc0cf6110a00674c42f698790cd215b8b484bb16e5107bd839773c2677bd0`

## Remaining-failure classification (fresh, this exact SHA — no carried-over counts)

Full standalone offline suite: **43 failed / 6217 passed / 9 skipped / 1 deselected;
0 pytest-socket errors** (the #670 baseline's 327 fixture errors and uvloop/OCC
defects are gone).  Every failure is pre-existing Windows-platform debt, none in
the #679 lanes' new tests.  Clusters (exact IDs in `failed_tests.txt`):

| Cluster | Count | Root cause (reproduced) | Owner/task |
|---|---|---|---|
| tests/deployment/test_pr008_supply_chain.py, tests/durability/test_pr003_storage_security.py, test_pr041 backup drill, test_pr178 artifact registry, test_pr184 tamper-evident audit | ~14 | POSIX file-permission/mode-bit semantics (0o600/owner-only) are not reproducible via Windows chmod/ACL; symlink/type checks diverge on NTFS | R11-documented Windows debt → GPR-01a (owner: platform/durability lane) |
| test_pr170_management_plane, test_pr06_management_audit_anchor, test_o1_management_evidence_pipeline | ~9 | management-plane evidence pipelines depend on POSIX file semantics/pagination | GPR-01a (owner: management lane) |
| test_pr025_container_runtime, test_pr190_canonical_config, test_pr120_secret_resolver, test_pr183/196/205/… | ~14 | config/secret/container platforms diverge on Windows path/permission/validation ordering (e.g. test_pr120: file-permission check fires before the 'exactly one line' check on Windows) | GPR-01a (owners per module) |
| test_ton_radar_wave2, test_r02_cap_c_offline_replay, test_super06 frontier closure | ~4 | pydantic/OpenAPI fixture byte-format (CRLF in committed OpenAPI JSON) + replay drift | GPR-01a (owner: ton/r02 lane) |
| verify_repo FOCUSED pytest stage | 2 | test_pr120 mode-bit ordering (see above) — pre-existing on native Windows, Linux CI green | WIN-04b (backlog on #679) |

## verify_repo stage detail (this SHA)

- pip check: 0; compileall: 0; quality_gate (black/flake8/mypy/bandit): pass;
  validate_authority_map: pass; **package_smoke: PASS on native Windows**
  (fixed on this branch: wheel-probe AF_UNIX sentinel + stdlib self-pipe
  connect exemption — fail-closed contract unchanged); 27 pinned verifiers:
  pass up to the fail-fast point; focused pytest: exit 1 with the 2
  pre-existing test_pr120 failures above.  verify_repo exit code 1 is the
  honest terminal state on native Windows until WIN-04b lands; Linux CI
  (PR-8 #698) is fully green.

## Zero-network assertion

No campaign capture, RPC collection, quote API call, provider activation or
credential use was performed. The only network activity in this run is
dependency resolution and local loopback test fixtures already covered by the
offline suite. CS-06 remains CS06_PENDING_CAPTURE; no qualification PASS is
claimed.


## Exact failed test IDs

```
FAILED tests/deployment/test_pr008_supply_chain.py::test_locks_include_resolved_transitive_dependencies
FAILED tests/durability/test_pr003_storage_security.py::test_database_permissions_pragmas_and_fingerprint
FAILED tests/durability/test_pr003_storage_security.py::test_symlink_database_path_is_rejected
FAILED tests/durability/test_pr003_storage_security.py::test_symlink_parent_component_is_rejected
FAILED tests/durability/test_pr003_storage_security.py::test_existing_database_in_writable_parent_is_rejected
FAILED tests/durability/test_pr003_storage_security.py::test_sqlite_sidecars_are_owner_only
FAILED tests/durability/test_pr003_storage_security.py::test_restore_validates_staged_copy_without_destroying_destination
FAILED tests/durability/test_pr041_durable_lifecycle.py::test_backup_restore_drill_and_checksum
FAILED tests/runtime/test_mpr_rp03_instance_resources.py::test_cleanup_refuses_to_delete_replaced_generation_lock
FAILED tests/security/test_mpr_td_04_security.py::test_owned_path_and_atomic_write_reject_traversal_and_symlink
FAILED tests/test_decision_calibration.py::test_report_contains_metrics - Val...
FAILED tests/test_decision_model.py::test_train_artifact_safe_and_prediction_explainable
FAILED tests/test_mpr_close_23_hermetic_runtime.py::test_verify_plan_uses_canonical_installed_entrypoint
FAILED tests/test_o1_management_evidence_pipeline.py::test_o1_management_protects_ready_and_consumes_signed_state
FAILED tests/test_o1_management_evidence_pipeline.py::test_o1_tampered_or_stale_state_cannot_affect_readiness
FAILED tests/test_o1_management_evidence_pipeline.py::test_o1_ed25519_manifest_verifies_and_detects_materialized_drift
FAILED tests/test_pr025_container_runtime.py::test_safe_idle_container_supervisor_has_live_process_heartbeat
FAILED tests/test_pr025_container_runtime.py::test_container_port_collision_leaves_no_healthy_state
FAILED tests/test_pr025_container_runtime.py::test_healthcheck_rejects_missing_stale_dead_and_wrong_mode
FAILED tests/test_pr025_packaging.py::test_optional_lock_profiles_are_explicit_and_hashed
FAILED tests/test_pr06_management_audit_anchor.py::test_signed_checkpoint_anchor_and_independent_verification
FAILED tests/test_pr06_management_audit_anchor.py::test_snapshot_mutation_invalidates_checkpoint
FAILED tests/test_pr06_management_audit_anchor.py::test_anchor_receipt_is_create_only
FAILED tests/test_pr120_secret_resolver_config_jito.py::test_secret_resolver_handles_env_and_restrictive_file_without_repr_leak
FAILED tests/test_pr120_secret_resolver_config_jito.py::test_file_secret_reference_rejects_symlink_multiline_and_loose_permissions
FAILED tests/test_pr132_observability_integrity.py::test_pr132_export_uses_real_date_type_and_full_envelope
FAILED tests/test_pr170_management_plane.py::test_pr170_signed_state_snapshot_is_owner_only_and_verified
FAILED tests/test_pr170_management_plane.py::test_pr170_state_tamper_fails_closed
FAILED tests/test_pr170_management_plane.py::test_pr170_stale_generation_and_policy_mismatch_are_rejected
FAILED tests/test_pr178_artifact_registry.py::test_latest_pointer_rejects_absolute_path_escape
FAILED tests/test_pr178_artifact_registry.py::test_pointer_checksum_is_enforced
FAILED tests/test_pr178_artifact_registry.py::test_non_finite_json_artifact_is_rejected_before_checksum_trust
FAILED tests/test_pr178_artifact_registry.py::test_feature_and_coefficient_count_must_match
FAILED tests/test_pr183_credential_trust_lifecycle.py::test_file_secret_path_swap_reads_original_descriptor
FAILED tests/test_pr184_tamper_evident_audit.py::test_store_creates_restrictive_database_and_valid_chain
FAILED tests/test_pr190_canonical_config.py::test_runtime_identity_is_domain_separated_and_display_is_redacted
FAILED tests/test_pr190_canonical_config.py::test_signed_activation_is_atomic_and_compare_and_swap_bound
FAILED tests/test_pr196_durable_runtime_kernel.py::test_backup_restore_preserves_attempt_and_outbox_hashes
FAILED tests/test_pr205_asymmetric_qualification.py::test_secure_artifact_reader_rejects_traversal_symlink_and_hardlink
FAILED tests/test_r02_cap_c_offline_replay.py::test_vendor_blob_hashes_match_pinned_manifest
FAILED tests/test_super06_research_frontier_closure.py::test_super06_closure_verifier_accepts_current_canonical_owners
FAILED tests/test_super06_research_frontier_closure.py::test_super06_pins_checked_out_canonical_source_blobs
FAILED tests/test_ton_radar_wave2.py::test_wave2_bundle_files_and_hashes_are_intact
```
