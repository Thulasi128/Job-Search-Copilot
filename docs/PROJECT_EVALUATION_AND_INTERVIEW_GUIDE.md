# Project Acceptance, Limitations & Technical Interview Guide

This document records the final acceptance evaluation across the 6 core project goals, details the 5 weakest architectural points with candidate interview explanations, and provides answers to 8 likely technical interview questions based strictly on the implemented codebase.

---

## 1. Acceptance Table: 6 Core Project Goals

| Core Goal | Status | Evidence & Actual Result |
| :--- | :---: | :--- |
| **1. Never Invent Resume Content** (Tailoring may only reorder and reword real facts) | **PASS** | Evaluated via Layer 1 deterministic checks and 36 adversarial injection tests in `backend/eval/eval_verifier.py`. Code enforces: `skills_section` $\subseteq$ `profile.skills`, exact project titles, metric audit (`\b\d+(?:[.,]\d+)*%?`), and blocks unearned claims. |
| **2. Nothing Is Ever Sent Anywhere** (System prepares drafts; human approves) | **PASS** | Workflows pause via LangGraph interrupts at `awaiting_approval`. Transition to `approved` requires explicit human API decision `/jobs/{id}/decide`. Direct export (`GET /export/{id}`) blocks with HTTP 409 if status is unapproved. No external dispatch endpoints or email integrations exist. |
| **3. Safe Intake Without Gated Scraping** (No LinkedIn/login bypass; pasted or public URL only) | **PASS** | Tested in `backend/tests/test_intake.py` and SSRF test suite. Public URL fetcher verifies IP ranges, rejects private/loopback/link-local IPv4 and IPv6, caps streams at 2 MB, follows max 3 redirects, and extracts main text using readability/bs4 without headless browsers. |
| **4. Strict Audit Logging** (Every agent action written to `agent_log`) | **PASS** | Verified in `backend/tests/test_agent_log.py`. `log_agent_action` records `agent_name`, `step_name`, `duration_ms`, `tokens_used`, and `status`. Sensitive fields (raw API keys, full JD body, full resume) are sanitized. |
| **5. Strict Schema Validation** (All LLM outputs consumed by code are validated Pydantic models) | **PASS** | Verified in `backend/tests/test_llm_client.py` and `backend/agents/tailoring_agent.py`. All structured calls go through `generate_json(schema)` returning validated Pydantic instances (`ExtractedJD`, `TailoredResume`, `CoverNote`, `VerificationResult`). Invalid schema triggers one structured repair retry before failing closed. |
| **6. Fast Application Preparation (~5 minutes review time)** | **NOT MEASURED** | Evaluated honestly: No human trial data ($n \ge 5$) exists yet. Framework created in `backend/eval/eval_timing.py` and `data/timing.csv`, but synthetic automated tests cannot measure human review speed. Unsubstantiated time claims have been removed from documentation. |

---

## 2. Five Weakest Points of the Project (With Interview Explanations)

### 1. Layer 1 Verifier Relies on Heuristics for Seniority & Entity Claims
- **Weakness**: Layer 1 catches 100% of unearned skills, metric inflations, project title mismatches, and length violations (69.4% overall L1 catch rate across 36 adversarial cases). However, subtle semantic claims like unearned senior titles ("Staff Architect") or plausible fabricated employers ("Netflix") slip past Layer 1 regexes and rely on the Layer 2 LLM.
- **Interview Explanation**:
  > *"Deterministic string matching and regexes excel at token containment (skills, numbers, project titles), but they cannot evaluate world knowledge or semantic scope without maintaining an exhaustive entity ontology. In our architecture, Layer 1 serves as an instant, zero-cost first line of defense that catches over two-thirds of blatant hallucinations before any token is spent, while Layer 2 (LLM fact extraction) inspects semantic alignment. When Layer 2 is unavailable or rate-limited, the system fails closed rather than accepting unverified drafts."*

