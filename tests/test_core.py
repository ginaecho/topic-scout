import sys
import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_corpus import classify
from build_dashboard import graph_data, wiki_data
from costs import usage_cost, zero_cost
from init_topic import build_queries, parse_years, slugify
from intent_refiner import refine_intent, refine_intent_codex
from paper_graph import Candidate, relevance
import scout as scout_module
import analyze_research_gaps as gaps_module
import orchestrate as orchestrate_module
from scout_llm import score_candidates_api, score_candidates_codex


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
                    "--offline",
                ],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            root = Path(directory)
            self.assertTrue((root / "topic.json").exists())
            self.assertTrue((root / "TOPIC_AGENTS.md").exists())
            self.assertTrue((root / "agents" / "graph-scout.md").exists())
            self.assertTrue((root / "skills" / "topic-paper-scout" / "SKILL.md").exists())
            topic = json.loads((root / "topic.json").read_text())
            self.assertEqual(topic["raw_intent"], "AI theorem proving")
            self.assertIn("dashboard_sections", topic)

    def test_orchestrate_emits_cross_agent_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(orchestrate_module, "ROOT", root):
                with patch.object(orchestrate_module, "DATA_DIR", root / "data"):
                    for mode in ["claw", "swarm", "copilot", "copilot-cli", "microsoft-scouting"]:
                        payload = orchestrate_module.emit(mode, CONFIG)
                        manifest_path = root / orchestrate_module.MODE_PROFILES[mode]["manifest"]
                        self.assertTrue(manifest_path.exists())
                        self.assertEqual(payload["mode"], mode)
                        self.assertIn("runtime", payload)
                        self.assertIn("topic_contract", payload)
                        self.assertIn("commands", payload)
                        self.assertEqual(payload["topic_contract"]["include"], CONFIG["include"])
                        self.assertEqual(payload["tasks"][0]["contract_files"], ["AGENTS.md", "TOPIC_AGENTS.md", "topic.json"])
                        self.assertEqual(payload["tasks"][0]["agent_brief"], "agents/query-designer.md")

    def test_intent_refinement_uses_structured_responses_output(self):
        refined = {
            "title": "Business-Aligned Evaluation of AI Agents",
            "research_question": "How should AI agent answers be evaluated against business, policy, and system requirements?",
            "goal": "Guide evaluation design",
            "audience": "researchers",
            "include": ["answer quality", "business utility"],
            "exclude": [],
            "evidence_types": ["methods", "benchmarks"],
            "taxonomy": ["metrics", "governance", "agent systems"],
            "dashboard_sections": ["scorecards", "policy coverage", "system design"],
            "search_queries": ["query one", "query two", "query three", "query four", "query five"],
            "scouting_strategy": ["Search evaluation benchmarks", "Expand citation graphs", "Test policy terminology"],
        }
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(refined)}],
                }
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response_body).encode()

        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse()

        result, model = refine_intent(
            "raw sentence",
            provider="api",
            api_key="test-key",
            model="test-model",
            urlopen=fake_urlopen,
        )
        self.assertEqual(result["title"], refined["title"])
        self.assertEqual(model, "test-model")
        self.assertEqual(captured["payload"]["text"]["format"]["type"], "json_schema")
        self.assertFalse(captured["payload"]["store"])

    def test_cost_block_defaults_to_zero_for_openalex_scouting(self):
        cost = zero_cost()
        self.assertEqual(cost["token_count"], 0)
        self.assertEqual(cost["money_cost_usd"], 0.0)
        self.assertEqual(cost["currency"], "USD")

    def test_usage_cost_sums_input_output_and_reasoning(self):
        cost = usage_cost(
            provider="codex",
            model="codex-cli:test",
            input_tokens=100,
            output_tokens=25,
            reasoning_tokens=5,
        )
        self.assertEqual(cost["token_count"], 130)
        self.assertEqual(cost["input_tokens"], 100)
        self.assertEqual(cost["output_tokens"], 25)
        self.assertEqual(cost["reasoning_tokens"], 5)

    def test_dashboard_payload_includes_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "reports").mkdir(parents=True, exist_ok=True)
            (root / "topic.json").write_text(
                json.dumps(
                    {
                        "topic": "Detecting Discriminatory AI in Hiring",
                        "goal": "Track bias detection methods",
                        "audience": "researchers",
                        "taxonomy": ["methods", "systems"],
                        "include": ["hiring", "fairness"],
                        "exclude": [],
                        "years": {"from": 2023, "to": 2026},
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "papers.json").write_text(
                json.dumps({"papers": [], "scout_runs": []}),
                encoding="utf-8",
            )
            (root / "data" / "candidates.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-13T00:00:00Z",
                        "cost": {"token_count": 12, "money_cost_usd": 0.03, "currency": "USD"},
                        "queries": ["query"],
                        "candidates": [
                            {
                                "id": "openalex:1",
                                "title": "Candidate One",
                                "year": 2025,
                                "url": "https://example.com",
                                "citation_count": 4,
                                "relevance_score": 1.5,
                                "relevance_reason": "example",
                                "topics": ["fairness"],
                                "discovered_via": ["query:test"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = dict(os.environ, TOPIC_SCOUT_ROOT=directory)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_dashboard.py")],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            payload = json.loads((root / "data" / "dashboard.json").read_text())
            self.assertEqual(payload["candidate_count"], 1)
            self.assertEqual(payload["candidate_cost"]["token_count"], 12)
            self.assertEqual(payload["candidates"][0]["title"], "Candidate One")
            self.assertTrue(any(page["type"] == "candidate" for page in payload["wiki"]["pages"]))

    def test_dashboard_uses_candidates_for_visuals_when_no_papers_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "reports").mkdir(parents=True, exist_ok=True)
            (root / "topic.json").write_text(
                json.dumps(
                    {
                        "topic": "Detecting Discriminatory AI in Hiring",
                        "goal": "Track bias detection methods",
                        "audience": "researchers",
                        "taxonomy": ["methods", "systems"],
                        "include": ["hiring", "fairness"],
                        "exclude": [],
                        "years": {"from": 2023, "to": 2026},
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "papers.json").write_text(
                json.dumps({"papers": [], "scout_runs": []}),
                encoding="utf-8",
            )
            (root / "data" / "candidates.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-06-13T00:00:00Z",
                        "cost": {"token_count": 12, "money_cost_usd": 0.03, "currency": "USD"},
                        "queries": ["query"],
                        "candidates": [
                            {
                                "id": "openalex:1",
                                "title": "Candidate One",
                                "year": 2025,
                                "url": "https://example.com",
                                "citation_count": 4,
                                "relevance_score": 1.5,
                                "relevance_reason": "example",
                                "topics": ["fairness"],
                                "discovered_via": ["query:test"],
                                "abstract": "fairness in hiring systems",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = dict(os.environ, TOPIC_SCOUT_ROOT=directory)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_dashboard.py")],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            payload = json.loads((root / "data" / "dashboard.json").read_text())
            self.assertEqual(payload["visualized_paper_count"], 1)
            self.assertEqual(payload["visualized_source"], "discovered candidates")
            self.assertGreater(len(payload["graph"]["nodes"]), 0)
            self.assertGreater(payload["categories"][0]["count"] + payload["categories"][1]["count"], 0)

    def test_dashboard_records_category_history_for_scout_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "reports").mkdir(parents=True, exist_ok=True)
            (root / "topic.json").write_text(
                json.dumps(
                    {
                        "topic": "Detecting Discriminatory AI in Hiring",
                        "goal": "Track bias detection methods",
                        "audience": "researchers",
                        "taxonomy": ["methods", "systems"],
                        "include": ["hiring", "fairness"],
                        "exclude": [],
                        "years": {"from": 2023, "to": 2026},
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "papers.json").write_text(
                json.dumps(
                    {
                        "papers": [
                            {
                                "id": "openalex:1",
                                "title": "Candidate One",
                                "year": 2025,
                                "url": "https://example.com/1",
                                "citation_count": 4,
                                "abstract": "fairness in hiring systems",
                                "topics": ["fairness"],
                            },
                            {
                                "id": "openalex:2",
                                "title": "Candidate Two",
                                "year": 2025,
                                "url": "https://example.com/2",
                                "citation_count": 2,
                                "abstract": "hiring workflow systems",
                                "topics": ["workflow"],
                            },
                        ],
                        "scout_runs": [
                            {
                                "date": "2026-06-13",
                                "accepted_ids": ["openalex:1", "openalex:2"],
                                "accepted_count": 2,
                                "candidate_count": 10,
                                "cost": {"token_count": 0, "money_cost_usd": 0.0, "currency": "USD"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "candidates.json").write_text(
                json.dumps({"generated_at": "2026-06-13T00:00:00Z", "candidates": []}),
                encoding="utf-8",
            )
            env = dict(os.environ, TOPIC_SCOUT_ROOT=directory)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_dashboard.py")],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            payload = json.loads((root / "data" / "dashboard.json").read_text())
            self.assertEqual(len(payload["runs"]), 1)
            self.assertIn("accepted_topic_counts", payload["runs"][0])
            self.assertIn("cumulative_topics", payload["runs"][0])
            self.assertIn("cumulative_topic_ratios", payload["runs"][0])
            self.assertEqual(
                sum(payload["runs"][0]["accepted_topic_counts"].values()),
                payload["runs"][0]["accepted"],
            )
            self.assertEqual(
                payload["runs"][0]["cumulative_topics"],
                payload["runs"][0]["accepted_topic_counts"],
            )
            self.assertAlmostEqual(
                sum(payload["runs"][0]["cumulative_topic_ratios"].values()),
                1.0,
            )

    def test_scout_records_history_even_when_nothing_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            papers_path = root / "data" / "papers.json"
            candidates_path = root / "data" / "candidates.json"
            papers_path.write_text(
                json.dumps({"papers": [], "scout_runs": []}),
                encoding="utf-8",
            )
            fake_result = {
                "topic": "AI theorem proving",
                "queries": ["q"],
                "candidates": [
                    {
                        "id": "openalex:1",
                        "title": "Formal proof search",
                        "year": 2025,
                        "url": "https://example.com",
                        "doi": None,
                        "abstract": "Proof search with verifier feedback.",
                        "citation_count": 10,
                        "topics": ["proof search"],
                        "discovered_via": ["query:q"],
                        "relevance_score": 8.0,
                        "relevance_reason": "aligned",
                    }
                ],
                "edges": [],
            }
            fake_topic = {
                "topic": "AI theorem proving",
                "goal": "Track proof systems",
                "audience": "researchers",
                "include": ["proof search", "formal verification"],
                "exclude": [],
                "years": {"from": 2023, "to": 2026},
                "taxonomy": ["proof search", "verification", "benchmarks"],
                "approval_required": True,
            }

            def fake_load_json(path, default):
                if not path.exists():
                    return default
                return json.loads(path.read_text(encoding="utf-8"))

            def fake_write_json(path, payload):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            with patch.object(scout_module, "discover", return_value=fake_result):
                with patch.object(scout_module, "load_topic", return_value=fake_topic):
                    with patch.object(scout_module, "load_json", side_effect=fake_load_json):
                        with patch.object(scout_module, "write_json", side_effect=fake_write_json):
                            with patch.object(scout_module, "PAPERS_PATH", papers_path):
                                with patch.object(scout_module, "CANDIDATES_PATH", candidates_path):
                                    with patch.object(sys, "argv", ["scout.py", "--offline"]):
                                        self.assertEqual(scout_module.main(), 0)

            corpus = json.loads(papers_path.read_text())
            self.assertEqual(len(corpus["scout_runs"]), 1)
            self.assertEqual(corpus["scout_runs"][0]["accepted_count"], 0)
            self.assertGreaterEqual(corpus["scout_runs"][0]["candidate_count"], 0)

    def test_scout_auto_accepts_by_default_when_approval_not_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            papers_path = root / "data" / "papers.json"
            candidates_path = root / "data" / "candidates.json"
            papers_path.write_text(
                json.dumps({"papers": [], "scout_runs": []}),
                encoding="utf-8",
            )
            candidates_path.write_text(
                json.dumps({"candidates": []}),
                encoding="utf-8",
            )
            fake_result = {
                "topic": "AI theorem proving",
                "queries": ["q"],
                "candidates": [
                    {
                        "id": "openalex:1",
                        "title": "Formal proof search",
                        "year": 2025,
                        "url": "https://example.com",
                        "doi": None,
                        "abstract": "Proof search with verifier feedback.",
                        "citation_count": 10,
                        "topics": ["proof search"],
                        "discovered_via": ["query:q"],
                        "relevance_score": 8.0,
                        "relevance_reason": "aligned",
                    }
                ],
                "edges": [],
            }
            fake_topic = {
                "topic": "AI theorem proving",
                "goal": "Track proof systems",
                "audience": "researchers",
                "include": ["proof search", "formal verification"],
                "exclude": [],
                "years": {"from": 2023, "to": 2026},
                "taxonomy": ["proof search", "verification", "benchmarks"],
                "approval_required": False,
            }

            def fake_load_json(path, default):
                if not path.exists():
                    return default
                return json.loads(path.read_text(encoding="utf-8"))

            def fake_write_json(path, payload):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            with patch.object(scout_module, "discover", return_value=fake_result):
                with patch.object(scout_module, "load_topic", return_value=fake_topic):
                    with patch.object(scout_module, "load_json", side_effect=fake_load_json):
                        with patch.object(scout_module, "write_json", side_effect=fake_write_json):
                            with patch.object(scout_module, "PAPERS_PATH", papers_path):
                                with patch.object(scout_module, "CANDIDATES_PATH", candidates_path):
                                    with patch.object(sys, "argv", ["scout.py", "--offline"]):
                                        self.assertEqual(scout_module.main(), 0)
            corpus = json.loads(papers_path.read_text())
            self.assertEqual(len(corpus["papers"]), 1)
            self.assertEqual(corpus["scout_runs"][0]["accepted_count"], 1)

    def test_report_includes_scout_usage_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "topic.json").write_text(
                json.dumps(
                    {
                        "topic": "AI theorem proving",
                        "goal": "Track proof systems",
                        "audience": "researchers",
                        "taxonomy": ["proof search", "verification", "benchmarks"],
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "papers.json").write_text(
                json.dumps(
                    {
                        "papers": [],
                        "scout_runs": [
                            {
                                "date": "2026-06-19",
                                "accepted_count": 0,
                                "accepted_ids": [],
                                "candidate_count": 7,
                                "cost": {
                                    "provider": "codex",
                                    "model": "codex-cli:test",
                                    "token_count": 123,
                                    "money_cost_usd": 0.0,
                                    "currency": "USD",
                                    "note": "subscription",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = dict(os.environ, TOPIC_SCOUT_ROOT=directory)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_corpus.py")],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            report = (root / "reports" / "research_report.md").read_text(encoding="utf-8")
            self.assertIn("## Scout Usage", report)
            self.assertIn("**Total scout tokens:** 123", report)
            self.assertIn("via codex (codex-cli:test)", report)

    def test_scout_llm_api_returns_usage(self):
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "candidates": [
                                        {
                                            "id": "openalex:1",
                                            "relevance_score": 8.2,
                                            "relevance_reason": "Matches proof search and verification scope.",
                                        }
                                    ]
                                }
                            ),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "output_tokens_details": {"reasoning_tokens": 4},
            },
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response_body).encode()

        def fake_urlopen(request, timeout):
            return FakeResponse()

        scores, cost = score_candidates_api(
            CONFIG,
            [
                {
                    "id": "openalex:1",
                    "title": "Formal proof search",
                    "abstract": "Proof search with verifier feedback.",
                    "topics": ["proof search"],
                    "relevance_score": 1.0,
                    "relevance_reason": "heuristic",
                }
            ],
            api_key="test-key",
            model="test-model",
            urlopen=fake_urlopen,
        )
        self.assertEqual(scores["openalex:1"]["relevance_score"], 8.2)
        self.assertEqual(cost["token_count"], 154)
        self.assertEqual(cost["model"], "test-model")

    def test_scout_llm_codex_parses_usage(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "id": "openalex:1",
                                "relevance_score": 7.5,
                                "relevance_reason": "Highly aligned with formal verification scope.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    '{"type":"thread.started"}\n'
                    '{"type":"turn.completed","usage":{"input_tokens":210,"output_tokens":18,"reasoning_output_tokens":2}}\n'
                ),
                stderr="",
            )

        with patch("scout_llm.shutil.which", return_value="/usr/local/bin/codex"):
            scores, cost = score_candidates_codex(
                CONFIG,
                [
                    {
                        "id": "openalex:1",
                        "title": "Formal proof search",
                        "abstract": "Proof search with verifier feedback.",
                        "topics": ["proof search"],
                        "relevance_score": 1.0,
                        "relevance_reason": "heuristic",
                    }
                ],
                cwd=ROOT,
                run=fake_run,
            )
        self.assertIn("--json", captured["command"])
        self.assertEqual(scores["openalex:1"]["relevance_score"], 7.5)
        self.assertEqual(cost["token_count"], 230)

    def test_gap_analysis_skips_when_no_accepted_papers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            papers_path = root / "data" / "papers.json"
            opportunities_path = root / "data" / "research_opportunities.json"
            papers_path.write_text(json.dumps({"papers": []}), encoding="utf-8")

            def fake_load_json(path, default):
                if not path.exists():
                    return default
                return json.loads(path.read_text(encoding="utf-8"))

            with patch.object(gaps_module, "load_json", side_effect=fake_load_json):
                with patch.object(gaps_module, "PAPERS_PATH", papers_path):
                    with patch.object(gaps_module, "OPPORTUNITIES_PATH", opportunities_path):
                        with patch.object(sys, "argv", ["analyze_research_gaps.py"]):
                            self.assertEqual(gaps_module.main(), 0)
            self.assertFalse(opportunities_path.exists())

    def test_intent_refinement_can_use_codex_subscription(self):
        refined = {
            "title": "Business-Aligned Evaluation of AI Agents",
            "research_question": "How should AI agent answers be evaluated against business, policy, and system requirements?",
            "goal": "Guide evaluation design",
            "audience": "researchers",
            "include": ["answer quality", "business utility"],
            "exclude": [],
            "evidence_types": ["methods", "benchmarks"],
            "taxonomy": ["metrics", "governance", "agent systems"],
            "dashboard_sections": ["scorecards", "policy coverage", "system design"],
            "search_queries": ["query one", "query two", "query three", "query four", "query five"],
            "scouting_strategy": ["Search evaluation benchmarks", "Expand citation graphs", "Test policy terminology"],
        }
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(refined), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        result, model = refine_intent_codex(
            "raw sentence",
            cwd=ROOT,
            run=fake_run,
            which=lambda _: "codex",
        )
        self.assertEqual(result["title"], refined["title"])
        self.assertEqual(model, "codex-cli:configured-model")
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("--ignore-user-config", captured["command"])
        self.assertIn("--ignore-rules", captured["command"])
        self.assertIn("read-only", captured["command"])
        self.assertIn("--output-schema", captured["command"])


if __name__ == "__main__":
    unittest.main()
