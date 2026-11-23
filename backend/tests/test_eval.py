"""Unit tests for evaluation runners (eval_matcher and eval_verifier)."""

import pytest

from backend.eval.eval_matcher import evaluate_matcher, map_score_to_category
from backend.eval.eval_verifier import evaluate_verifier, PerturbationEngine
from backend.eval.run_eval import build_markdown_report
from backend.models.draft import TailoredResume, CoverNote
from backend.models.job import Job
from backend.models.match import Match
from scripts.real_similarity_check import get_synthetic_profile


def test_map_score_to_category_thresholds():
    """Verify continuous score mapping to discrete fit categories."""
    assert map_score_to_category(85) == "strong"
    assert map_score_to_category(70) == "strong"
    assert map_score_to_category(69) == "medium"
    assert map_score_to_category(40) == "medium"
    assert map_score_to_category(39) == "weak"
    assert map_score_to_category(10) == "weak"


from chromadb.api.types import EmbeddingFunction


class MockEmbeddingFunction(EmbeddingFunction):
    """Deterministic mock embedding function returning 384-dim normalized zero vectors."""

    def name(self) -> str:
        return "mock_embedding"

    def __call__(self, input):
        return [[0.1] * 384 for _ in input]


@pytest.mark.asyncio
async def test_matcher_evaluation_harness(tmp_path, monkeypatch):
    """Verify matcher evaluation runs across benchmark dataset and reports valid metrics."""
    from unittest.mock import AsyncMock
    fake_client = AsyncMock()
    fake_client.generate_json.return_value = {"reasoning": "Candidate shows relevant background."}
    monkeypatch.setattr("backend.agents.matching_agent.get_llm_client", lambda: fake_client)

    temp_dir = str(tmp_path / "chroma_eval_test")
    report = await evaluate_matcher(
        chroma_dir=temp_dir,
        embedding_fn=MockEmbeddingFunction(),
    )

    assert "accuracy" in report
    assert "spearman_rho" in report
    assert report["total_evaluated"] >= 3
    assert 0.0 <= report["accuracy"] <= 1.0
    assert -1.0 <= report["spearman_rho"] <= 1.0
    assert len(report["results"]) == report["total_evaluated"]


@pytest.mark.asyncio
async def test_verifier_evaluation_adversarial_catch_rate():
    """Verify comprehensive 2-layer verifier evaluation benchmark."""
    report = await evaluate_verifier()

    assert report["adversarial_cases_tested"] == 36
    assert report["clean_controls_tested"] == 20
    assert report["layer_1_adversarial_caught"] >= 25
    assert report["clean_controls_passed"] == 20
    assert report["false_positive_rate"] == 0.0
    assert report["layer_1_catch_rate"] >= 0.65


def test_build_markdown_report_formatting():
    """Verify automated report builder produces valid structured markdown."""
    fake_matcher = {
        "accuracy": 1.0,
        "spearman_rho": 0.9404,
        "p_value": 0.0052,
        "total_evaluated": 6,
        "correct_predictions": 6,
        "results": [
            {
                "filename": "sample_01.txt",
                "company": "Acme AI",
                "title": "ML Intern",
                "expected_label": "medium",
                "predicted_category": "medium",
                "score": 55,
                "cap_reasons": [],
                "correct": True,
            }
        ],
    }
    fake_verifier = {
        "total_test_cases": 8,
        "adversarial_cases_tested": 7,
        "adversarial_cases_caught": 7,
        "clean_drafts_tested": 1,
        "false_positive_rate": 0.0,
        "catch_rate": 1.0,
        "layer_1_catches": 7,
        "layer_2_catches": 0,
        "results": [
            {
                "id": "TC_CLEAN_01",
                "description": "Clean baseline draft",
                "expected_pass": True,
                "actual_pass": True,
                "caught_by": "clean",
                "correct": True,
            }
        ],
    }

    report_md = build_markdown_report(fake_matcher, fake_verifier)
    assert "# Job-Search Copilot — Automated Evaluation Report" in report_md
    assert "Spearman Rank Correlation" in report_md
    assert "Adversarial Injections Caught" in report_md
    assert "| `TC_CLEAN_01` |" in report_md

