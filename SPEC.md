# Job-Search Copilot — Specification

## 1. Goal
Cut the time to prepare an internship application from about 25 minutes to about 5 minutes of review, without ever fabricating experience and without sending anything automatically. Single user, runs locally.

## 2. User Flow
1. Upload a resume (PDF or DOCX). It is parsed into a structured Profile.
2. Set preferences: target roles, max duration (up to 6 months), preferred locations, remote OK, skills to emphasise, skills to avoid, score thresholds.
3. Add a job by pasting JD text or a public URL.
4. System extracts job details, scores the match, explains it (matched skills, gaps).
5. If the score is high enough, it tailors skills and project bullets and drafts a 120–180 word cover note.
6. A verifier agent checks the drafts for invented claims. Failed drafts are retried (max 2).
7. Workflow pauses for human approval: approve, edit, or reject.
8. Jobs are tracked through statuses: `saved`, `drafted`, `approved`, `applied` (set manually), `interview`, `rejected`.

## 3. Agents
- **Profile agent**: `resume file -> Profile JSON`. Indexes chunks into ChromaDB.
- **Job intake agent**: `JD text or URL -> Job JSON`.
- **Matching agent**: `Profile + Job -> Match JSON` (deterministic score, LLM-written reasoning).
- **Planner (supervisor)**: routes the workflow based on score and state.
- **Tailoring agent**: reorders and rewords skills and project bullets for the JD using only facts in the Profile.
- **Cover note agent**: drafts a short role-specific note (120–180 words).
- **Verifier agent**: checks every claim in the drafts against the Profile.
- **Tracker agent**: updates status and follow-up reminders.

## 4. Workflow (LangGraph)

```
START -> job_intake -> match -> planner
planner:
  score < min_score_to_consider            -> mark_skipped (store reason) -> END
  min_score_to_consider <= score < min_score_to_tailor
                                           -> confirm_tailoring (interrupt) -> tailor, or END
  score >= min_score_to_tailor             -> tailor
tailor -> cover_note -> verify
verify:
  fails and retries < 2   -> tailor (pass verifier feedback)
  fails and retries >= 2  -> manual_edit_required (interrupt)
  passes                  -> approval (interrupt)
approval:
  approve -> mark_ready -> END
  edit    -> save_edits -> mark_ready -> END
  reject  -> store_feedback -> END
```

Use LangGraph interrupts and a checkpointer so paused runs resume later. The two thresholds come from Preferences (defaults: `min_score_to_consider = 40`, `min_score_to_tailor = 70`), not hardcoded.

## 5. Data Models (Pydantic)

```python
class Education:
    institution: str
    degree: str
    field: str
    start_year: int
    end_year: int | None = None
    cgpa: float | None = None

class Project:
    title: str
    bullets: list[str]
    tech: list[str]
    link: str | None = None

class Experience:
    company: str
    role: str
    start_date: str
    end_date: str | None = None
    bullets: list[str]

class Profile:
    name: str
    education: list[Education]
    skills: list[str]            # normalised, deduplicated
    projects: list[Project]
    experience: list[Experience]
    links: dict[str, str]

class Preferences:               # single document, single-user v1
    target_roles: list[str] = []
    max_duration_months: int = 6
    preferred_locations: list[str] = []
    remote_ok: bool = True
    emphasise_skills: list[str] = []
    avoid_skills: list[str] = []
    min_score_to_tailor: int = 70
    min_score_to_consider: int = 40

class Job:
    id: str
    company: str
    title: str
    source: str                  # "pasted" or the URL
    jd_text: str
    required_skills: list[str]
    preferred_skills: list[str]
    duration_months: int | None = None
    location: str | None = None
    created_at: datetime

class Match:
    job_id: str
    score: int                   # 0-100 (deterministic)
    matched_skills: list[str]
    missing_skills: list[str]
    reasoning: str               # 2-4 sentences by LLM
    preference_conflicts: list[str]

class ProjectBullets:
    project_title: str           # same project titles as in Profile
    bullets: list[str]

class TailoredResume:
    job_id: str
    skills_section: list[str]
    project_bullets: list[ProjectBullets]
    version: int

class VerificationResult:
    passed: bool
    unsupported_claims: list[str]
    notes: str
```

## 6. Matching Approach
- Embed profile chunks (skills, each project, each experience) in ChromaDB using local `sentence-transformers/all-MiniLM-L6-v2`.
- Extract required and preferred skills from the JD with the LLM (JSON output).
- Deterministic scoring: required-skill coverage (~50%), semantic similarity of projects to the JD (~30%), preference fit such as duration and location (~20%). Weights configured in a config file.
- The LLM writes only the human-readable reasoning, not the score.

