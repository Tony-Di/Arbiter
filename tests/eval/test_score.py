import pytest

from arbiter.eval.score import binarize, prf, score_category, sweep_category


def test_binarize():
    assert binarize(3, 2) == 1 and binarize(2, 2) == 1 and binarize(1, 2) == 0


def test_prf_zero_division_is_zero():
    assert prf(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_score_category_hand_computed():
    gold = [1, 1, 0, 0, 1]
    pred_sev = [3, 1, 2, 0, 0]
    s = score_category(gold, pred_sev, cutoff=2)
    # pred binary at >=2: [1,0,1,0,0]; tp=1, fp=1, fn=2
    assert s["tp"] == 1 and s["fp"] == 1 and s["fn"] == 2
    assert s["precision"] == 0.5
    assert s["recall"] == pytest.approx(1 / 3)
    assert s["f1"] == pytest.approx(0.4)


def test_sweep_has_three_cutoffs():
    s = sweep_category([1, 0], [3, 0])
    assert set(s.keys()) == {1, 2, 3}
