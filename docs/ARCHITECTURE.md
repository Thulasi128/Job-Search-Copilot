# System Architecture & Technical Specifications

Job-Search Copilot is a local-first, multi-agent AI assistant designed to prepare high-quality, verified software internship applications while eliminating LLM hallucinations and preserving complete human control.

```mermaid
flowchart TD
    User([User / Browser]) <--> UI[React + Vite Frontend\nPort 3000 / Nginx]
    UI <--> API[FastAPI Backend\nPort 8000]
    
    subgraph Data Layer
        Mongo[(MongoDB 7.0\nMotor Async Driver)]
        Chroma[(ChromaDB\nLocal Cosine Vector Store)]
        Sqlite[(SQLite\nLangGraph Checkpointer)]
    end

    subgraph LangGraph Multi-Agent Engine
        IntakeNode[Intake & Validation] --> MatchNode[Embedding & Matcher Agent]
        MatchNode --> DecInterrupt{Confirmation Interrupt\nPending Threshold Check}
        DecInterrupt --> TailorNode[Tailoring Agent]
        TailorNode --> VerifyNode[Two-Layer Verifier Agent]
        VerifyNode --> ApprInterrupt{Approval Interrupt\nVerification Gate}
        ApprInterrupt --> ExportNode[Export Engine]
    end

    subgraph LLM Layer
        LLMWrapper[Provider-Agnostic Client\nbackend/llm/client.py]
        Gemini[Google Gemini API / Mock Fallback]
    end

    API <--> Mongo
    API <--> Chroma
    API <--> Sqlite
    IntakeNode <--> Mongo
    MatchNode <--> Chroma
    TailorNode <--> LLMWrapper
    VerifyNode <--> LLMWrapper
    LLMWrapper <--> Gemini
```

---

## 1. Core Architectural Principles

1. **Anti-Hallucination Invariant**: The system never invents skills, experiences, degrees, employers, or project metrics. Tailoring only reorders, selects, and highlights genuine candidate facts.
2. **Mandatory Human-in-the-Loop**: No resume or cover letter is ever submitted or marked approved automatically. Applications pause at human checkpoints for review.
3. **Fail-Closed Verification**: If an LLM call fails during verification, the verification result defaults to `passed=False` with error flags. A draft can never reach `approved` status without passing verification or having an explicit human override recorded.
4. **Minimal Checkpoint State**: LangGraph checkpoints persist state across interrupts in SQLite. To prevent data staleness and duplication of personal data, `JobState` holds only identifiers, counters, and small status summaries. Large documents (Profile, Job description, full drafts) are persisted in MongoDB.

---

## 2. Multi-Agent Workflow State Machine

The orchestration engine is built on LangGraph with state persistence in SQLite (`checkpoints.db`) and atomic conditional status updates in MongoDB.

```mermaid
stateDiagram-v2
    [*] --> saved : POST /jobs
    saved --> processing : Background Task Spawned
    processing --> awaiting_confirmation : Score Between Thresholds (e.g., 40-70)
    processing --> skipped : Score < Min Threshold (e.g., < 40)
    processing --> drafting : Score >= Auto Threshold (e.g., >= 70)
    
    awaiting_confirmation --> drafting : User Proceed
    awaiting_confirmation --> skipped : User Skip
    
    drafting --> awaiting_approval : Verification Passed
    drafting --> awaiting_manual_edit : Verification Failed (Max Retries)
    drafting --> failed : Uncaught Node Error
    
    awaiting_manual_edit --> awaiting_approval : Valid Edits Submitted
    awaiting_manual_edit --> closed : User Abandoned
    
    awaiting_approval --> approved : User Approved (Verified or Override)
    awaiting_approval --> rejected : User Rejected
    
    approved --> applied : Manual Status Update
    applied --> interview : Status Progression
    interview --> closed : Completed
    rejected --> closed : Archived
    skipped --> closed : Archived
    failed --> processing : POST /jobs/{id}/retry
```

