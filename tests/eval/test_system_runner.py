import csv
import json

import pytest

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.eval.system_runner import (
    CACHE_VERSION,
    VARIANTS,
    load_cases,
    make_config_fingerprint,
    make_production_variant_fns,
    run_system_eval,
    write_reports,
)


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _cases():
    return [
        {"id": "a", "comment": "clean", "gold_action": "allow"},
        {"id": "b", "comment": "bad", "gold_action": "remove", "gold_severity": 3},
    ]


def test_load_cases_supports_jsonl_and_csv_aliases(tmp_path):
    jsonl = tmp_path / "gold.jsonl"
    _write_jsonl(
        jsonl,
        [{"case_id": "j1", "text": "hello", "action": "review", "categories": ["insult"]}],
    )
    assert load_cases(jsonl)[0] == {
        "case_id": "j1",
        "text": "hello",
        "action": "review",
        "categories": ["insult"],
        "id": "j1",
        "comment": "hello",
        "gold_action": "human-review",
        "gold_categories": ["insult"],
    }

    csv_path = tmp_path / "gold.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "comment", "gold_action", "gold_categories", "gold_severity"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "c1",
                "comment": "threat",
                "gold_action": "remove",
                "gold_categories": "threat|toxic",
                "gold_severity": "3",
            }
        )
    loaded = load_cases(csv_path)[0]
    assert loaded["gold_categories"] == ["threat", "toxic"]
    assert loaded["gold_severity"] == 3


def test_runner_supports_all_variants_and_resumes_exact_cache_identity(tmp_path):
    cache = tmp_path / "predictions.jsonl"
    calls = []

    def variant(name):
        def run(case):
            calls.append((name, case["id"], case["comment"]))
            return {"action": "allow" if case["id"] == "a" else "remove", "trace": name}
        return run

    functions = {name: variant(name) for name in VARIANTS}
    first = run_system_eval(
        _cases(), functions, cache, config_fingerprint="config-a"
    )
    assert first["n_new_predictions"] == 8
    assert first["n_cached_predictions"] == 0
    assert len(calls) == 8
    assert all(metric["coverage"] == 1 for metric in first["metrics"].values())

    second = run_system_eval(
        _cases(), functions, cache, config_fingerprint="config-a"
    )
    assert second["n_new_predictions"] == 0
    assert second["n_cached_predictions"] == 8
    assert len(calls) == 8

    changed = _cases()
    changed[0] = {**changed[0], "comment": "clean but changed"}
    third = run_system_eval(
        changed, functions, cache, config_fingerprint="config-a"
    )
    assert third["n_new_predictions"] == 4
    assert third["n_cached_predictions"] == 4
    assert len(calls) == 12

    fourth = run_system_eval(
        changed, functions, cache, config_fingerprint="config-b"
    )
    assert fourth["n_new_predictions"] == 8
    assert fourth["n_cached_predictions"] == 0
    assert len(calls) == 20

    rows = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()]
    assert all(row["cache_version"] == CACHE_VERSION for row in rows)
    assert all(len(row["text_sha256"]) == 64 for row in rows)


def test_failed_call_is_not_cached_and_resume_retries_it(tmp_path):
    attempts = 0

    def flaky(case):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary")
        return "allow"

    cache = tmp_path / "cache.jsonl"
    cases = [{"id": "a", "comment": "x", "gold_action": "allow"}]
    first = run_system_eval(
        cases,
        {"single_call": flaky},
        cache,
        variants=["single_call"],
        config_fingerprint="cfg",
    )
    assert first["metrics"]["single_call"]["coverage"] == 0
    assert len(first["errors"]) == 1

    second = run_system_eval(
        cases,
        {"single_call": flaky},
        cache,
        variants=["single_call"],
        config_fingerprint="cfg",
    )
    assert second["metrics"]["single_call"]["coverage"] == 1
    assert second["n_new_predictions"] == 1
    assert attempts == 2


