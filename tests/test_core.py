import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_corpus import classify
from build_dashboard import graph_data, wiki_data
from init_topic import build_queries, parse_years, slugify
from paper_graph import Candidate, relevance


CONFIG = {
    "topic": "AI theorem proving",
    "goal": "Track proof systems",
    "audience": "researchers",
    "include": ["proof search", "formal verification"],
    "exclude": ["math tutoring"],
    "years": {"from": 2023, "to": 2026},
    "evidence_types": ["methods", "benchmarks"],
    "taxonomy": ["proof search", "verification", "benchmarks"],
}


class CoreTests(unittest.TestCase):
    def test_topic_helpers(self):
        self.assertEqual(slugify("AI for Theorem Proving!"), "ai-for-theorem-proving")
        self.assertEqual(parse_years("2023-2026"), {"from": 2023, "to": 2026})
        self.assertIn("AI theorem proving proof search", build_queries(CONFIG["topic"], CONFIG["include"], CONFIG["evidence_types"]))

    def test_relevance_respects_include_and_exclude(self):
        candidate = Candidate(
            "openalex:1", "Formal proof search", 2025, "https://example.com", None,
            "Formal verification with proof search.", 10, [], ["query"]
        )
        score, reason = relevance(candidate, CONFIG)
        self.assertGreater(score, 0)
        self.assertIn("proof search", reason)

    def test_classification_graph_and_wiki(self):
        papers = [
            {
                "id": "openalex:a", "title": "Proof Search A", "abstract": "proof search benchmark",
                "topics": [], "primary_category": "unclassified", "url": "https://a", "year": 2025,
            },
            {
                "id": "openalex:b", "title": "Proof Search B", "abstract": "proof search method",
                "topics": [], "primary_category": "unclassified", "url": "https://b", "year": 2026,
            },
        ]
        for paper in papers:
            paper["primary_category"] = classify(paper, CONFIG)
        graph = graph_data(papers)
        wiki = wiki_data(CONFIG, papers, graph)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertGreaterEqual(wiki["page_count"], 6)
        self.assertIn("overview", {page["id"] for page in wiki["pages"]})

    def test_noninteractive_initialization_generates_agent_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, TOPIC_SCOUT_ROOT=directory)
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "init_topic.py"),
                    "--topic", "AI theorem proving",
                    "--goal", "Track verified proof systems",
                    "--audience", "research engineers",
                    "--include", "proof search,formal verification",
                    "--exclude", "math tutoring",
                    "--years", "2023-2026",
                    "--taxonomy", "proof search,verification,benchmarks",
                ],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            root = Path(directory)
            self.assertTrue((root / "topic.json").exists())
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertTrue((root / "agents" / "graph-scout.md").exists())
            self.assertTrue((root / "skills" / "topic-paper-scout" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