### Transition Integrity & Invariant Enforcement
All status transitions pass through a single centralized validator `apply_status_transition()` executing an atomic MongoDB conditional update:
```python
result = await collection.update_one(
    {"_id": job_id, "status": current_status},
    {"$set": {"status": next_status, "updated_at": now}}
)
```
- **Approval Invariant**: Transitioning to `approved` is strictly rejected (HTTP 409) unless the latest draft in MongoDB has `verification.passed == True` or `user_override == True`.
- **Export Invariant**: Generating markdown or plaintext exports (`GET /export/{id}`) is permitted only when status is `approved`, `applied`, `interview`, or `closed`.

---

## 3. Two-Layer Verification Architecture

Drafts produced by the Tailoring Agent are subjected to an adversarial two-layer verification pipeline before presentation to the user:

```mermaid
flowchart TD
    Draft[Tailored Draft + Cover Note] --> L1[Layer 1: Deterministic Engine]
    
    subgraph Layer 1 Checks
        L1_Skills[Skills Subset Check\nDraft skills ⊆ Profile skills]
        L1_Proj[Project Titles & Bullets Check\nTitles exact match; ≤3 bullets/project]
        L1_Num[Numbers & Metrics Verification\nRegex audit against source profile]
        L1_Degree[Degree & University Verification]
        L1_Length[Cover Note Length Guard\n120 - 180 words strictly enforced]
    end
    
    L1 --> L1_Skills
    L1 --> L1_Proj
    L1 --> L1_Num
    L1 --> L1_Degree
    L1 --> L1_Length
    
    L1_Skills & L1_Proj & L1_Num & L1_Degree & L1_Length --> L1_Gate{Any L1 Violations?}
    L1_Gate -- Yes --> Reject[Mark Draft Failed\nTrigger Regenerate / Manual Edit]
    L1_Gate -- No --> L2[Layer 2: Semantic LLM Claim Checker]
    
    subgraph Layer 2 Checks
        L2_Claims[Extract Factual Claims]
        L2_Verify[Verify Every Claim Against Profile Evidence]
        L2_Inflate[Detect Verb / Seniority Inflation]
    end
    
    L2 --> L2_Claims --> L2_Verify --> L2_Inflate --> L2_Gate{All Claims Supported?}
    L2_Gate -- Yes --> Pass[Verification Passed\nAdvance to Awaiting Approval]
    L2_Gate -- No / LLM Error --> Reject
```

1. **Layer 1 (Deterministic)**:
   - Zero LLM latency, zero cost, completely deterministic.
   - Skill containment: Asserts every skill in `skills_section` exists verbatim in `profile.skills`.
   - Metric preservation: Extracts all numbers, percentages, and metrics (`\b\d+(?:[.,]\d+)*%?`) and confirms they exist in candidate source achievements.
   - Constraint gating: Checks that project count $\le 3$, bullet counts $\le 3$ per project, and cover note length is between 120 and 180 words.
2. **Layer 2 (Semantic LLM Check)**:
   - Extracts factual assertions and maps them to profile evidence.
   - Flags seniority inflation (e.g., student described as "Staff Architect" or "World-class authority").
   - **Fail-Closed Guarantee**: If the LLM call times out, returns HTTP 429/500, or provides unparseable output, Layer 2 returns `passed=False` with `reason="LLM verification layer unavailable - fail closed"`.

---

## 4. Security & Privacy Safeguards

- **Strict Localhost Binding**: All exposed network ports in Docker Compose bind exclusively to `127.0.0.1` (`127.0.0.1:8000`, `127.0.0.1:3000`, `127.0.0.1:27017`).
- **SSRF Defense Engine**: Public JD URL fetching verifies target host DNS resolutions, explicitly rejecting private IPv4 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8), IPv4-mapped IPv6, and link-local ranges, with manual redirect following up to 3 hops and 2 MB streaming limits.
- **Privacy in Observability**: Agent logs record token counts, step names, and validation statuses. Full resume text, job description bodies, and raw API keys are strictly excluded from logs.
- **Provider-Agnostic LLM Isolation**: All generative inference flows through `backend/llm/client.py` with automatic exponential backoff retry for rate limits.

