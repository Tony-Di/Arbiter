import json

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.eval.collect import cache_path, collect, load_done_ids


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _fake_result():
    return ClassifyResult(
        verdicts={c: {"severity": Severity.none, "reason": "x", "span": None} for c in ALL_6}
    )


def test_cache_path_encodes_versions():
    p = cache_path("eval_cache", "deepseek-chat", "1", "1")
    assert p == "eval_cache/deepseek-chat__p1__s1.jsonl"


def test_load_done_ids_missing_file_is_empty(tmp_path):
    assert load_done_ids(str(tmp_path / "nope.jsonl")) == set()


def test_collect_is_resumable(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_jsonl(
        sample,
        [
            {"id": "a", "comment": "hi", "labels": {c: 0 for c in ALL_6}},
            {"id": "b", "comment": "yo", "labels": {c: 0 for c in ALL_6}},
        ],
    )
    out = tmp_path / "out.jsonl"

    calls = []

    def fake_classify(model, comment, categories):
        calls.append(comment)
        return _fake_result()

    n1 = collect(str(sample), str(out), "deepseek-chat", fake_classify)
    assert n1 == 2 and len(calls) == 2

    n2 = collect(str(sample), str(out), "deepseek-chat", fake_classify)
    assert n2 == 0 and len(calls) == 2  # nothing re-called

    assert load_done_ids(str(out)) == {"a", "b"}
