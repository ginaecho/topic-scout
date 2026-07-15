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
from build_dashboard import DEFAULT_THEME, graph_data, resolve_theme, root_css, wiki_data
from costs import usage_cost, zero_cost
from judging import DEFAULT_JUDGING, aggregate, recency_weight, resolve_judging
from eval_metric import (
    evaluate as eval_metrics,
    precision_at_k,
    roc_auc,
    routing_analysis,
    spearman,
)
from init_topic import build_queries, parse_years, slugify
from intent_refiner import refine_intent, refine_intent_codex
from paper_graph import Candidate, relevance
import scout as scout_module
from scout import select_for_llm
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

    def test_prefilter_gate_splits_pool_and_dropped(self):
        config = {"topic": "proof search", "include": ["proof search"], "exclude": []}
        # `current` recomputes the heuristic from text, so on-topic abstracts
        # score > 0 and off-topic ones score 0.
        cands = [
            {"id": "a", "title": "Proof search A", "abstract": "formal proof search method", "topics": []},
            {"id": "b", "title": "Proof search B", "abstract": "proof search benchmark", "topics": []},
            {"id": "c", "title": "Cooking", "abstract": "bread recipe", "topics": []},
            {"id": "d", "title": "Gardening", "abstract": "plant tomatoes", "topics": []},
        ]
        prefilter = {"enabled": True, "scorer": "current", "threshold": 0.0, "keep_min": 1}
        pool, dropped, _ = select_for_llm(cands, config, prefilter, limit=10)
        self.assertEqual({c["id"] for c in pool}, {"a", "b"})
        self.assertEqual({c["id"] for c in dropped}, {"c", "d"})
        # Disabled gate sends everything (up to the limit), nothing dropped.
        off = select_for_llm(cands, config, {"enabled": False}, limit=10)
        self.assertEqual(len(off[0]), 4)
        self.assertEqual(off[1], [])

    def test_scout_prefilter_reduces_llm_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            papers_path = root / "data" / "papers.json"
            candidates_path = root / "data" / "candidates.json"
            papers_path.write_text(json.dumps({"papers": [], "scout_runs": []}), encoding="utf-8")
            candidates_path.write_text(json.dumps({"candidates": []}), encoding="utf-8")
            fake_topic = {
                "topic": "AI theorem proving", "goal": "g", "audience": "a",
                "include": ["proof search"], "exclude": [], "years": {"from": 2023, "to": 2026},
                "taxonomy": ["proof search"], "evidence_types": ["methods"],
                "approval_required": False, "scout_provider": "api",
            }
            # 6 on-topic (heuristic > 0) + 6 off-topic (heuristic 0); keep_min=5 so
            # the 6 survivors clear the floor and the 6 zeros are truly dropped.
            cands = []
            for i in range(6):
                cands.append({"id": f"y{i}", "title": "Proof search", "year": 2025,
                              "url": "u", "doi": None, "abstract": "proof search method",
                              "citation_count": 3, "topics": ["proof search"],
                              "discovered_via": ["q"], "relevance_score": 2.6,
                              "relevance_reason": "heuristic"})
            for i in range(6):
                cands.append({"id": f"n{i}", "title": "Cooking", "year": 2020,
                              "url": "u", "doi": None, "abstract": "bread recipe",
                              "citation_count": 0, "topics": [], "discovered_via": ["q"],
                              "relevance_score": 0.0, "relevance_reason": "heuristic"})
            fake_result = {"topic": "AI theorem proving", "queries": ["q"], "edges": [], "candidates": cands}
            seen = {}

            def fake_score(config, candidates, **kwargs):
                seen["ids"] = [c["id"] for c in candidates]
                return ({c["id"]: {"topical_fit": 0.9, "evidence_match": 0.9, "rigor": 0.8,
                                   "exclusion_hit": False, "relevance_reason": "fit"}
                         for c in candidates}, zero_cost())

            def fake_load_json(path, default):
                return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

            def fake_write_json(path, payload):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

            with patch.object(scout_module, "discover", return_value=fake_result):
                with patch.object(scout_module, "load_topic", return_value=fake_topic):
                    with patch.object(scout_module, "score_candidates", side_effect=fake_score):
                        with patch.object(scout_module, "load_json", side_effect=fake_load_json):
                            with patch.object(scout_module, "write_json", side_effect=fake_write_json):
                                with patch.object(scout_module, "PAPERS_PATH", papers_path):
                                    with patch.object(scout_module, "CANDIDATES_PATH", candidates_path):
                                        with patch.object(sys, "argv", ["scout.py"]):
                                            self.assertEqual(scout_module.main(), 0)

            # The LLM only saw the 6 on-topic candidates; the 6 zeros were prefiltered.
            self.assertEqual(sorted(seen["ids"]), sorted(f"y{i}" for i in range(6)))
            queue = json.loads(candidates_path.read_text())
            verdicts = {c["id"]: c.get("relevance_verdict") for c in queue["candidates"]}
            self.assertTrue(all(verdicts[f"n{i}"] == "prefiltered" for i in range(6)))
            # The judged on-topic candidates carry a real verdict, not "prefiltered".
            self.assertTrue(all(verdicts[f"y{i}"] in {"accept", "uncertain", "reject"} for i in range(6)))
            self.assertEqual(json.loads(papers_path.read_text())["scout_runs"][0]["prefiltered_count"], 6)

    def test_eval_metric_rank_statistics(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        # Positives ranked strictly above negatives -> AUC 1.0; reversed -> 0.0.
        self.assertAlmostEqual(roc_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]), 1.0)
        self.assertAlmostEqual(roc_auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]), 0.0)
        self.assertAlmostEqual(precision_at_k([0.9, 0.8, 0.1], [1, 1, 0], 2), 1.0)

    def test_eval_metric_routing_retains_recall_and_saves_calls(self):
        config = {"topic": "proof search", "include": ["proof search"], "exclude": []}
        papers = [
            {"id": "a", "title": "Proof search method", "abstract": "formal proof search",
             "topics": [], "citation_count": 5, "year": 2025, "relevance_score": 9.0},
            {"id": "b", "title": "Neural proof search", "abstract": "proof search benchmark",
             "topics": [], "citation_count": 2, "year": 2024, "relevance_score": 8.0},
        ] + [
            {"id": f"n{i}", "title": "Cooking recipe", "abstract": "how to bake bread",
             "topics": [], "citation_count": 0, "year": 2020, "relevance_score": 0.0}
            for i in range(8)
        ]
        route = routing_analysis(papers, config, "current")
        # All 8 off-topic papers auto-dropped; both relevant papers survive to the LLM.
        self.assertEqual(route["auto_dropped"], 8)
        self.assertEqual(route["llm_calls"], 2)
        self.assertEqual(route["recall_retained"], 1.0)
        self.assertGreater(route["token_saving"], 0.5)

    def test_eval_metric_evaluate_covers_all_scorers(self):
        config = {"topic": "proof search", "include": ["proof search"], "exclude": [],
                  "search_queries": ["proof search benchmark"], "taxonomy": ["benchmarks"]}
        papers = [
            {"id": "a", "title": "Proof search", "abstract": "formal proof search method",
             "topics": ["proof"], "citation_count": 5, "year": 2025, "relevance_score": 9.0},
            {"id": "n", "title": "Cooking", "abstract": "bread recipe",
             "topics": [], "citation_count": 0, "year": 2020, "relevance_score": 0.0},
        ]
        summary = eval_metrics(papers, config)
        self.assertEqual(summary["n"], 2)
        for name in ("current", "tfidf_cosine", "bm25", "hybrid"):
            self.assertIn(name, summary["metrics"])
            self.assertIn("auc", summary["metrics"][name])
        self.assertEqual(summary["routing"]["recall_retained"], 1.0)

    def test_resolve_judging_merges_and_normalizes_weights(self):
        judging = resolve_judging({"judging": {"weights": {"topical_fit": 1.0}}})
        # Weights always normalize to sum 1 after merging over defaults.
        self.assertAlmostEqual(sum(judging["weights"].values()), 1.0)
        self.assertGreater(judging["weights"]["topical_fit"], judging["weights"]["evidence_match"])
        # Empty/absent block reproduces the defaults.
        self.assertEqual(resolve_judging({})["weights"], resolve_judging({"judging": {}})["weights"])
        # A malformed (all-zero) weight set falls back to defaults.
        fallback = resolve_judging({"judging": {"weights": {"topical_fit": 0, "evidence_match": 0, "rigor": 0}}})
        self.assertAlmostEqual(fallback["weights"]["topical_fit"], DEFAULT_JUDGING["weights"]["topical_fit"])
        # A CLI accept-score override wins and keeps the band coherent.
        overridden = resolve_judging({"judging": {"accept_lo": 9.0}}, accept_hi=6.0)
        self.assertEqual(overridden["accept_hi"], 6.0)
        self.assertLessEqual(overridden["accept_lo"], overridden["accept_hi"])

    def test_recency_weight_decays_gently_to_a_floor(self):
        recency = DEFAULT_JUDGING["recency"]
        self.assertEqual(recency_weight(2026, 2026, recency), 1.0)
        self.assertAlmostEqual(recency_weight(2021, 2026, recency), 0.85)
        # Far-past papers clamp at the floor; missing years get the neutral value.
        self.assertEqual(recency_weight(1990, 2026, recency), recency["floor"])
        self.assertEqual(recency_weight(None, 2026, recency), recency["unknown_year"])

    def test_aggregate_produces_accept_reject_uncertain_and_veto(self):
        judging = resolve_judging({})
        # Strong rubric + agreeing heuristic -> accept.
        strong = aggregate(
            {"topical_fit": 1.0, "evidence_match": 1.0, "rigor": 1.0, "exclusion_hit": False},
            judging, year=2026, reference_year=2026, heuristic_score=6.0,
        )
        self.assertEqual(strong["relevance_score"], 10.0)
        self.assertEqual(strong["relevance_verdict"], "accept")
        # High rubric but the cheap heuristic strongly disagrees -> uncertain.
        disputed = aggregate(
            {"topical_fit": 0.9, "evidence_match": 0.9, "rigor": 0.9, "exclusion_hit": False},
            judging, year=2026, reference_year=2026, heuristic_score=0.0,
        )
        self.assertLess(disputed["relevance_confidence"], judging["min_confidence"])
        self.assertEqual(disputed["relevance_verdict"], "uncertain")
        # Low rubric -> reject.
        weak = aggregate(
            {"topical_fit": 0.2, "evidence_match": 0.2, "rigor": 0.2, "exclusion_hit": False},
            judging, year=2026, reference_year=2026, heuristic_score=1.2,
        )
        self.assertEqual(weak["relevance_verdict"], "reject")
        # Excluded scope is a hard veto regardless of the other scores.
        vetoed = aggregate(
            {"topical_fit": 1.0, "evidence_match": 1.0, "rigor": 1.0, "exclusion_hit": True},
            judging, year=2026, reference_year=2026, heuristic_score=6.0,
        )
        self.assertEqual(vetoed["relevance_verdict"], "reject")
        self.assertEqual(vetoed["relevance_score"], 0.0)

    def test_scout_uses_rubric_verdict_band_for_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            papers_path = root / "data" / "papers.json"
            candidates_path = root / "data" / "candidates.json"
            papers_path.write_text(json.dumps({"papers": [], "scout_runs": []}), encoding="utf-8")
            candidates_path.write_text(json.dumps({"candidates": []}), encoding="utf-8")

            fake_topic = {
                "topic": "AI theorem proving",
                "goal": "Track proof systems",
                "audience": "researchers",
                "include": ["proof search"],
                "exclude": [],
                "years": {"from": 2023, "to": 2026},
                "taxonomy": ["proof search", "verification"],
                "evidence_types": ["methods"],
                "approval_required": False,
                "scout_provider": "api",
            }
            fake_result = {
                "topic": "AI theorem proving",
                "queries": ["q"],
                "edges": [],
                "candidates": [
                    {  # heuristic agrees with a strong rubric -> accept
                        "id": "openalex:1", "title": "Accept Me", "year": 2025,
                        "url": "https://a", "doi": None, "abstract": "proof search method",
                        "citation_count": 12, "topics": ["proof search"],
                        "discovered_via": ["query:q"], "relevance_score": 6.0,
                        "relevance_reason": "heuristic",
                    },
                    {  # strong rubric but heuristic disagrees -> uncertain, not accepted
                        "id": "openalex:2", "title": "Unsure Me", "year": 2025,
                        "url": "https://b", "doi": None, "abstract": "proof search benchmark",
                        "citation_count": 3, "topics": ["proof search"],
                        "discovered_via": ["query:q"], "relevance_score": 0.0,
                        "relevance_reason": "heuristic",
                    },
                ],
            }
            rubrics = {
                "openalex:1": {"topical_fit": 1.0, "evidence_match": 1.0, "rigor": 0.9,
                               "exclusion_hit": False, "relevance_reason": "clear fit"},
                "openalex:2": {"topical_fit": 0.9, "evidence_match": 0.9, "rigor": 0.9,
                               "exclusion_hit": False, "relevance_reason": "looks aligned"},
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
                    with patch.object(scout_module, "score_candidates", return_value=(rubrics, zero_cost())):
                        with patch.object(scout_module, "load_json", side_effect=fake_load_json):
                            with patch.object(scout_module, "write_json", side_effect=fake_write_json):
                                with patch.object(scout_module, "PAPERS_PATH", papers_path):
                                    with patch.object(scout_module, "CANDIDATES_PATH", candidates_path):
                                        with patch.object(sys, "argv", ["scout.py"]):
                                            self.assertEqual(scout_module.main(), 0)

            corpus = json.loads(papers_path.read_text())
            queue = json.loads(candidates_path.read_text())
            verdicts = {c["id"]: c["relevance_verdict"] for c in queue["candidates"]}
            # Only the agreed-strong candidate is auto-accepted.
            self.assertEqual([p["id"] for p in corpus["papers"]], ["openalex:1"])
            self.assertEqual(verdicts["openalex:1"], "accept")
            self.assertEqual(verdicts["openalex:2"], "uncertain")
            # The judge's rubric is preserved on the candidate for auditing.
            by_id = {c["id"]: c for c in queue["candidates"]}
            self.assertIn("rubric", by_id["openalex:2"])
            self.assertEqual(by_id["openalex:1"]["relevance_reason"], "clear fit")

    def test_resolve_theme_merges_partial_override_over_defaults(self):
        theme = resolve_theme(
            {
                "theme": {
                    "palette": {"accent": "#ff2e88"},
                    "fonts": {"body": "Inter, sans-serif"},
                    "category_colors": ["#ff2e88", "#22d3ee"],
                }
            }
        )
        # Overridden values win.
        self.assertEqual(theme["palette"]["accent"], "#ff2e88")
        self.assertEqual(theme["fonts"]["body"], "Inter, sans-serif")
        self.assertEqual(theme["category_colors"], ["#ff2e88", "#22d3ee"])
        # Unspecified values fall back to the defaults.
        self.assertEqual(theme["palette"]["ink"], DEFAULT_THEME["palette"]["ink"])
        self.assertEqual(theme["fonts"]["display"], DEFAULT_THEME["fonts"]["display"])

    def test_resolve_theme_defaults_when_absent_or_malformed(self):
        self.assertEqual(resolve_theme({}), resolve_theme({"theme": {}}))
        # A malformed category_colors value silently falls back.
        theme = resolve_theme({"theme": {"category_colors": "not-a-list"}})
        self.assertEqual(theme["category_colors"], DEFAULT_THEME["category_colors"])
        root = root_css(theme)
        self.assertTrue(root.startswith(":root{"))
        self.assertIn("--accent:", root)
        self.assertIn("--font-display:", root)

    def test_dashboard_applies_theme_palette_and_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir(parents=True, exist_ok=True)
            (root / "reports").mkdir(parents=True, exist_ok=True)
            (root / "topic.json").write_text(
                json.dumps(
                    {
                        "topic": "Themed Topic",
                        "goal": "Verify theming",
                        "audience": "devs",
                        "taxonomy": ["alpha", "beta"],
                        "include": ["x"],
                        "exclude": [],
                        "years": {"from": 2023, "to": 2026},
                        "theme": {
                            "palette": {"ink": "#0b1021", "accent": "#ff2e88"},
                            "fonts": {"body": "Inter, system-ui, sans-serif"},
                            "category_colors": ["#ff2e88", "#22d3ee"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "data" / "papers.json").write_text(
                json.dumps({"papers": [], "scout_runs": []}), encoding="utf-8"
            )
            (root / "data" / "candidates.json").write_text(
                json.dumps({"candidates": [], "generated_at": None, "cost": {}}),
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
            html = (root / "topic-dashboard.html").read_text(encoding="utf-8")
            self.assertIn("--ink:#0b1021", html)
            self.assertIn("--accent:#ff2e88", html)
            self.assertIn("--font-body:Inter, system-ui, sans-serif", html)
            # Unspecified palette entries keep their defaults.
            self.assertIn(f"--muted:{DEFAULT_THEME['palette']['muted']}", html)
            # Category colors flow into the embedded payload.
            payload = json.loads((root / "data" / "dashboard.json").read_text())
            self.assertEqual(payload["categories"][0]["color"], "#ff2e88")
            self.assertEqual(payload["categories"][1]["color"], "#22d3ee")

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
                                            "topical_fit": 0.9,
                                            "evidence_match": 0.8,
                                            "rigor": 0.7,
                                            "exclusion_hit": False,
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
        self.assertEqual(scores["openalex:1"]["topical_fit"], 0.9)
        self.assertEqual(scores["openalex:1"]["evidence_match"], 0.8)
        self.assertFalse(scores["openalex:1"]["exclusion_hit"])
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
                                "topical_fit": 0.8,
                                "evidence_match": 0.7,
                                "rigor": 0.6,
                                "exclusion_hit": False,
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
        self.assertEqual(scores["openalex:1"]["topical_fit"], 0.8)
        self.assertEqual(scores["openalex:1"]["rigor"], 0.6)
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