### 2. Matcher Evaluation Dataset Size ($n=3$ synthetic jobs)
- **Weakness**: The current automated test suite evaluates matcher performance against 3 synthetic benchmark jobs (strong, conflict, weak). While sufficient for smoke-testing logic, this is statistically inadequate for calculating Spearman rank correlation or statistical significance ($p < 0.05$).
- **Interview Explanation**:
  > *"We chose rigorous statistical honesty over inflated claims. Rather than reporting a misleading '100% correlation' on a sample of three jobs, we refactored our evaluation suite to explicitly suppress p-values and headline correlation metrics whenever $n < 20$. The pipeline defines a standardized benchmark protocol ready for 30+ real labeled job descriptions, but until those labeled samples are collected, we report only raw confusion matrices and classify the run as a smoke test."*

### 3. Application Preparation Time Unproven on Real Users
- **Weakness**: The project premise is that students can prepare an internship application in ~5 minutes of review. We have not conducted controlled trials with real human applicants.
- **Interview Explanation**:
  > *"Automated tests verify that the software pipeline generates, verifies, and formats an application draft in under 15 seconds. However, claiming that a human user finishes review in 5 minutes without empirical user testing violates our ground rules. We built `eval_timing.py` and the `data/timing.csv` logging harness to measure baseline manual drafting versus copilot review across multiple users, but we mark this metric as NOT MEASURED until verified across at least 5 empirical trials."*

### 4. In-Memory SQLite Checkpoints for LangGraph
- **Weakness**: While checkpoints survive application restarts via `checkpoints.db` on disk, SQLite checkpointers are local and not designed for horizontally scaled multi-worker backend fleets.
- **Interview Explanation**:
  > *"For a local, single-user student desktop application, SQLite checkpointers provide zero-maintenance transactional persistence with minimal overhead. The LangGraph state schema is kept strictly minimal (holding IDs, retry counters, and status flags rather than large blobs) specifically to decouple checkpoint state from the primary document store in MongoDB. If scaling to a hosted multi-tenant cloud service, this checkpointer would be swapped for Postgres or Redis checkpointers without modifying graph node logic."*

### 5. Dependency on LLM Provider Availability
- **Weakness**: While the system has fallback mechanisms for match reasoning (template fallback) and fails closed on verification, high-quality tailoring still requires an accessible generative LLM. If the provider returns 429 quota exhaustion, users cannot auto-generate new drafts.
- **Interview Explanation**:
  > *"Because our core hard rule prohibits fabricating resume content, we cannot synthesize new creative cover notes or bullet points when the LLM is completely unreachable. We mitigated this by building exponential backoff with jitter into our provider-agnostic client, enabling manual profile-based draft editing via `/jobs/{id}/decide`, and failing closed so that broken LLM responses can never silently slip unverified drafts into an approved state."*

---

## 3. Eight Likely Technical Interview Questions & Answers

### Q1: How do you guarantee the LLM never hallucinates skills or credentials the student doesn't have?
**Answer**:
> *"We do not rely on prompt instructions alone. We enforce anti-hallucination at three distinct architectural layers. First, the tailoring prompt receives only genuine profile facts and explicit instructions to select from them. Second, upon output, Layer 1 deterministic validation executes code-level containment checks: `tailored.skills_section` is checked as a mathematical subset of `profile.skills`, project titles must match existing profile projects verbatim, and all numbers and metrics are extracted via regex and verified against source achievements. Third, Layer 2 LLM semantic verification cross-references every factual assertion against candidate chunks. If any check fails, the draft is rejected or sent to human manual editing. Finally, the MongoDB status transition function enforces an invariant: a job cannot transition to `approved` unless its draft passed verification or an explicit human override is logged."*

