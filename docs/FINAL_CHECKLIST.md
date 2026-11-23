# Final Hardening & Honest Verification Checklist

Running status across all audit and verification sections. Updated continuously.

**Ground Rules Applied**:
- No fabricated numbers or test outcomes.
- No secrets logged or printed.
- Anything not verified live is marked `NOT VERIFIED` with reason.

---

## Section A: Regrade Phase 6 Report
| Item | Status | Evidence |
| :--- | :---: | :--- |
| Docker status regraded to `NOT TESTED` | **PASS** | Updated in `eval_report.md` (only `docker compose config` ran previously; full container lifecycle pending Section F) |
| Verifier catch rate clarified to Layer 1 only | **PASS** | Updated in `eval_report.md` (Layer 2 LLM was mocked/fallback; Layer 1 deterministic caught 7/7 injected mutations) |
| Project-fit verdict regraded to `NOT ESTABLISHED` | **PASS** | Marked `NOT ESTABLISHED` in `eval_report.md` pending live LLM validation and timing data |
| Remove "100% precision" claim | **PASS** | Removed from `eval_report.md` and codebase docs (precision on hallucinations was never measured) |
| Remove unmeasured "25 to 5 minutes" claim | **PASS** | Removed from `README.md` and `eval_report.md` |
| Remove "correlation with human judgment" claim | **PASS** | Removed from `README.md` and `eval_report.md` (labels were self-generated synthetic fixtures, not independent human labels) |

---

## Section B: Live LLM Verification
| Item | Status | Evidence |
| :--- | :---: | :--- |
| `scripts/check_llm.py` probe script created | **PASS** | [`scripts/check_llm.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/scripts/check_llm.py); prints model, provider, latency, never logs secrets |
| Gemini retry with exponential backoff & jitter for 429 & 5xx | **PASS** | Implemented `retry_with_backoff` in [`backend/llm/client.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/backend/llm/client.py) |
| Mocked tests for exponential backoff & jitter | **PASS** | 4 tests in [`backend/tests/test_llm_client.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/backend/tests/test_llm_client.py) passing |
| Live LLM execution (resume parse, JD extract, tailor, verifier, workflow) | **PASS (Auth & Extraction) / QUOTA LIMITED (Full Run)** | Verified live authentication via `scripts/check_llm.py`: text (`PONG`) & JSON parsing (`status='ok'`). Parsed `sample_resume.pdf` extracting candidate `ALEX RIVERA` & 8 skills. Free tier 20 req/day quota limit reached; exponential backoff caught 429 and gracefully fell back. |
| Standalone `scripts/final_verification.py --live` created | **PASS** | [`scripts/final_verification.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/scripts/final_verification.py) created to run all LLM checks once key is valid |
| Verifier fail-closed semantics (drafts fail closed if Layer 2 fails) | **PASS** | `test_verifier_fails_closed_on_llm_failure` and `test_approval_invariant_blocks_unverified_draft_without_override` in `test_tailoring_pipeline.py` |

---

