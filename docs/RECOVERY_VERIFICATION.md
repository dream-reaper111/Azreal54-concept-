# Recovery verification

Checks were run from `AZRAEL_HOME=$HOME/azrael54`. No service, listener, browser,
model worker, training process, container command, systemd command, package installer
or network request was started. Verification scratch and compiled files were kept
inside `${AZRAEL_HOME}/recovery/verification`.

| Check | Result |
|---|---|
| Python compilation, including extensionless azraelctl and recovery helpers | 77/77 PASS |
| Safe parse of recovered Compose YAML files | 4/4 PASS |
| Explicit offline fixture tests | 44 PASS, 1 assertion failure, 2 errors; 47 run |
| Attempted subprocess/network/outside-tree writes during bounded checks | 0 |
| AZRAEL artwork against original files and registry hashes | 21/21 match |

The three unsuccessful tests are all in test_ctf_lab.py:

- test_pinned_offline_catalog_hides_answers_and_keeps_progress_separate:
  initialization is unavailable because ctf_assets/catalog.json is missing.
- test_attempt_validation_and_unknown_challenge_fail_closed: the unavailable
  catalog raises RuntimeError before the expected challenge-validation path.
- test_invalid_existing_ctf_store_is_preserved_and_not_reseeded: no organizer
  answer-key file was seeded because the source bundle is missing.

These failures were anticipated from the documented missing CTF assets. They were
reported without creating substitute challenges, altering tests, or changing source.

## Executed scope

Complete modules: test_evidence_store, test_collection, test_council,
test_storage_paths, test_idle_trainer, test_ctf_lab, test_hak5_catalog, and
test_role_research. Four test_source_transport methods checked exact URL policy,
credential-free worker environments through mocks, output bounds, and redirects.

Tests used explicitly labeled fixtures and fake generators/trainers; they establish
local contracts, not live collection, actual training, inference quality, operational
telemetry, GPU access, or service health. Temporary SQLite/test records were not
substituted for lost historical artifacts.

## Not run

- Socket/listener tests and real source-fetch subprocess tests.
- Installer/azraelctl lifecycle suites with provider/setup side effects and
  unresolved source contracts; no lifecycle command was invoked.
- Broader admin/HTTP/commands/roster/research suites needing optional dependencies;
  defusedxml and transformers are absent from the available interpreter.
- PoC training, real SLM inference, runtime security-tool execution, GPU tests,
  coordinator child-process cancellation, deployment and browser tests.
- No dependency was installed to work around a missing package.

Syntax success does not resolve setup_lab.py or azraelctl's missing runtime
interfaces, compose.yaml's source conflict, historical verification-report gaps,
or the original dashboard/network failure.

## Evidence

- recovery/verification/checks.json — per-file syntax/parse results and test failures.
- recovery/verification/unittest.log — retained offline test output.
- recovery/artwork-validation.json — per-image source/recovered hash comparison.
- recovery_verify.py — explicit check selection and write/process/network guards.

Future specification implementations must be independently approved and separately
tested; none was implemented during this review.
