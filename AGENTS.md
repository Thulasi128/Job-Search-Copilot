# Job-Search Copilot — Agent Rules & Guidelines

A local multi-agent web application that helps a student prepare internship applications. The system parses resumes, evaluates candidate-job fit, tailors skills and project bullets, drafts cover notes, verifies against hallucinations, and pauses for human approval.

## Stack
- Backend: Python 3.11, FastAPI, LangGraph, Pydantic
- Vector store: ChromaDB (local with `sentence-transformers/all-MiniLM-L6-v2`)
- Database: MongoDB (via `motor`)
- Frontend: React + Vite, plain CSS or Tailwind
- LLM: accessed ONLY through `backend/llm/client.py` (provider-agnostic wrapper with `generate_text` and `generate_json(schema)`)
- Dev & Testing: Docker Compose for MongoDB, pytest for tests

## Hard Rules
1. **Never invent resume content.** Tailoring may reorder and reword real facts only.
2. **Nothing is ever sent anywhere.** The system prepares drafts; a human approves.
3. **No scraping of LinkedIn or login-gated sites.** No headless browsers. No attempts to bypass blocks. Input is pasted JD text or a public URL.
4. **Every agent action is written to the `agent_log` collection.**
5. **All LLM outputs consumed by code must be validated JSON (Pydantic models).**
6. **All LLM calls go through `backend/llm/client.py`**, which provides `generate_text` and `generate_json(schema)`.
7. **No secrets in code.** Use `.env` and provide `.env.example`. Add `data/`, `.env`, and local caches to `.gitignore`.
8. **Prompts live in `backend/prompts/` as files**, not inline strings.
9. **Small typed functions, a docstring on every public function.**
10. **Tests mirror the source tree in `backend/tests/`.**
11. **Before finishing any task: run tests, then summarise what changed.**
12. **For any task touching more than 2 files, plan first.**
13. **Build one phase at a time.** Do not start a later phase early. Do not build shallow versions of everything at once.
14. **Never invent numbers, results, or test outcomes.** Report only what was actually run.

## Phase completion protocol (mandatory at the end of every phase)
1. Requirement table: re-read SPEC.md for this phase. For every requirement mark PASS / FAIL / NOT TESTED with evidence (a test name or real command output). No PASS without evidence.
2. Run the full test suite including `-m slow` and paste the summaries.
3. Run a real run-through (real local embeddings, a real Gemini call if a key is present, NOT mocks) on the synthetic fixtures and show the actual outputs.
4. Try to break it: run at least 5 adversarial or edge cases specific to this phase and show the results.
5. Re-check the hard rules in AGENTS.md against the code just written (no fabrication, nothing auto-sent, no secrets or full resume/JD text in logs, all LLM output validated, all LLM calls via the wrapper).
6. Project-fit verdict: does what was built move us toward the goal (an application prepared in about 5 minutes of review, no fabricated claims, nothing sent automatically)? Say plainly where it falls short.
7. Honesty section: list everything that was mocked, everything not verified, known limitations, and any decision made that is not in SPEC.md.
Then stop and wait for my approval.