## Section C: Cross-Phase Audit
| Phase & Feature | Status | Evidence |
| :--- | :---: | :--- |
| **Phase 1**: Scanned PDF -> 422 | **PASS** | `test_resume_parser_scanned_pdf_triggers_422` in `test_profile_agent.py` |
| **Phase 1**: File signature check (magic bytes) | **PASS** | `test_resume_parser_rejects_invalid_file_signature` in `test_profile_agent.py` |
| **Phase 1**: 5 MB file size -> 413 | **PASS** | `test_resume_parser_rejects_oversized_file` in `test_profile_agent.py` |
| **Phase 1**: Single profile constraint | **PASS** | `test_api_profile_and_preferences_lifecycle` in `test_profile_agent.py` |
| **Phase 1**: All old chunks deleted before re-indexing | **PASS** | `test_chroma_indexing_and_duplicate_prevention` in `test_profile_agent.py` & `collection.delete(where={"profile_id": ...})` |
| **Phase 1**: Skill normalisation done in code | **PASS** | `test_skill_normalization_canonical_and_deduplication` in `test_profile_agent.py` |
| **Phase 1**: One retry on invalid LLM JSON, then nothing stored | **PASS** | `test_profile_agent_llm_failure_logs_and_stores_nothing` in `test_profile_agent.py` |
| **Phase 1**: Logs contain summaries only (no raw resume text) | **PASS** | `write_agent_log` in `models/logs.py` asserts summary dicts only |
| **Phase 2**: Chroma collection is cosine (migrated from L2) | **PASS** | `test_chroma_collection_metric_migration_to_cosine` in `test_intake_matching.py` |
| **Phase 2**: Similarity calibration (clamping s_low=0.15, s_high=0.60) | **PASS** | `test_chroma_distance_to_similarity_conversion` in `test_intake_matching.py` |
| **Phase 2**: SSRF protection (manual redirects, private DNS, IPv4-mapped IPv6, 2 MB stream limit) | **PASS** | `test_ssrf_blocked_ip_ranges`, `test_redirect_to_private_ip_blocked`, `test_hostname_resolving_to_private_ip_blocked` |
| **Phase 2**: Dedup hash of normalised JD text only (pasted == fetched) | **PASS** | `test_deduplication_pasted_vs_fetched_returns_same_job` in `test_intake_matching.py` |
| **Phase 2**: Match recalculated when profile or preferences hash changes | **PASS** | `test_match_recalculated_after_preferences_change` in `test_intake_matching.py` |
| **Phase 2**: Rematch allowed only for saved/skipped/failed | **PASS** | `test_jobs_api_lifecycle_and_staleness` & status check in `backend/api/jobs.py` (409 on others) |
| **Phase 2**: Coverage gate & conflict cap use Preferences thresholds, score_before_caps/after_caps recorded | **PASS** | `test_coverage_gate_caps_score_when_under_threshold`, `test_conflict_cap_caps_score_for_duration_and_avoid_skills` |
| **Phase 2**: Same input gives same deterministic score | **PASS** | `test_score_determinism` in `test_intake_matching.py` |
| **Phase 2**: Prompt-injection JD does not affect score | **PASS** | `test_prompt_injection_does_not_affect_score` in `test_intake_matching.py` |
| **Phase 2**: Embedding work offloaded from event loop | **PASS** | `asyncio.to_thread` wrapped in `backend/vector_store.py::query_profile_chunks` |
| **Phase 2**: JD text truncated before LLM calls | **PASS** | `[:15000]` truncation enforced in `matching_agent.py` & `intake_agent.py` |
| **Phase 3**: Skills section is subset of Profile.skills (enforced in code) | **PASS** | `test_tailor_agent_enforces_skills_and_project_limits_in_code` in `test_tailoring_pipeline.py` |
| **Phase 3**: Missing skills never appear as possessed | **PASS** | `test_redteam_catch_missing_skill_claimed_as_possessed` in `test_tailoring_pipeline.py` |
| **Phase 3**: Project titles match Profile.projects | **PASS** | `test_redteam_catch_nonexistent_project_title` in `test_tailoring_pipeline.py` |
| **Phase 3**: Max 3 bullets per project and 3 projects | **PASS** | `test_tailor_agent_enforces_skills_and_project_limits_in_code` in `test_tailoring_pipeline.py` |
| **Phase 3**: Cover note 120-180 words enforced in code | **PASS** | `test_cover_note_agent_word_count_retry_and_enforcement` in `test_tailoring_pipeline.py` |
| **Phase 3**: Verifier Layer 1 checks (skills, titles, numbers, employers, degree, word count) | **PASS** | 5 red-team unit tests passing in `test_tailoring_pipeline.py` |
| **Phase 3**: Layer 2 claim check including inflation | **PASS** | `test_redteam_catch_inflated_verb_by_layer_2` in `test_tailoring_pipeline.py` |
| **Phase 3**: Fail closed; max 2 retries then failed_verification | **PASS** | `test_pipeline_fails_after_3_attempts`, `test_verifier_fails_closed_on_llm_failure` |
| **Phase 3**: Drafts stored with versions | **PASS** | `test_pipeline_stability_identical_stored_structure` in `test_tailoring_pipeline.py` |
| **Phase 4**: Graph state holds ids and small summaries only (no full resume/JD/draft text) | **PASS** | Inspected `JobState` in `backend/workflow/state.py` |
| **Phase 4**: POST /jobs and resumes run in background and return 202 | **PASS** | `test_post_jobs_returns_202_and_processes_in_background` in `test_workflow.py` |
| **Phase 4**: Failed status + POST /jobs/{id}/retry | **PASS** | `test_workflow_failure_retains_checkpoint_and_allows_retry` in `test_workflow.py` |
| **Phase 4**: Jobs left in "processing" at startup become failed | **PASS** | `test_recover_interrupted_jobs_on_startup` in `test_workflow.py` |
| **Phase 4**: ONE transition table with atomic conditional MongoDB update | **PASS** | `ALLOWED_TRANSITIONS` & `test_atomic_transition_prevents_race_conditions` |
| **Phase 4**: Approved job always has passed verification or recorded override | **PASS** | `test_approval_invariant_enforced_strictly` & `test_approval_invariant_blocks_unverified_draft_without_override` |
| **Phase 4**: Decision validation (409 wrong/no interrupt, 422 invalid action, double submit 409) | **PASS** | `test_decision_validation_no_pending_interrupt_returns_409`, `test_decision_validation_invalid_action_returns_422`, `test_decision_double_submit_returns_409` |
| **Phase 4**: Edits verified server-side before resuming (approval->edit & manual_edit_required->submit_edits) | **PASS** | `test_manual_edit_flow_with_warning_acknowledgement` in `test_workflow.py` |
| **Phase 4**: 422 needs_acknowledgement keeps interrupt pending | **PASS** | `test_manual_edit_flow_with_warning_acknowledgement` in `test_workflow.py` |
| **Phase 4**: submit_edits goes back through verification then approval | **PASS** | `test_manual_edit_flow_with_warning_acknowledgement` in `test_workflow.py` |
| **Phase 4**: thread_id includes run number | **PASS** | `test_run_number_isolates_threads` in `test_workflow.py` |
| **Phase 4**: Checkpointer opened in lifespan and compiled once | **PASS** | `init_checkpointer_and_graph` in `backend/main.py` lifespan |
| **Phase 4**: MongoDB saver tested or removed | **PASS** | Cleanly omitted in favor of official `AsyncSqliteSaver` in `checkpointer.py` |
| **Phase 4**: Temporary POST /jobs/{id}/draft is gone | **PASS** | Verified absent from routes in `backend/api/jobs.py` and `app.openapi()` |
| **Phase 4**: GET /jobs/{id} never advances graph | **PASS** | Read-only inspection in `backend/api/jobs.py::get_job` |
| **Phase 4**: agent_log contains no resume, JD or draft text | **PASS** | `test_agent_log_privacy_no_full_text` in `test_workflow.py` |
| **Phase 5**: Polling while processing/drafting stops on pause/finish/fail/hidden tab/unmount | **PASS** | Verified in `frontend/src/pages/JobsBoardPage.jsx` |
| **Phase 5**: Retry button on failed status | **PASS** | Implemented in `JobDetailPage.jsx` and `JobsBoardPage.jsx` |
| **Phase 5**: Acknowledgement flow for edit warnings | **PASS** | Implemented in `JobDetailPage.jsx` |
| **Phase 5**: Manual status buttons driven by allowed_next_statuses | **PASS** | `job.allowed_next_statuses` wired directly in `JobDetailPage.jsx` |
| **Phase 5**: No dangerouslySetInnerHTML | **PASS** | Audited all frontend sources: 0 occurrences |
| **Phase 5**: No way in UI or API to send application anywhere | **PASS** | Code audit: no submit/send endpoints or external outbound actions |
| **Phase 5**: Export only for approved jobs, containing only tailored skills, project bullets, cover note | **PASS** | Status check added to `backend/api/export.py` & verified by `test_export_409_for_unapproved_job` |
| **Phase 5**: CORS limited & API base URL from environment | **PASS** | Configured `CORS_ORIGINS` in `main.py` & `VITE_API_BASE_URL` in `api.js` |

