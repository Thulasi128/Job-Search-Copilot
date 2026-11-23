"""Script to run real SentenceTransformer semantic similarity check across test fixtures."""

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_settings
from backend.models.profile import Education, Experience, Preferences, Profile, Project
from backend.vector_store import (
    distance_to_similarity,
    get_embedding_function,
    index_profile_chunks,
    query_profile_chunks,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "backend" / "tests" / "fixtures"


def get_synthetic_profile() -> Profile:
    """Build the canonical Alex Rivera synthetic profile."""
    return Profile(
        id="default_profile",
        name="Alex Rivera",
        email="alex.rivera.fake@example.com",
        phone="(555) 019-2834",
        location="Austin, TX",
        education=[
            Education(
                institution="State University of Technology",
                degree="Bachelor of Science",
                field="Computer Science",
                start_year=2021,
                end_year=2025,
                cgpa=3.85,
            )
        ],
        skills=[
            "Python", "TypeScript", "JavaScript", "SQL", "Go",
            "React", "Node.js", "FastAPI", "Express",
            "Docker", "PostgreSQL", "MongoDB", "Git", "CI/CD", "AWS",
        ],
        projects=[
            Project(
                title="TaskStreamer — Real-Time Collaboration Workspace",
                tech=["React", "Node.js", "MongoDB"],
                bullets=[
                    "Developed an open-source collaboration board supporting concurrent WebSocket editing for over 500 active users.",
                    "Architected scalable MongoDB aggregation pipelines improving dashboard load latency by 35%.",
                    "Implemented automated integration suites in GitHub Actions achieving 92% code coverage.",
                ],
            ),
            Project(
                title="DataPipeline CLI — Distributed Ingestion Framework",
                tech=["Python", "Docker", "PostgreSQL"],
                bullets=[
                    "Built a concurrent event stream processing engine ingesting 100,000 JSON records daily into PostgreSQL.",
                    "Containerized worker microservices with Docker Compose for consistent local development and staging environments.",
                ],
            ),
        ],
        experience=[
            Experience(
                company="TechLabs Solutions",
                role="Software Engineering Intern",
                location="Austin, TX",
                start_date="June 2024",
                end_date="August 2024",
                bullets=[
                    "Engineered 8 production RESTful endpoints using FastAPI and PostgreSQL handling 20,000 daily requests.",
                    "Collaborated in an agile team of 6 engineers, participating in bi-weekly sprints and rigorous code reviews.",
                    "Reduced continuous deployment pipeline cycle time by 20% by introducing parallel test runners.",
                ],
            )
        ],
    )


async def main():
    settings = get_settings()
    temp_dir = tempfile.mkdtemp(prefix="chroma_real_sim_")
    try:
        profile = get_synthetic_profile()
        embedding_fn = get_embedding_function()

        print(f"Loading real embedding model: {settings.EMBEDDING_MODEL}")
        print(f"Indexing synthetic profile '{profile.name}' into Chroma at: {temp_dir}")
        indexed_count = index_profile_chunks(profile, persist_directory=temp_dir, embedding_fn=embedding_fn)
        print(f"Indexed {indexed_count} profile chunks.\n" + "=" * 70)

        fixtures = [
            {
                "name": "CloudWave Systems (Strong Match)",
                "file": "jd_strong_match.txt",
                "required_skills": ["Python", "React", "Docker", "MongoDB"],
            },
            {
                "name": "Vintage Web Media (Conflict Match)",
                "file": "jd_conflict_match.txt",
                "required_skills": [],  # no required skills in JD
            },
            {
                "name": "Quantum Micro-Circuits (Weak Match)",
                "file": "jd_weak_match.txt",
                "required_skills": ["C++", "Verilog", "FPGA", "RTOS", "Assembly"],
            },
        ]

        results = []

        for f in fixtures:
            file_path = FIXTURES_DIR / f["file"]
            jd_text = file_path.read_text(encoding="utf-8")
            req_skills = f["required_skills"]

            if req_skills:
                query_text = f"Required Skills: {', '.join(req_skills)}. Overview: {jd_text[:1000]}"
                query_source = "required_skills_and_summary"
            else:
                query_text = jd_text[:1500]
                query_source = "jd_body_first_1500_chars"

            matched_chunks = await query_profile_chunks(
                query_text=query_text,
                top_k=3,
                persist_directory=temp_dir,
                embedding_fn=embedding_fn,
            )

            raw_scores = [c["raw_similarity"] for c in matched_chunks]
            cal_scores = [c["calibrated_similarity"] for c in matched_chunks]
            raw_avg = sum(raw_scores) / len(raw_scores) if raw_scores else 0.0
            cal_avg = sum(cal_scores) / len(cal_scores) if cal_scores else 0.0

            results.append({
                "name": f["name"],
                "query_source": query_source,
                "query_text": query_text,
                "chunks": matched_chunks,
                "raw_scores": raw_scores,
                "raw_avg": raw_avg,
                "cal_avg": cal_avg,
            })

            print(f"Fixture: {f['name']}")
            print(f"Query Source: {query_source}")
            print(f"Query Text Preview: {query_text[:120]}...")
            print("Top 3 Matched Chunks:")
            for i, c in enumerate(matched_chunks, 1):
                chunk_title = c["metadata"].get("title") or c["metadata"].get("company") or "chunk"
                print(f"  {i}. [{chunk_title}] Raw: {c['raw_similarity']:.4f} | Calibrated: {c['calibrated_similarity']:.4f}")
            print(f"Top 3 Raw Average: {raw_avg:.4f}")
            print(f"Top 3 Calibrated Average: {cal_avg:.4f}")
            print("-" * 70)

        print("\nSummary Comparison:")
        print(f"Strong Raw Avg:   {results[0]['raw_avg']:.4f} -> Calibrated: {results[0]['cal_avg']:.4f}")
        print(f"Conflict Raw Avg: {results[1]['raw_avg']:.4f} -> Calibrated: {results[1]['cal_avg']:.4f}")
        print(f"Weak Raw Avg:     {results[2]['raw_avg']:.4f} -> Calibrated: {results[2]['cal_avg']:.4f}")
        margin = results[0]["raw_avg"] - results[2]["raw_avg"]
        print(f"Strong vs Weak Raw Margin: +{margin:.4f}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
