#!/usr/bin/env python3
"""Build a self-contained dashboard, graph, wiki, and opportunity view."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

from build_corpus import classify
from workspace import (
    DASHBOARD_PATH,
    DATA_DIR,
    CANDIDATES_PATH,
    OPPORTUNITIES_PATH,
    PAPERS_PATH,
    load_json,
    load_topic,
    write_json,
)


COLORS = ["#e4572e", "#1d6f75", "#f3a712", "#963484", "#4267ac", "#5b8e3e", "#7b6045"]


def terms(paper: dict) -> set[str]:
    stop = {
        "with", "from", "this", "that", "paper", "using", "based", "study",
        "large", "model", "models", "research", "approach", "method", "system",
    }
    text = " ".join([paper.get("title", ""), paper.get("abstract", ""), *paper.get("topics", [])]).lower()
    return {
        token.strip(".,:;()[]")
        for token in text.split()
        if len(token) >= 5 and token not in stop
    }


def graph_data(papers: list[dict]) -> dict:
    candidates = []
    for index, left in enumerate(papers):
        left_terms = terms(left)
        for right in papers[index + 1 :]:
            shared = sorted(left_terms & terms(right))
            same_category = left["primary_category"] == right["primary_category"]
            score = (1.8 if same_category else 0) + min(len(shared), 8) * 0.32
            if score >= 2.1:
                candidates.append(
                    {
                        "source": left["id"],
                        "target": right["id"],
                        "weight": round(score, 2),
                        "reason": "; ".join(
                            [
                                *(["same category"] if same_category else []),
                                *([f"terms: {', '.join(shared[:3])}"] if shared else []),
                            ]
                        ),
                    }
                )
    per_node: dict[str, list[dict]] = defaultdict(list)
    for edge in candidates:
        per_node[edge["source"]].append(edge)
        per_node[edge["target"]].append(edge)
    selected = {}
    for identifier, edges in per_node.items():
        for edge in sorted(edges, key=lambda item: -item["weight"])[:3]:
            key = tuple(sorted((edge["source"], edge["target"])))
            selected[key] = edge
    edges = sorted(selected.values(), key=lambda item: (item["source"], item["target"]))
    degree = Counter()
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    return {
        "nodes": [
            {
                "id": paper["id"],
                "title": paper["title"],
                "category": paper["primary_category"],
                "url": paper.get("url"),
                "year": paper.get("year"),
                "degree": degree[paper["id"]],
            }
            for paper in papers
        ],
        "edges": edges,
    }


def wiki_data(config: dict, papers: list[dict], graph: dict, candidates: list[dict] | None = None) -> dict:
    nodes = {node["id"]: node for node in graph["nodes"]}
    related: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        related[edge["source"]].append(
            {"id": edge["target"], "title": nodes[edge["target"]]["title"], "reason": edge["reason"]}
        )
        related[edge["target"]].append(
            {"id": edge["source"], "title": nodes[edge["source"]]["title"], "reason": edge["reason"]}
        )
    pages = [
        {
            "id": "overview",
            "type": "overview",
            "title": config["topic"],
            "subtitle": config["goal"],
            "body": (
                f"This living wiki contains {len(papers)} accepted papers for {config['audience']} "
                f"and {len(candidates or [])} candidate papers awaiting review. "
                "Browse category pages, the candidate queue, or follow related-paper trails."
            ),
            "links": [f"category:{category}" for category in config["taxonomy"]],
        }
    ]
    if candidates:
        pages.append(
            {
                "id": "candidate-queue",
                "type": "queue",
                "title": "Candidate Queue",
                "subtitle": f"{len(candidates)} papers awaiting review",
                "body": "Top discovered papers that have not been accepted into the corpus yet.",
                "links": [f"candidate:{paper['id']}" for paper in candidates],
            }
        )
    for category in config["taxonomy"]:
        members = [paper for paper in papers if paper["primary_category"] == category]
        pages.append(
            {
                "id": f"category:{category}",
                "type": "category",
                "title": category.title(),
                "subtitle": f"{len(members)} accepted papers",
                "body": f"Generated category page for {category}.",
                "links": [paper["id"] for paper in members],
            }
        )
    for paper in papers:
        pages.append(
            {
                "id": paper["id"],
                "type": "paper",
                "title": paper["title"],
                "subtitle": f"{paper['primary_category']} · {paper.get('year') or 'year unknown'}",
                "body": paper.get("abstract") or "Abstract unavailable.",
                "source_url": paper.get("url"),
                "assessment": paper.get("notes") or paper.get("relevance_reason"),
                "related": sorted(related[paper["id"]], key=lambda item: item["title"])[:8],
                "links": [f"category:{paper['primary_category']}"],
            }
        )
    for candidate in candidates or []:
        pages.append(
            {
                "id": f"candidate:{candidate['id']}",
                "type": "candidate",
                "title": candidate["title"],
                "subtitle": f"pending review · {candidate.get('year') or 'year unknown'}",
                "body": candidate.get("abstract") or "Abstract unavailable.",
                "source_url": candidate.get("url"),
                "assessment": candidate.get("relevance_reason"),
                "links": ["candidate-queue"],
            }
        )
    return {"pages": pages, "page_count": len(pages)}


def build_data() -> dict:
    config = load_topic()
    corpus = load_json(PAPERS_PATH, {"papers": [], "scout_runs": []})
    candidates_payload = load_json(CANDIDATES_PATH, {"candidates": [], "generated_at": None, "cost": {}})
    papers = corpus["papers"]
    for paper in papers:
        paper["primary_category"] = classify(paper, config)
    categories = [
        {
            "id": category,
            "label": category.title(),
            "count": 0,
            "ratio": 0,
            "color": COLORS[index % len(COLORS)],
        }
        for index, category in enumerate(config["taxonomy"])
    ]
    runs = []
    cumulative = 0
    cumulative_topics = {category["id"]: 0 for category in categories}
    total_tokens = 0
    total_cost = 0.0
    paper_by_id = {paper["id"]: paper for paper in papers}
    for run in corpus.get("scout_runs", []):
        accepted_count = int(run.get("accepted_count", len(run.get("accepted_ids", []))) or 0)
        candidate_count = int(run.get("candidate_count", 0) or 0)
        cumulative += accepted_count
        cost = run.get("cost") or {}
        total_tokens += int(cost.get("token_count", 0) or 0)
        total_cost += float(cost.get("money_cost_usd", 0.0) or 0.0)
        accepted_topic_counts = {category["id"]: 0 for category in categories}
        for identifier in run.get("accepted_ids", []):
            paper = paper_by_id.get(identifier)
            if not paper:
                continue
            accepted_topic_counts[paper["primary_category"]] += 1
        for category_id, count in accepted_topic_counts.items():
            cumulative_topics[category_id] += count
        runs.append(
            {
                **run,
                "accepted": accepted_count,
                "candidate_count": candidate_count,
                "cumulative": cumulative,
                "accepted_topic_counts": accepted_topic_counts,
                "cumulative_topics": dict(cumulative_topics),
                "cumulative_topic_ratios": {
                    category_id: (count / cumulative if cumulative else 0.0)
                    for category_id, count in cumulative_topics.items()
                },
                "token_count": int(cost.get("token_count", 0) or 0),
                "money_cost_usd": float(cost.get("money_cost_usd", 0.0) or 0.0),
                "currency": cost.get("currency", "USD"),
            }
        )
    candidate_rows = sorted(
        candidates_payload.get("candidates", []),
        key=lambda item: (-item.get("relevance_score", 0), -item.get("citation_count", 0), -(item.get("year") or 0)),
    )
    candidate_cost = candidates_payload.get("cost") or {}
    visual_papers = papers if papers else [dict(item) for item in candidate_rows[:60]]
    for paper in visual_papers:
        paper["primary_category"] = classify(paper, config)
    counts = Counter(paper["primary_category"] for paper in visual_papers)
    for category in categories:
        category["count"] = counts[category["id"]]
        category["ratio"] = counts[category["id"]] / len(visual_papers) if visual_papers else 0
    graph = graph_data(visual_papers)
    opportunities = load_json(
        OPPORTUNITIES_PATH,
        {
            "generated_at": None,
            "analysis_model": None,
            "summary": "Run the generated analyze-research-gaps skill after the corpus has evidence.",
            "opportunities": [],
        },
    )
    return {
        "topic": config,
        "paper_count": len(papers),
        "visualized_paper_count": len(visual_papers),
        "visualized_source": "accepted papers" if papers else "discovered candidates",
        "categories": categories,
        "runs": runs,
        "scout_tokens": total_tokens,
        "scout_spend_usd": round(total_cost, 2),
        "candidate_count": len(candidate_rows),
        "candidate_generated_at": candidates_payload.get("generated_at"),
        "candidate_cost": {
            "provider": candidate_cost.get("provider", candidates_payload.get("scout_provider", "unknown")),
            "model": candidate_cost.get("model"),
            "token_count": int(candidate_cost.get("token_count", 0) or 0),
            "input_tokens": int(candidate_cost.get("input_tokens", 0) or 0),
            "output_tokens": int(candidate_cost.get("output_tokens", 0) or 0),
            "reasoning_tokens": int(candidate_cost.get("reasoning_tokens", 0) or 0),
            "money_cost_usd": float(candidate_cost.get("money_cost_usd", 0.0) or 0.0),
            "currency": candidate_cost.get("currency", "USD"),
            "note": candidate_cost.get("note", ""),
        },
        "candidates": candidate_rows[:25],
        "graph": graph,
        "wiki": wiki_data(config, papers or visual_papers, graph, candidate_rows[:25]),
        "opportunities": opportunities,
        "papers": papers,
    }


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · AI Topic Scout</title>
<style>
:root{--ink:#17201f;--paper:#f3efe4;--panel:#fffdf6;--line:#c9c1b1;--muted:#706c63}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Avenir Next","Gill Sans",sans-serif}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.25;background-image:radial-gradient(#817b70 .55px,transparent .55px);background-size:7px 7px}
main{position:relative;width:min(1480px,calc(100% - 30px));margin:auto;padding:34px 0 70px}
header{border-top:8px solid var(--ink);padding-top:18px}.eyebrow{text-transform:uppercase;letter-spacing:.15em;font-size:10px;font-weight:800}
h1{font:700 clamp(42px,7vw,92px)/.9 Georgia,serif;letter-spacing:-.055em;margin:8px 0}.subtitle{max-width:850px;color:var(--muted);font-size:17px}
.metrics{display:grid;grid-template-columns:repeat(7,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:26px 0}.metric{background:var(--panel);padding:17px}.metric b{display:block;font:700 35px Georgia,serif;margin-top:14px}
.grid{display:grid;grid-template-columns:1fr 1.4fr;gap:17px}.panel{background:rgba(255,253,246,.94);border:1px solid var(--line);padding:20px;min-width:0}.wide{grid-column:1/-1}.panel h2{font:700 26px Georgia,serif;margin:5px 0 16px}
.framing{display:grid;grid-template-columns:1.4fr 1fr;gap:24px}.framing ul{columns:2;padding-left:18px}.framing li{margin-bottom:7px}
.barrow{display:grid;grid-template-columns:1fr 2fr 84px;gap:9px;align-items:center;margin:12px 0}.bar{height:12px;background:#ded8ca}.bar i{display:block;height:100%;background:var(--c);width:var(--w)}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin:4px 0 14px;font-size:12px}.legend span::before{content:"";display:inline-block;width:9px;height:9px;margin-right:6px;background:var(--c)}
svg{width:100%;height:auto;overflow:visible}.axis{stroke:#bcb4a4;stroke-width:1}.chart-label{fill:#706c63;font-size:11px}.trend-line{fill:none;stroke-width:3;vector-effect:non-scaling-stroke}.run-dot{stroke:var(--panel);stroke-width:2}
.wiki{padding:0}.wikihead,.graphhead{display:flex;justify-content:space-between;align-items:end;gap:18px;padding:20px;border-bottom:1px solid var(--line)}input,select,button{font:inherit}.wikihead input,.graphhead input,.graphhead select{padding:9px;border:1px solid currentColor;background:transparent}
.wikilayout{display:grid;grid-template-columns:270px 1fr;min-height:620px}.wikinav{background:#eee8dc;border-right:1px solid var(--line);max-height:700px;overflow:auto;padding:10px}.wikinav button{display:block;width:100%;padding:10px 7px;border:0;border-bottom:1px solid #d2cabb;background:transparent;text-align:left;cursor:pointer}.wikinav button.active,.wikinav button:hover{background:var(--panel)}.wikinav small{display:block;color:var(--muted);text-transform:uppercase}
.wikipage{padding:clamp(22px,4vw,54px);max-height:700px;overflow:auto}.wikipage h3{font:700 clamp(30px,5vw,58px)/1 Georgia,serif;margin:7px 0}.wikipage .lede{font:italic 19px Georgia,serif;color:var(--muted)}.links{display:flex;flex-wrap:wrap;gap:7px}.links button,.related button{border:1px solid var(--line);background:#f7f3e9;padding:9px;text-align:left;cursor:pointer}.related{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.related small{display:block;color:var(--muted);margin-top:4px}
.graphpanel{padding:0;background:#17201f;color:#f3efe4}.graphlayout{display:grid;grid-template-columns:minmax(0,1fr) 220px}.stage{position:relative;overflow:hidden;background:radial-gradient(circle,#263330,#111817)}canvas{display:block;width:100%;height:360px;touch-action:none}.detail{padding:16px;border-left:1px solid #44504e}.detail h3{font:700 23px Georgia,serif}.detail p{color:#bac4c1}
.opportunity{display:grid;grid-template-columns:65px 1fr 220px;gap:16px;padding:17px 0;border-bottom:1px solid var(--line)}.rank{font:700 38px Georgia,serif;color:#e4572e}.score{font:700 31px Georgia,serif}.tag{display:inline-block;border:1px solid;padding:3px 6px;font-size:9px;text-transform:uppercase;margin-right:5px}
.candidate{display:grid;grid-template-columns:65px 1fr 220px;gap:16px;padding:17px 0;border-bottom:1px solid var(--line)}.candidate .rank{font:700 38px Georgia,serif;color:#1d6f75}.candidate .meta{font-size:12px;color:var(--muted);margin-top:6px}.candidate h3{margin:0 0 6px;font:700 22px Georgia,serif}.candidate p{margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;border-bottom:1px solid #d9d2c4;text-align:left}a{color:inherit;font-weight:700}
@media(max-width:850px){.grid,.framing{grid-template-columns:1fr}.wide{grid-column:auto}.metrics{grid-template-columns:1fr 1fr}.wikilayout,.graphlayout{grid-template-columns:1fr}.wikinav{max-height:220px;border-right:0;border-bottom:1px solid var(--line)}.detail{border-left:0}.opportunity,.candidate{grid-template-columns:1fr}.related{grid-template-columns:1fr}}
</style></head><body><main>
<header><div class="eyebrow">AI Topic Scout · Living research intelligence</div><h1 id="title"></h1><p class="subtitle" id="goal"></p></header>
<section class="metrics" id="metrics"></section><section class="grid">
<article class="panel wide framing"><div><div class="eyebrow">LLM-refined research contract</div><h2>What this scout evaluates</h2><p id="question"></p><h3>Dashboard structure</h3><ul id="dashboardsections"></ul></div><div><div class="eyebrow">Discovery design</div><h2>Scouting strategy</h2><ul id="scoutingstrategy"></ul></div></article>
<article class="panel"><div class="eyebrow">Corpus distribution</div><h2>Research categories by visualized papers</h2><p id="visualizedsource"></p><div id="categories"></div></article>
<article class="panel"><div class="eyebrow">Scout history</div><h2>Category share over time</h2><p id="trendsource"></p><div class="legend" id="trendlegend"></div><svg id="trend" viewBox="0 0 820 330"></svg></article>
<article class="panel wide"><div class="eyebrow">Candidate queue</div><h2>Discovered papers awaiting review</h2><p id="candidatesummary"></p><div id="candidates"></div></article>
<article class="panel wide wiki" id="wiki"><div class="wikihead"><div><div class="eyebrow">Compiled knowledge base</div><h2>Research Wiki</h2></div><input id="wikisearch" placeholder="Search pages"></div><div class="wikilayout"><nav class="wikinav" id="wikinav"></nav><article class="wikipage" id="wikipage"></article></div></article>
<article class="panel wide graphpanel"><div class="graphhead"><div><div class="eyebrow">Association map</div><h2>Paper Graph</h2></div><div><input id="graphsearch" placeholder="Find a paper"><select id="graphcat"><option value="all">All categories</option></select></div></div><div class="graphlayout"><div class="stage"><canvas id="graph"></canvas></div><aside class="detail" id="detail"></aside></div></article>
<article class="panel wide"><div class="eyebrow">LLM reasoning</div><h2>Underexplored areas & opportunities</h2><p id="oppsummary"></p><div id="opportunities"></div></article>
<article class="panel wide"><div class="eyebrow">Evidence ledger</div><h2>Accepted papers</h2><table><thead><tr><th>Year</th><th>Paper</th><th>Category</th><th>Citations</th></tr></thead><tbody id="papers"></tbody></table></article>
</section></main><script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById("data").textContent), byCat=Object.fromEntries(data.categories.map(x=>[x.id,x]));
title.textContent=data.topic.topic;goal.textContent=data.topic.goal;
question.textContent=data.topic.research_question||data.topic.topic;
dashboardsections.innerHTML=(data.topic.dashboard_sections||data.topic.taxonomy).map(x=>`<li>${x}</li>`).join("");
scoutingstrategy.innerHTML=(data.topic.scouting_strategy||[]).map(x=>`<li>${x}</li>`).join("");
document.getElementById("visualizedsource").textContent=`This section is rendered from ${data.visualized_source}.`;
document.getElementById("trendsource").textContent=data.runs.length ? `Showing category percentage across ${data.runs.length} scout run(s), based on cumulative accepted papers.` : "No scout history yet; run `make scout` to add the first dot.";
metrics.innerHTML=[["Accepted papers",data.paper_count],["Visualized papers",data.visualized_paper_count],["Wiki pages",data.wiki.page_count],["Graph links",data.graph.edges.length],["Scout runs",data.runs.length],["Scout tokens",data.scout_tokens],["Scout spend",`$${data.scout_spend_usd.toFixed(2)}`]].map(x=>`<div class="metric"><span class="eyebrow">${x[0]}</span><b>${x[1]}</b></div>`).join("");
categories.innerHTML=data.categories.map(x=>`<div class="barrow"><span>${x.label}</span><span class="bar"><i style="--c:${x.color};--w:${Math.round(x.ratio*100)}%"></i></span><b>${x.count} (${Math.round(x.ratio*100)}%)</b></div>`).join("");
const candidateSummaryText = data.candidate_count ? `Latest scout found ${data.candidate_count} candidates${data.candidate_generated_at ? ` at ${data.candidate_generated_at}` : ""}. Recorded scout usage: ${data.candidate_cost.token_count} tokens, $${data.candidate_cost.money_cost_usd.toFixed(2)} ${data.candidate_cost.currency} via ${data.candidate_cost.provider}${data.candidate_cost.model ? ` (${data.candidate_cost.model})` : ""}.${data.candidate_cost.note ? ` ${data.candidate_cost.note}` : ""}` : "No candidates recorded yet. Run `make scout` to populate this section.";
document.getElementById("candidatesummary").textContent=candidateSummaryText;
const candidateItems=(data.candidates||[]).map((x,i)=>`<section class="candidate"><div class="rank">${String(i+1).padStart(2,"0")}</div><div><span class="tag">${x.relevance_score.toFixed(1)}</span><span class="tag">${x.citation_count} cites</span><h3><a href="${x.url||"#"}">${x.title}</a></h3><p>${x.year||""}</p><p class="meta">${x.id} · ${x.discovered_via?.[0]||"n/a"}</p><p>${x.relevance_reason||""}</p></div><aside><div class="eyebrow">Review</div><div class="score">${x.relevance_score.toFixed(1)}</div><ul>${(x.topics||[]).slice(0,3).map(t=>`<li>${t}</li>`).join("")}</ul></aside></section>`).join("");
document.getElementById("candidates").innerHTML=candidateItems||"<p>No candidate rows loaded.</p>";
document.getElementById("trendlegend").innerHTML=data.categories.filter(x=>x.count||data.runs.some(r=>(r.cumulative_topics||{})[x.id])).map(x=>`<span style="--c:${x.color}">${x.label}</span>`).join("");
const ts=document.getElementById("trend"),runs=data.runs,W=820,H=330,pad={l:42,r:16,t:12,b:40},visibleTrendCategories=data.categories.filter(x=>x.count||runs.some(r=>(r.cumulative_topic_ratios||{})[x.id])),trendMax=1;let chart=`<line class="axis" x1="${pad.l}" y1="${H-pad.b}" x2="${W-pad.r}" y2="${H-pad.b}"/>`;const tx=i=>pad.l+(runs.length===1?((W-pad.l-pad.r)/2):i*(W-pad.l-pad.r)/Math.max(1,runs.length-1)),ty=v=>H-pad.b-v*(H-pad.t-pad.b)/trendMax,dotOffset=(i,v,catId)=>{const same=visibleTrendCategories.filter(cat=>Math.abs((((runs[i].cumulative_topic_ratios||{})[cat.id]||0)-v))<1e-9);if(same.length<=1)return 0;const idx=same.findIndex(cat=>cat.id===catId);return (idx-(same.length-1)/2)*10;};for(let i=0;i<=4;i++){const v=i/4;chart+=`<line class="axis" opacity=".35" x1="${pad.l}" y1="${ty(v)}" x2="${W-pad.r}" y2="${ty(v)}"/><text class="chart-label" x="4" y="${ty(v)+4}">${Math.round(v*100)}%</text>`;}if(runs.length){runs.forEach((r,i)=>{chart+=`<text class="chart-label" text-anchor="middle" x="${tx(i)}" y="${H-12}">${r.date.slice(5)}</text>`;});visibleTrendCategories.forEach(cat=>{const pts=runs.map((r,i)=>`${tx(i)},${ty((r.cumulative_topic_ratios||{})[cat.id]||0)}`).join(" ");if(runs.length>1)chart+=`<polyline class="trend-line" stroke="${cat.color}" points="${pts}"/>`;runs.forEach((r,i)=>{const value=(r.cumulative_topic_ratios||{})[cat.id]||0,y=ty(value),x=tx(i)+dotOffset(i,value,cat.id);chart+=`<circle class="run-dot" cx="${x}" cy="${y}" r="4.5" fill="${cat.color}"/>`;});});}ts.innerHTML=chart;
const wp=Object.fromEntries(data.wiki.pages.map(x=>[x.id,x]));let current="overview",wq="";
function nav(){wikinav.innerHTML=data.wiki.pages.filter(x=>!wq||`${x.title} ${x.body}`.toLowerCase().includes(wq)).map(x=>`<button data-page="${x.id}" class="${x.id===current?"active":""}">${x.title}<small>${x.type}</small></button>`).join("")}
function openPage(id){const p=wp[id];if(!p)return;current=id;nav();wikipage.innerHTML=`<div class="eyebrow">${p.type}</div><h3>${p.title}</h3><p class="lede">${p.subtitle||""}</p><p>${p.body}</p>${p.source_url?`<p><a href="${p.source_url}">Open source ↗</a></p>`:""}${p.assessment?`<h4>Scout assessment</h4><p>${p.assessment}</p>`:""}${p.related?.length?`<h4>Related papers</h4><div class="related">${p.related.map(x=>`<button data-page="${x.id}"><b>${x.title}</b><small>${x.reason}</small></button>`).join("")}</div>`:""}${p.links?.length?`<h4>Linked pages</h4><div class="links">${p.links.map(id=>wp[id]?`<button data-page="${id}">${wp[id].title}</button>`:"").join("")}</div>`:""}`;wikipage.scrollTop=0}
wiki.addEventListener("click",e=>{const b=e.target.closest("[data-page]");if(b)openPage(b.dataset.page)});wikisearch.oninput=e=>{wq=e.target.value.toLowerCase();nav()};nav();openPage("overview");
graphcat.innerHTML+=data.categories.map(x=>`<option value="${x.id}">${x.label}</option>`).join("");
const cv=graph,ctx=cv.getContext("2d"),catIndex=Object.fromEntries(data.categories.map((x,i)=>[x.id,i])),nodes=data.graph.nodes.map((n,i)=>{const a=catIndex[n.category]/Math.max(1,data.categories.length)*Math.PI*2,r=60+(i%8)*8;return{...n,x:Math.cos(a)*r,y:Math.sin(a)*r,vx:0,vy:0}}),nodeMap=Object.fromEntries(nodes.map(x=>[x.id,x])),edges=data.graph.edges.map(e=>({...e,a:nodeMap[e.source],b:nodeMap[e.target]}));let view={x:0,y:0,s:.5},filter="all",selected=null,frame=0;
function resize(){const r=cv.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);cv.width=r.width*d;cv.height=r.height*d;ctx.setTransform(d,0,0,d,0,0)}function pos(n){const r=cv.getBoundingClientRect();return{x:r.width/2+view.x+n.x*view.s,y:r.height/2+view.y+n.y*view.s}}function visible(n){return filter==="all"||n.category===filter}
function draw(){const r=cv.getBoundingClientRect();ctx.clearRect(0,0,r.width,r.height);edges.forEach(e=>{if(!visible(e.a)||!visible(e.b))return;const a=pos(e.a),b=pos(e.b);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=selected&&(e.a===selected||e.b===selected)?"#ddd":"#60706b44";ctx.stroke()});nodes.forEach(n=>{if(!visible(n))return;const p=pos(n),rad=5+Math.sqrt(n.degree+1)*2;ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fillStyle=byCat[n.category]?.color||"#aaa";ctx.fill();if(n===selected){ctx.strokeStyle="#fff";ctx.lineWidth=2;ctx.stroke();ctx.fillStyle="#fff";ctx.font="12px sans-serif";ctx.fillText(n.title,p.x+rad+5,p.y)}})}
function sim(){if(frame++<360){for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){let a=nodes[i],b=nodes[j],dx=b.x-a.x,dy=b.y-a.y,d2=Math.max(70,dx*dx+dy*dy),f=55/d2;a.vx-=dx*f;a.vy-=dy*f;b.vx+=dx*f;b.vy+=dy*f}edges.forEach(e=>{let dx=e.b.x-e.a.x,dy=e.b.y-e.a.y,d=Math.max(1,Math.hypot(dx,dy)),f=(d-42)*.003;e.a.vx+=dx/d*f;e.a.vy+=dy/d*f;e.b.vx-=dx/d*f;e.b.vy-=dy/d*f});nodes.forEach(n=>{n.vx+=-n.x*.001;n.vy+=-n.y*.001;n.vx*=.87;n.vy*=.87;n.x+=n.vx;n.y+=n.vy})}draw();requestAnimationFrame(sim)}
cv.onclick=e=>{const r=cv.getBoundingClientRect(),x=(e.clientX-r.left-r.width/2-view.x)/view.s,y=(e.clientY-r.top-r.height/2-view.y)/view.s;selected=nodes.find(n=>visible(n)&&Math.hypot(n.x-x,n.y-y)<14)||null;if(selected){detail.innerHTML=`<h3>${selected.title}</h3><p>${selected.category} · ${selected.year||""}</p><button id="towiki">Open wiki page</button>${selected.url?`<p><a href="${selected.url}">Open source ↗</a></p>`:""}`;towiki.onclick=()=>{openPage(selected.id);wiki.scrollIntoView({behavior:"smooth"})}}};cv.onwheel=e=>{e.preventDefault();view.s=Math.max(.35,Math.min(3,view.s*(e.deltaY<0?1.12:.89)))};
graphcat.onchange=e=>{filter=e.target.value;selected=null};graphsearch.oninput=e=>{const q=e.target.value.toLowerCase(),n=nodes.find(x=>x.title.toLowerCase().includes(q));if(n){selected=n;detail.innerHTML=`<h3>${n.title}</h3><p>${n.category}</p>`}};detail.innerHTML=`<h3>${data.graph.nodes.length} papers</h3><p>Select a node to inspect it.</p>`;addEventListener("resize",resize);resize();sim();
const opp=data.opportunities;oppsummary.textContent=opp.summary||"No opportunity analysis yet.";opportunities.innerHTML=(opp.opportunities||[]).map(x=>`<section class="opportunity"><div class="rank">0${x.rank}</div><div><span class="tag">${x.gap_type}</span><span class="tag">${x.confidence}</span><h3>${x.title}</h3><p>${x.scope}</p><p><b>Reasoning:</b> ${x.llm_reasoning}</p><p><b>Uncertainty:</b> ${x.uncertainty}</p></div><aside><div class="eyebrow">Priority</div><div class="score">${x.priority_score}/100</div><ul>${x.research_questions.slice(0,3).map(q=>`<li>${q}</li>`).join("")}</ul></aside></section>`).join("")||"<p>Use the generated gap-analysis skill after papers are accepted.</p>";
papers.innerHTML=[...data.papers].sort((a,b)=>(b.year||0)-(a.year||0)).map(p=>`<tr><td>${p.year||""}</td><td><a href="${p.url||"#"}">${p.title}</a></td><td>${p.primary_category}</td><td>${p.citation_count||0}</td></tr>`).join("");
</script></body></html>"""


def main() -> int:
    payload = build_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DATA_DIR / "dashboard.json", payload)
    embedded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
    DASHBOARD_PATH.write_text(
        HTML.replace("__TITLE__", payload["topic"]["topic"]).replace("__DATA__", embedded),
        encoding="utf-8",
    )
    print(
        f"Built {DASHBOARD_PATH}: {payload['paper_count']} papers, "
        f"{payload['wiki']['page_count']} wiki pages, {len(payload['graph']['edges'])} graph links."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