def test_write_reports_emits_json_and_flat_csv(tmp_path):
    functions = {name: (lambda case: "allow" if case["id"] == "a" else "remove") for name in VARIANTS}
    result = run_system_eval(
        _cases(), functions, tmp_path / "cache.jsonl", config_fingerprint="cfg"
    )
    paths = write_reports(result, tmp_path / "reports")

    report = json.loads((tmp_path / "reports" / "system_eval_metrics.json").read_text())
    assert report["metrics"]["single_call"]["action_macro_f1"] > 0
    assert "metric_definitions" in report
    with open(paths["csv"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["variant"] for row in rows] == list(VARIANTS)
    assert "unsafe_auto_allow_rate" in rows[0]


def test_production_factories_compose_graphs_and_inject_store():
    table = {category: {"model": "fake", "threshold": 1} for category in ALL_6}
    graph_builds = []

    class FakeGraph:
        def __init__(self, action):
            self.action = action

        def invoke(self, state):
            return {**state, "action": self.action, "overall_severity": 0}

    actions = iter(["allow", "human-review", "remove"])

    def graph_builder(table_arg, **kwargs):
        graph_builds.append((table_arg, kwargs))
        return FakeGraph(next(actions))

    def fake_classify(model, comment, categories):
        return ClassifyResult(
            verdicts={
                category: {"severity": Severity.none, "reason": "clean", "span": None}
                for category in categories
            }
        )

    fake_store = object()
    fake_adjudicate = object()
    functions = make_production_variant_fns(
        table,
        single_model="one-model",
        classify_fn=fake_classify,
        detect_fn=lambda comment: None,
        adjudicate_fn=fake_adjudicate,
        store=fake_store,
        graph_builder=graph_builder,
    )

    case = {"id": "a", "comment": "hello", "gold_action": "allow"}
    assert set(functions) == set(VARIANTS) | {"specialists_only"}
    assert functions["single_call"](case)["action"] == "allow"
    assert functions["specialist_panel"](case)["action"] == "allow"
    assert functions["policy_agent"](case)["action"] == "human-review"
    assert functions["full_system"](case)["action"] == "remove"
    assert graph_builds[0][1].get("adjudicate_fn") is None
    assert graph_builds[1][1]["store"] is None
    assert graph_builds[2][1]["store"] is fake_store
    assert graph_builds[2][1]["adjudicate_fn"] is fake_adjudicate


def test_single_call_rejects_missing_category_instead_of_silently_allowing():
    table = {category: {"model": "fake", "threshold": 1} for category in ALL_6}

    class FakeGraph:
        def invoke(self, state):
            return {**state, "action": "allow", "overall_severity": 0}

    def fake_classify(model, comment, categories):
        return ClassifyResult(
            verdicts={
                category: {"severity": Severity.none, "reason": "clean", "span": None}
                for category in categories[:-1]
            }
        )

    functions = make_production_variant_fns(
        table,
        classify_fn=fake_classify,
        graph_builder=lambda table_arg, **kwargs: FakeGraph(),
    )
    with pytest.raises(ValueError, match="missing=identity_hate"):
        functions["single_call"]({"id": "a", "comment": "hello", "gold_action": "allow"})


def test_policy_variant_removes_precedent_tool_and_prompt_before_model_call():
    table = {category: {"model": "fake", "threshold": 1} for category in ALL_6}
    graph_kwargs = []

    class FakeGraph:
        def invoke(self, state):
            return {**state, "action": "allow", "overall_severity": 0}

    def graph_builder(table_arg, **kwargs):
        graph_kwargs.append(kwargs)
        return FakeGraph()

    seen = {}

    def fake_adjudicate(messages, tools):
        seen["messages"] = messages
        seen["tools"] = tools
        return {"role": "assistant", "content": None, "tool_calls": []}

    make_production_variant_fns(
        table,
        adjudicate_fn=fake_adjudicate,
        graph_builder=graph_builder,
    )
    policy_only = graph_kwargs[1]["adjudicate_fn"]
    policy_only(
        [{"role": "system", "content": "Use get_policy and search_precedents to see how human moderators ruled similar comments."}],
        [
            {"function": {"name": "get_policy"}},
            {"function": {"name": "search_precedents"}},
            {"function": {"name": "submit_decision"}},
        ],
    )
    assert [tool["function"]["name"] for tool in seen["tools"]] == [
        "get_policy",
        "submit_decision",
    ]
    assert "search_precedents" not in seen["messages"][0]["content"]


def test_config_fingerprint_is_order_independent():
    assert make_config_fingerprint({"a": 1, "b": 2}) == make_config_fingerprint(
        {"b": 2, "a": 1}
    )


@pytest.mark.parametrize("recommendation,confidence,expected", [
    ("allow", 0.94, "human-review"),
    ("remove", 0.94, "human-review"),
    ("allow", 0.95, "allow"),
    ("human-review", 0.99, "human-review"),
])
def test_eval_action_matches_real_checkpointed_product_gate(recommendation, confidence, expected):
    from langgraph.checkpoint.memory import InMemorySaver
    from arbiter.product.context import ContextFlags
    from arbiter.product.graph import build_graph
    from arbiter.product.state import initial_state

    table = {category: {"model": "fake", "threshold": 1} for category in ALL_6}

    def classify(model, comment, categories):
        return ClassifyResult(verdicts={cat: {"severity": 2, "reason": "gray", "span": None}
                                       for cat in categories})

    def adjudicate(messages, tools):
        return {"role": "assistant", "tool_calls": [{"id": "decision", "type": "function",
            "function": {"name": "submit_decision", "arguments": json.dumps({
                "action": recommendation, "overall_severity": 3 if recommendation == "remove" else 1, "note": "reason",
                "confidence": confidence, "policy_category": "insult", "evidence_span": "gray"})}}]}

    functions = make_production_variant_fns(table, classify_fn=classify,
        detect_fn=lambda _: ContextFlags(ambiguity=True), adjudicate_fn=adjudicate)
    evaluated = functions["policy_agent"]({"id": "x", "comment": "gray"})
    graph = build_graph(table, classify_fn=classify, detect_fn=lambda _: ContextFlags(ambiguity=True),
                        adjudicate_fn=adjudicate, checkpointer=InMemorySaver())
    actual = graph.invoke(initial_state("gray"), {"configurable": {"thread_id": "test"}})
    actual_action = "human-review" if actual.get("__interrupt__") else actual["action"]
    assert evaluated["action"] == expected == actual_action
    assert evaluated["ai_recommended_action"] == recommendation


def test_concurrent_runner_never_exposes_gold_and_writes_valid_cache(tmp_path):
    def predict(case):
        assert set(case) == {"id", "comment"}
        return "allow"

    cases = [{"id": str(i), "comment": str(i), "gold_action": "allow",
              "rationale": "do not leak this"} for i in range(12)]
    cache = tmp_path / "parallel.jsonl"
    result = run_system_eval(cases, {"single_call": predict}, cache,
                             variants=["single_call"], max_workers=3)
    assert result["errors"] == []
    assert len(result["predictions"]) == 12
    assert len({json.loads(line)["case_id"] for line in cache.read_text().splitlines()}) == 12


def test_resume_after_interrupted_tail_retains_new_predictions(tmp_path):
    cache = tmp_path / "interrupted.jsonl"
    cache.write_text('{"incomplete":', encoding="utf-8")
    kwargs = {"variants": ["single_call"]}
    first = run_system_eval(_cases(), {"single_call": lambda _: "allow"}, cache, **kwargs)
    assert first["n_new_predictions"] == 2
    def unexpected_call(_):
        raise AssertionError("Should have resumed from the newly written cache")
    second = run_system_eval(_cases(), {"single_call": unexpected_call}, cache, **kwargs)
    assert second["n_cached_predictions"] == 2
    assert second["errors"] == []


def test_specialists_only_uses_six_classifications_and_no_context_model():
    calls = []
    table = {category: {"model": "same-model", "threshold": 1} for category in ALL_6}
    def classify(model, comment, categories):
        calls.append((model, categories))
        return ClassifyResult(verdicts={cat: {"severity": 2, "reason": "gray", "span": None}
                                       for cat in categories})
    def forbidden_context(_):
        raise AssertionError("specialists_only must not call the context model")
    functions = make_production_variant_fns(table, classify_fn=classify, detect_fn=forbidden_context)
    result = functions["specialists_only"]({"id": "a", "comment": "gray"})
    assert len(calls) == 6
    assert {categories[0] for _, categories in calls} == set(ALL_6)
    assert all(model == "same-model" and len(categories) == 1 for model, categories in calls)
    from arbiter.product.context import ContextFlags
    assert result["context_flags"] == ContextFlags().model_dump()
    assert result["action"] == "human-review"
    assert result["logical_model_turns"] == 6