### Q2: Why did you choose LangGraph for orchestration instead of a standard sequential script or Celery?
**Answer**:
> *"Application tailoring is inherently an interruptible, human-in-the-loop workflow. A job may need to pause when match scores are marginal (`awaiting_confirmation`), pause after drafting for user inspection (`awaiting_approval`), or halt when verification fails (`awaiting_manual_edit`). LangGraph provides native interrupt primitives and transactional checkpointing: when a human decision is needed, the graph yields control, serializes minimal state to SQLite, and resumes seamlessly when the user posts an approval or edit, without keeping background worker threads blocked."*

### Q3: Why is `JobState` in LangGraph kept minimal instead of storing the full resume and job description?
**Answer**:
> *"Checkpoints serialize state to disk on every step and interrupt. Storing full resume text, candidate contact details, and long JD texts inside the checkpoint database would duplicate personal data across multiple storage engines, increase serialization latency, and create a data staleness hazard if a candidate updates their profile while a job is paused. Instead, `JobState` holds only identifiers (`job_id`, `run_number`), numeric scores, retry counters, and status flags. Graph nodes fetch current business documents directly from MongoDB when executing."*

### Q4: How does your two-layer verifier handle LLM service outages or rate limit errors (HTTP 429)?
**Answer**:
> *"Our system enforces a strict fail-closed security policy. In `verify_draft()`, if Layer 1 passes but Layer 2 fails due to an API timeout, rate limit, or invalid response, the verification result explicitly returns `passed=False` with `reason='LLM verification layer unavailable - fail closed'`. Furthermore, the state transition function prevents the job from reaching `approved` without a passed verification result or an explicit human override. This prevents transient network or quota failures from silently bypassing safety controls."*

### Q5: How do you prevent Server-Side Request Forgery (SSRF) when fetching public job URLs?
**Answer**:
> *"When a user inputs a URL instead of pasted text, our URL fetcher performs strict pre-flight DNS resolution before opening an HTTP connection. It inspects all resolved IP addresses against blacklisted ranges: loopback (`127.0.0.0/8`, `::1`), private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), IPv4-mapped IPv6 addresses, and link-local ranges (`169.254.0.0/16`). It disables automatic redirects in the HTTP client and manually audits every redirect target IP up to a maximum of 3 hops, while enforcing a 2 MB streaming limit to prevent resource exhaustion."*

### Q6: How do you handle race conditions when two concurrent requests attempt to transition a job's status?
**Answer**:
> *"We implement defense-in-depth across the API and database. First, the FastAPI layer maintains an in-process per-job `asyncio.Lock` to serialize operations on any single job. Second, the definitive consistency guarantee is enforced at the database layer using an atomic conditional update in MongoDB: `update_one({'_id': job_id, 'status': current_status}, {'$set': {'status': next_status}})`. If a concurrent request changed the status millisecond earlier, the filter matches 0 documents and the transition function raises a 409 Conflict."*

### Q7: Why did you migrate the Chroma vector store from L2 distance to Cosine similarity?
**Answer**:
> *"The embedding model `sentence-transformers/all-MiniLM-L6-v2` produces normalized vectors where cosine similarity directly represents semantic relatedness on a calibrated scale from 0.0 to 1.0. L2 (Euclidean) distance scales from 0 to $\sqrt{2}$, where lower values represent higher similarity, requiring inversions that can introduce edge cases near boundaries. Migrating to cosine distance (`hnsw:space: cosine`) allows straightforward similarity calibration ($1 - \text{distance}$) and consistent thresholding for skill and experience chunk matching."*

### Q8: What did you learn from your evaluation benchmarks, and what would you improve next?
**Answer**:
> *"Our verifier benchmark revealed that Layer 1 deterministic checks catch 100% of unearned skills, metric exaggerations, project mismatches, and length violations, achieving a 69.4% catch rate across 36 adversarial injections with 0.0% false positives on clean drafts. However, subtle semantic claims like unearned senior titles or plausible unlisted employers require Layer 2 semantic verification. If continuing development, my next priority would be expanding the local deterministic knowledge base to include candidate degree, university, and employment history tokens in Layer 1, pushing deterministic catch rate above 85% before invoking any LLM."*

