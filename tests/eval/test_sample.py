from arbiter.classify import ALL_6
from arbiter.eval.sample import stratified_select


def _row(i, **pos):
    labels = {c: 0 for c in ALL_6}
    for c in pos:
        labels[c] = 1
    return {"id": str(i), "comment": f"c{i}", "labels": labels}


def _make_rows():
    rows = []
    for i in range(3):
        rows.append(_row(f"thr{i}", threat=1))
    for i in range(3):
        rows.append(_row(f"idh{i}", identity_hate=1))
    for i in range(40):
        rows.append(_row(f"tox{i}", toxic=1))
    for i in range(100):
        rows.append(_row(f"clean{i}"))
    return rows


def test_rare_categories_are_not_starved():
    rows = _make_rows()
    sel = stratified_select(rows, n_target=50, min_per_category=2, seed=1)
    threat_pos = sum(1 for r in sel if r["labels"]["threat"] == 1)
    idh_pos = sum(1 for r in sel if r["labels"]["identity_hate"] == 1)
    assert threat_pos >= 2 and idh_pos >= 2


def test_is_deterministic_for_a_seed():
    rows = _make_rows()
    a = [r["id"] for r in stratified_select(rows, 50, 2, seed=7)]
    b = [r["id"] for r in stratified_select(rows, 50, 2, seed=7)]
    assert a == b


def test_no_duplicate_ids():
    rows = _make_rows()
    sel = stratified_select(rows, 50, 2, seed=1)
    ids = [r["id"] for r in sel]
    assert len(ids) == len(set(ids))
