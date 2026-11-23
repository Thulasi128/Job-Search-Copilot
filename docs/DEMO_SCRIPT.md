# Evaluator Demo Script (3-Minute Walkthrough)

This script provides an exact, end-to-end walkthrough for evaluators demonstrating the core capabilities of **Job-Search Copilot** using synthetic candidate fixtures.

---

## Prerequisites

1. Activate virtual environment and ensure dependencies are installed:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. Verify system health:
   ```powershell
   python scripts/check_llm.py
   ```
   *(Note: If no valid live Gemini API key is configured, the system operates seamlessly in deterministic/mock fallback mode).*

---

## 3-Minute Walkthrough Steps

### Minute 1: Candidate Intake & Preferences Setup

1. **Upload Synthetic Candidate Profile**:
   Run the synthetic profile intake or POST synthetic resume to `/profile`:
   ```powershell
   python -c "import asyncio; from backend.models.profile import get_synthetic_profile; from backend.database import get_db, init_db; async def main(): await init_db(); db = get_db(); p = get_synthetic_profile(); await db.profile.replace_one({'_id': 'default_profile'}, p.model_dump(by_alias=True), upsert=True); print('Profile loaded:', p.name, 'with', len(p.skills), 'skills'); asyncio.run(main())"
   ```
   - **Verification**: Profile contains genuine student facts (B.S. Computer Science, 3.85 GPA, projects TaskStreamer, SecureAuth, DataPipe).

2. **Set User Preferences**:
   - Auto-proceed threshold: $\ge 70\%$
   - Manual confirmation threshold: $40\% - 70\%$
   - Skip threshold: $< 40\%$
   - Conflict keywords: `US Citizenship Required`, `Active Top Secret Clearance`.

---

### Minute 2: Job Intake & Multi-Agent Matching

1. **Submit Evaluator Benchmark Jobs**:
   Submit the three evaluation fixtures from `data/jds/`:
   - `eval_job_strong.txt`: Full-Stack SWE Intern (Python, FastAPI, React)
   - `eval_job_conflict.txt`: Defense Software Intern (Requires US Citizenship / Security Clearance)
   - `eval_job_weak.txt`: Senior Embedded Systems Engineer (10+ yrs C/Assembly, Kernel drivers)

2. **Observe Matcher Decisions & Hard Cap Enforcement**:
   - **Strong Job**: Matches Python, FastAPI, React. Score $\approx 92\%$. Automatically advances to drafting.
   - **Conflict Job**: High technical alignment but contains clearance conflict keyword. Hard cap drops score to $\le 30\%$ and sets `conflict_detected=True`. Automatically marked `skipped`.
   - **Weak Job**: Embedded firmware role with missing prerequisites. Score $\approx 18\%$. Automatically marked `skipped`.

---

### Minute 3: Tailoring, Two-Layer Verification, & Export

1. **Trigger Tailoring & Verification**:
   - The Tailoring Agent selects relevant projects (`TaskStreamer`, `SecureAuth`) and extracts tailored bullets.
   - The Cover Note generator writes a targeted 120-180 word note.
   - **Two-Layer Verification Executes**:
     - Layer 1 verifies skills subset, word count, project title matches, and numbers.
     - If verified, job pauses at state `awaiting_approval`.

2. **Test Human-in-the-Loop Interrupt**:
   - Attempt to export before approval:
     ```powershell
     curl -i http://localhost:8000/export/{job_id}
     ```
     *Returns HTTP 409 Conflict: Application must be approved before export.*
   - Submit human approval:
     ```powershell
     curl -X POST http://localhost:8000/jobs/{job_id}/decide -H "Content-Type: application/json" -d "{\"action\": \"approve\", \"interrupt_type\": \"approval\"}"
     ```
   - Status transitions to `approved`.

3. **Export Verified Application Bundle**:
   - Fetch the final Markdown package:
     ```powershell
     curl http://localhost:8000/export/{job_id}?format=markdown
     ```
   - Inspect output: Perfectly tailored bullets, verified metrics (35% latency reduction, 500 users), exact 120-180 word cover note, zero invented skills or credentials.

---

## Key Invariants to Highlight to Observers
1. **Never Invented**: Check `skills_section` vs profile skills; every single token matches candidate experience.
2. **Never Auto-Sent**: Workflows pause at interrupts; human approval is strictly mandatory before export or status closure.
3. **Audit Trail**: Every action, retry, and verification pass is permanently logged in MongoDB `agent_log` with step duration and token counts.

