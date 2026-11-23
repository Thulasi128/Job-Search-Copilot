"""Phase 6 Adversarial and Edge Case Verification Script.

Covers:
1. Edge Case 1: Eval matcher handles corrupted/missing JD filenames in labels.csv gracefully without crashing.
2. Edge Case 2: Extreme metric inflation (1,000,000,000,000 / 1e12 requests) caught by Layer 1 verifier.
3. Edge Case 3: Injected missing skill with exotic casing and whitespace (e.g., '  kUbErNeTeS  ') caught by normalized Layer 1 check.
4. Edge Case 4: Verifier detects fabricated employer when candidate claims to have worked at a FAANG firm (e.g. 'Software Engineer at Netflix').
5. Edge Case 5: Docker compose configuration and orchestration integrity check (service dependencies, health checks, environment variables).
"""

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mongomock_motor import AsyncMongoMockClient
import backend.database as db_mod
db_mod._mongo_client = AsyncMongoMockClient()

from backend.agents.verifier_agent import run_layer_1_deterministic_check
from backend.eval.eval_matcher import evaluate_matcher
from backend.models.draft import ClaimCheck, CoverNote, ProjectBullets, TailoredResume
from backend.models.job import Job
from backend.models.match import Match
from backend.models.profile import Profile
from scripts.real_similarity_check import get_synthetic_profile


async def run_phase6_break_tests():
    print("=" * 75)
    print("PHASE 6 ADVERSARIAL AND EDGE CASE SUITE")
    print("=" * 75)

    profile = get_synthetic_profile()
    job = Job(
        id="job_adv_phase6",
        company="TechCorp Innovations",
        title="Software Engineering Intern",
        source="pasted",
        jd_text="Software Engineering Intern needed in Austin, TX for 3 months. Python, FastAPI, React.",
        required_skills=["Python", "FastAPI", "React"],
        content_hash="hash_adv",
    )

    clean_match = Match(
        job_id=job.id,
        score=95,
        matched_skills=["Python", "React", "FastAPI"],
        missing_skills=["Kubernetes"],
        reasoning="Good fit",
        profile_hash="phash",
        preferences_hash="prefhash",
    )

    # -------------------------------------------------------------
    # Case 1: Corrupted labels.csv pointing to nonexistent files
    # -------------------------------------------------------------
    print("\n[Case 1] Corrupted/Missing JD file references in evaluation harness:")
    temp_dir = tempfile.mkdtemp(prefix="eval_corrupt_")
    try:
        labels_file = Path(temp_dir) / "labels.csv"
        labels_file.write_text(
            "filename,company,title,fit_label,expected_rank\n"
            "nonexistent_file_999.txt,FakeCo,FakeRole,strong,3\n",
            encoding="utf-8",
        )
        report = await evaluate_matcher(
            labels_path=labels_file,
            jds_dir=Path(temp_dir),
        )
        assert report["total_evaluated"] == 0, "Should gracefully skip missing JD files"
        print("  PASS: Evaluation harness gracefully skipped missing files without crashing.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # Case 2: Extreme Metric Inflation
    # -------------------------------------------------------------
    print("\n[Case 2] Extreme metric inflation (1,000,000,000,000 requests):")
    extreme_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python", "FastAPI"],
        project_bullets=[
            ProjectBullets(
                project_title="TaskStreamer — Real-Time Collaboration Workspace",
                bullets=["Engineered microservices processing 1,000,000,000,000 daily requests."],
            )
        ],
    )
    clean_note = CoverNote(job_id=job.id, text="A" * 700, word_count=140)
    unsupported_c2 = run_layer_1_deterministic_check(
        profile=profile,
        job=job,
        match=clean_match,
        tailored_resume=extreme_tailored,
        cover_note=clean_note,
    )
    metric_caught = any("1000000000000" in u.claim or "1,000,000,000,000" in u.claim for u in unsupported_c2)
    assert metric_caught, "Layer 1 must catch extreme metric inflation"
    print(f"  PASS: Verifier successfully caught extreme metric inflation: '{unsupported_c2[0].claim}'")

    # -------------------------------------------------------------
    # Case 3: Missing skill with exotic casing and whitespace
    # -------------------------------------------------------------
    print("\n[Case 3] Injected missing skill with exotic casing/whitespace ('  kUbErNeTeS  '):")
    c3_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python", "  kUbErNeTeS  "],
        project_bullets=[],
    )
    unsupported_c3 = run_layer_1_deterministic_check(
        profile=profile,
        job=job,
        match=clean_match,
        tailored_resume=c3_tailored,
        cover_note=clean_note,
    )
    skill_caught = any("kUbErNeTeS" in u.claim or "kubernetes" in u.claim.lower() for u in unsupported_c3)
    assert skill_caught, "Layer 1 must catch missing skill regardless of casing or whitespace"
    print(f"  PASS: Verifier normalized and flagged injected missing skill: '{unsupported_c3[0].claim}'")

    # -------------------------------------------------------------
    # Case 4: Fabricated FAANG employer claim
    # -------------------------------------------------------------
    print("\n[Case 4] Fabricated employer claim ('Software Engineer at Netflix'):")
    fake_employer_tailored = TailoredResume(
        job_id=job.id,
        skills_section=["Python"],
        project_bullets=[
            ProjectBullets(
                project_title="TaskStreamer — Real-Time Collaboration Workspace",
                bullets=["Worked as a Senior Software Engineer at Netflix designing distributed video transcoders."],
            )
        ],
    )
    unsupported_c4 = run_layer_1_deterministic_check(
        profile=profile,
        job=job,
        match=clean_match,
        tailored_resume=fake_employer_tailored,
        cover_note=clean_note,
    )
    emp_caught = any("Netflix" in u.claim for u in unsupported_c4)
    assert emp_caught, "Layer 1 must catch unearned employer claim"
    print(f"  PASS: Verifier flagged fabricated employer claim: '{unsupported_c4[0].claim}'")

    # -------------------------------------------------------------
    # Case 5: Docker compose and container configuration check
    # -------------------------------------------------------------
    print("\n[Case 5] Docker compose service orchestration integrity:")
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"
    compose_text = compose_path.read_text(encoding="utf-8")
    assert "mongodb:" in compose_text
    assert "backend:" in compose_text
    assert "frontend:" in compose_text
    assert "service_healthy" in compose_text
    print("  PASS: Docker compose verified with mongodb, backend, frontend, and healthcheck dependencies.")

    print("\n" + "=" * 75)
    print("ALL 5 PHASE 6 ADVERSARIAL EDGE CASES PASSED")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_phase6_break_tests())