## 7. Verifier Design
- Extract every factual claim from tailored skills, project bullets, and cover note (skills named, tools used, outcomes, numbers).
- Check each claim against the Profile. Unsupported claims go into `unsupported_claims`.
- Fail if any unsupported claim exists. Numbers (percentages, counts) must match the Profile exactly.
- On retry, feed `unsupported_claims` back to the tailoring agent.

## 8. API (FastAPI)
- `GET /health`
- `POST /profile/upload`, `GET /profile`, `PUT /profile`
- `GET /preferences`, `PUT /preferences`
- `POST /jobs` (JD text or URL; starts workflow), `GET /jobs`, `GET /jobs/{id}`
  - `GET /jobs/{id}` includes `pending_interrupt: {type, payload}` when paused.
- `POST /jobs/{id}/decision` body `{interrupt_type, action, edits?, feedback?}`
  - Interrupt types and allowed actions:
    - `confirm_tailoring`: `proceed` | `skip`
    - `manual_edit_required`: `submit_edits` | `abandon`
    - `approval`: `approve` | `edit` | `reject`
  - Validation: return 409 if `interrupt_type` does not match graph's pending interrupt, and 422 if `action` is invalid for that type.
- `PATCH /jobs/{id}/status` (manual status updates)
- `GET /logs?job_id=`
- `GET /export/{id}` (DOCX and Markdown excerpt containing tailored skills, project bullets, and cover note)

## 9. Key Decisions
- **LLM provider**: Google Gemini API by default; wrapper also includes stubs for OpenAI and Ollama. `.env.example`: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=`, `LLM_MODEL=` (configurable, never hardcoded), `EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2`. Local embeddings ensure resume text is not sent out for embedding (note in README that resume and JD text are sent to LLM for parsing/drafting).
- **Checkpointer**: Use official LangGraph MongoDB checkpointer if compatible; fallback to SQLite. Placed behind a single factory function.
- **URL extraction**: `httpx` + `trafilatura`, plain User-Agent, 10s timeout, follow redirects. If request fails (403, 429, timeout) or extracted text < ~200 characters, return 422 asking user to paste JD text. Store source URL either way.
- **Export scope**: `GET /export/{id}` returns a DOCX (and .md copy) containing only tailored skills section, tailored project bullets, and cover note under clear headings, with job title and company at the top. (No full resume rebuilding in v1; stretch goal).
- **Frontend pages**: (1) Profile and preferences, (2) Jobs board with filters, (3) Job detail with match reasoning, original vs tailored skills side by side, cover note editor, verification result, and decision buttons for pending interrupts, (4) Agent log timeline.

## 10. Non-Goals for v1
- Auto-submitting applications.
- Logging into job sites.
- LinkedIn or Naukri scraping.
- Multi-user accounts.
- Cloud deployment.
- Full resume template rebuilding.

## 11. Build Phases
- **Phase 0: Scaffold**: Folder structure, FastAPI app with `/health`, LLM client wrapper, Docker Compose for MongoDB, `.env.example`, requirements.txt, pytest with one passing test.
  - *Done when*: pytest passes and the API starts.
- **Phase 1: Profile agent**: Parse PDF and DOCX into Profile validated by Pydantic. Index chunks in ChromaDB. Endpoints: `POST /profile/upload`, `GET /profile`, `PUT /profile`, `GET /preferences`, `PUT /preferences`. Tests with sample resume fixture.
  - *Done when*: sample resume parses correctly and tests pass.
- **Phase 2: Intake and matching**: Job intake (pasted text and URL), matching with deterministic score and LLM reasoning, weights in config. `POST /jobs` (intake and match only for now), `GET /jobs/{id}`. Tests with 3 sample JDs.
  - *Done when*: endpoint returns a score and reasons for 3 sample JDs.
- **Phase 3: Tailoring, cover note and verifier**: Plain Python functions with retry loop. Tests that inject a fake skill and a changed number and assert the verifier catches both.
  - *Done when*: those tests pass.
- **Phase 4: LangGraph workflow**: Section 4 graph exactly, planner routing, three interrupts, checkpointing, `agent_log` for every node, `POST /jobs/{id}/decision` validation. Include graph diagram.
  - *Done when*: full flow runs end to end via API with a pause and resume for each interrupt type.
- **Phase 5: React frontend**: 4 pages wired to API. Verified in browser: upload resume, add job, see match, approve draft. Screenshots in walkthrough.
  - *Done when*: full flow works in the browser.
- **Phase 6: Evaluation and polish**:
  - `backend/eval/eval_matcher.py`: runs matcher on `data/jds/` vs `data/labels.csv`, reports accuracy and Spearman correlation.
  - `backend/eval/eval_verifier.py`: injects fake skills and inflated numbers into tailored drafts, reports catch rate.
  - Auto-generated `eval_report.md` from real numbers.
  - README with setup steps, Mermaid architecture diagram, 3-minute demo script. `docker compose up` runs the app.
  - *Done when*: eval report generated from real data and `docker compose up` runs app.