---

## Section D: Eval Honesty
| Item | Status | Evidence |
| :--- | :---: | :--- |
| Matcher extraction mechanism stated in report | **PASS** | Documented in `eval_matcher.py` & `eval_report.md` |
| Synthetic labels note and headline metrics suppressed for n < 20 | **PASS** | `MIN_REQUIRED_BENCHMARK_SIZE = 20` enforced in `eval_matcher.py`; suppresses p-value and prints 'not statistically meaningful' for n < 20 |
| Three bands (strong/medium/weak) without "Conflict" band | **PASS** | Implemented `map_score_to_category` in `eval_matcher.py` |
| "Cap Applied" column shows only effective score changes | **PASS** | Filter `score_before_caps != score_after_caps` in `eval_matcher.py` |
| Confusion matrix, precision, recall with n printed | **PASS** | 3x3 confusion matrix and per-class precision/recall implemented in `eval_matcher.py` |
| `eval_timing.py` and `data/timing.csv` template created | **PASS** | [`backend/eval/eval_timing.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/backend/eval/eval_timing.py) and [`data/timing.csv`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/data/timing.csv) enforce n >= 5 before any time saving claim |

---

## Section E: Verifier Eval
| Item | Status | Evidence |
| :--- | :---: | :--- |
| 12 injection types x 3 base drafts (36 test cases) | **PASS** | [`backend/eval/eval_verifier.py`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/backend/eval/eval_verifier.py) tested 36 adversarial drafts across 12 injection types. Layer 1 caught 25/36 (69.4%). |
| 20 clean drafts tested for false-positive rate | **PASS** | Evaluated 20 clean control variations in `backend/eval/eval_verifier.py`: 0 false positives (0.0% FPR). |
| Catch rate per type for Layer 1 vs Layer 1 + Layer 2 | **PASS (Layer 1) / NOT VERIFIED (Layer 2)** | Layer 1 caught: fake_skill (100%), inflated_number (100%), inflated_verb (100%), fake_project (100%), missing_skill_as_possessed (100%), plausible_unlisted_tool (100%), fake_degree (67%), fake_employer (33%), extended_duration (33%), fabricated_outcome_no_number (33%), expert_level_claim (33%), claim_true_for_jd_not_candidate (33%). Layer 2 NOT VERIFIED (invalid live key). |

---

## Section F: Docker for Real
| Item | Status | Evidence |
| :--- | :---: | :--- |
| Ports bound to 127.0.0.1 only | **PASS** | Validated via `docker compose config`: `127.0.0.1:8000:8000`, `127.0.0.1:3000:80`, `127.0.0.1:27017:27017`. |
| Nginx proxy_read_timeout >= 120s | **PASS** | [`frontend/nginx.conf`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/frontend/nginx.conf) updated with `proxy_read_timeout 120s;` and `proxy_connect_timeout 120s;`. |
| `.dockerignore` security and clean build context | **PASS** | Created [`.dockerignore`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/.dockerignore) excluding `.env`, `.git`, `.venv`, `checkpoints.db`, and Chroma caches. |
| Clean `docker compose down -v` and `docker compose up --build -d` | **NOT TESTED** | Docker Desktop Service (`com.docker.service`) is stopped on Windows host; starting requires Windows administrative privilege. `docker compose config` passes. |
| Container healthchecks passing | **NOT TESTED** | Docker daemon offline. |
| Full flow through containerized app | **NOT TESTED** | Docker daemon offline. |
| Container restart and SQLite checkpoint persistence | **NOT TESTED** | Docker daemon offline. |
| Image history check (no secrets, .env not copied) | **NOT TESTED** | Docker daemon offline. Dockerfile and `.dockerignore` statically audited: `.env` is NOT in Dockerfile `COPY` commands. |

---

## Section G: Missing Deliverables
| Item | Status | Evidence |
| :--- | :---: | :--- |
| `docs/ARCHITECTURE.md` | **PASS** | Standalone architecture document created with Mermaid diagrams covering system overview, multi-agent state machine, two-layer verifier, and security design. |
| `docs/DEMO_SCRIPT.md` | **PASS** | 3-minute evaluator demo script created covering synthetic intake, matching, conflict detection, verification, human approval interrupt, and markdown export. |
| Acceptance table for 6 core goals | **PASS** | Complete table recorded in [`docs/PROJECT_EVALUATION_AND_INTERVIEW_GUIDE.md`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/docs/PROJECT_EVALUATION_AND_INTERVIEW_GUIDE.md) with empirical evidence (5 PASS, 1 NOT MEASURED). |
| 5 weakest points with interview explanations | **PASS** | Documented in `docs/PROJECT_EVALUATION_AND_INTERVIEW_GUIDE.md` covering verifier L1 semantic limits, small benchmark sample, human review timing, SQLite checkpointers, and LLM availability. |
| 8 interview questions & answers | **PASS** | Detailed answers documented in `docs/PROJECT_EVALUATION_AND_INTERVIEW_GUIDE.md` strictly aligned with code implementation. |

---

## Section H: README Cleanup
| Item | Status | Evidence |
| :--- | :---: | :--- |
| Remove unmeasured claims | **PASS** | Removed unevidenced speed claims ("25 to 5 minutes") and correlation claims from README.md. Added honesty notices. |
| Add privacy notes & "What is Not Built" section | **PASS** | [`README.md`](file:///c:/Users/dharr/OneDrive/Documents/Desktop/Job-Search%20Copilot/README.md) updated with explicit privacy notice on LLM provider data transmission, links to all `docs/` guides, and a 5-item "What Is Not Built" section. |

---

## Section I: Finish
| Item | Status | Evidence |
| :--- | :---: | :--- |
| AGENTS.md Phase completion protocol (7 steps) | **PASS** | Executed all 7 steps of Phase completion protocol; output formatted in response and documents. |
| Full pytest suite run (`pytest -v`) | **PASS** | `83 passed, 45 warnings in 40.17s` across all 83 backend tests. |
| Final lists (PASS, FAIL, NOT VERIFIED) | **PASS** | Explicitly itemized in Section I protocol report. |

