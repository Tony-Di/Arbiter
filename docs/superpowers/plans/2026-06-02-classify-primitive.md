# classify Primitive — Implementation Plan

> **For the author:** This plan is **scaffold-only** by request. You hand-write every implementation body; the **tests are your target** (red → green). Steps use `- [ ]` for tracking. Ping me when stuck or for a review/smoke pass.

**Goal:** Build the shared `classify(model, comment, categories=ALL_6) → ClassifyResult` primitive and prove it end-to-end on DeepSeek (the cheapest, OpenAI-compatible contestant). Everything else in Arbiter (eval harness + product pipeline) sits on this.

**Architecture:** A small Python library under `src/arbiter/classify/`. One shared Pydantic schema (the contract), one shared prompt (identical across providers, carries the severity rubric), a registry mapping model-id → adapter config, and a thin `classify()` doing prompt → adapter call → validate → retry-once. First adapter is OpenAI-compatible (covers DeepSeek **and** OpenAI via different registry rows). Gemini + Anthropic adapters are the next increment (out of this plan).

**Tech Stack:** Python 3.14 · Pydantic v2 · the `openai` SDK (OpenAI-compatible, works for DeepSeek) · `python-dotenv` · `pytest`.

---

## What I give vs. what you write

| I give (scaffold) | 🔨 You implement (bodies) |
|---|---|
| Project config (`pyproject.toml`, `.gitignore`, `.env.example`) | `schema.py` — the Pydantic models |
| `adapters/base.py` — the Adapter interface | `prompt.py` — `build_prompt()` |
| **Every test file** (your red→green target) | `registry.py` — `REGISTRY` + `get_adapter()` |
| Field/behavior **specs** + bare skeletons | `adapters/openai_compat.py` — the adapter |
| The live smoke script | `core.py` — `classify()` |
| Factual values you can't guess (base_urls, model ids) | |

**git:** every Commit step is **run by you** — I never run git. Messages provided.

---

## File structure (this plan)

```
arbiter/
  pyproject.toml                      # I give
  .env.example  .gitignore            # I give
  src/arbiter/__init__.py             # empty
  src/arbiter/classify/
    __init__.py                       # re-exports (Task 6)
    schema.py                         # 🔨 you
    prompt.py                         # 🔨 you
    registry.py                       # 🔨 you
    core.py                           # 🔨 you
    adapters/__init__.py              # empty
    adapters/base.py                  # I give (interface)
    adapters/openai_compat.py         # 🔨 you
  tests/classify/                     # I give ALL (your targets)
    test_schema.py  test_prompt.py  test_registry.py
    test_adapter_openai_compat.py  test_core.py
  scripts/smoke_classify.py           # I give (harness)
```

---

## Task 0: Project bootstrap (I give — config only)

**Files:** Create `pyproject.toml`, `.env.example`, `.gitignore`, and empty `__init__.py` for `src/arbiter/`, `src/arbiter/classify/`, `src/arbiter/classify/adapters/`, `tests/`, `tests/classify/`.

- [ ] **Step 1: `pyproject.toml`**
```toml
[project]
name = "arbiter"
version = "0.1.0"
description = "Multi-agent content moderation + cross-model LLM evaluation"
requires-python = ">=3.14"
dependencies = ["pydantic>=2.7", "openai>=1.40", "python-dotenv>=1.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/arbiter"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: `.env.example`**
```
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
```

- [ ] **Step 3: `.gitignore`**
```
.env
__pycache__/
*.pyc
.pytest_cache/
data/
.venv/
```

- [ ] **Step 4: venv + install + verify**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -c "import arbiter; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Commit** *(you run)*
```
git add pyproject.toml .env.example .gitignore src/arbiter tests
git commit -m "chore: bootstrap arbiter package + classify scaffolding"
```

---

## Task 1: 🔨 `schema.py` — the data contract

**Files:** Create `src/arbiter/classify/schema.py` 🔨 · Test (given): `tests/classify/test_schema.py`

**Spec — what the module must export:**
| Name | Kind | Detail |
|---|---|---|
| `SCHEMA_VERSION` | `str` | a non-empty version string, start `"1"` |
| `ALL_6` | `list[str]` | exactly, in order: `toxic, severe_toxic, obscene, threat, insult, identity_hate` |
| `Severity` | `IntEnum` | `none=0, low=1, medium=2, high=3` |
| `CategoryVerdict` | `BaseModel` | `severity: Severity`, `reason: str`, `span: str \| None` (default `None`) |
| `ClassifyResult` | `BaseModel` | `verdicts: dict[str, CategoryVerdict]` |

- [ ] **Step 1: The test is given — read it, run it, watch it fail**

```python
# tests/classify/test_schema.py
import pytest
from pydantic import ValidationError
from arbiter.classify.schema import (
    Severity, CategoryVerdict, ClassifyResult, ALL_6, SCHEMA_VERSION,
)

def test_all_6_is_the_jigsaw_label_set():
    assert ALL_6 == ["toxic", "severe_toxic", "obscene", "threat", "insult", "identity_hate"]

def test_severity_is_ordinal_0_to_3():
    assert int(Severity.none) == 0 and int(Severity.high) == 3

def test_category_verdict_accepts_nullable_span():
    assert CategoryVerdict(severity=Severity.low, reason="mild", span=None).span is None

def test_classify_result_round_trips_from_dict():
    raw = {"verdicts": {"toxic": {"severity": 2, "reason": "rude", "span": "you idiot"}}}
    assert ClassifyResult.model_validate(raw).verdicts["toxic"].severity == Severity.medium

def test_invalid_severity_is_rejected():
    with pytest.raises(ValidationError):
        CategoryVerdict(severity=9, reason="x", span=None)

def test_schema_version_is_present():
    assert isinstance(SCHEMA_VERSION, str) and SCHEMA_VERSION
```
Run: `pytest tests/classify/test_schema.py -v` → Expected: FAIL (`ModuleNotFoundError: ...schema`).

- [ ] **Step 2: 🔨 Write `schema.py` to the spec above** (translate the table into Pydantic v2 + an `IntEnum`).

- [ ] **Step 3: Run → green**
Run: `pytest tests/classify/test_schema.py -v` → Expected: PASS (6 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/classify/schema.py tests/classify/test_schema.py
git commit -m "feat(classify): shared Pydantic schema (Severity, verdicts, ALL_6)"
```

---

## Task 2: 🔨 `prompt.py` — the shared prompt

**Files:** Create `src/arbiter/classify/prompt.py` 🔨 · Test (given): `tests/classify/test_prompt.py`

**Spec:**
- Export `PROMPT_VERSION: str` (start `"1"`).
- Export `build_prompt(comment: str, categories: list[str] = ALL_6) -> str`.
- The returned string must contain: (a) instructions — *you are a content-moderation rater; judge ONLY the listed categories; for each return severity 0–3, a short reason, and span = verbatim offending substring or null; detection only, no overall action; return JSON `{"verdicts": {"<cat>": {"severity": int, "reason": str, "span": str|null}}}` with one entry per requested category*; (b) the rubric below; (c) the requested category names; (d) the comment.
- **Identical body across providers** (fairness). Bump `PROMPT_VERSION` whenever you change wording.

**Rubric text to embed** (approved in spec §5 — paste as a constant, you write the assembly):
```
Severity scale (per category):
- none (0): no policy-relevant harm for this category.
- low (1): mild or ambiguous - borderline, weak/uncertain, plausibly-but-not-clearly harmful.
- medium (2): clear harmful content; a likely human-review candidate.
- high (3): severe - a credible direct threat, an explicit identity attack, or severe abuse; a removal candidate.
```

- [ ] **Step 1: Test given — run, watch it fail**
```python
# tests/classify/test_prompt.py
from arbiter.classify.prompt import build_prompt, PROMPT_VERSION
from arbiter.classify.schema import ALL_6

def test_prompt_version_present():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION

def test_prompt_lists_only_requested_categories():
    p = build_prompt("some comment", ["toxic", "threat"])
    assert "toxic" in p and "threat" in p and "obscene" not in p

def test_prompt_includes_comment_and_rubric_levels():
    p = build_prompt("you are an idiot", ALL_6)
    assert "you are an idiot" in p
    for level in ("none", "low", "medium", "high"):
        assert level in p
```
Run: `pytest tests/classify/test_prompt.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 Write `build_prompt` + `PROMPT_VERSION`** to satisfy the spec + tests.

- [ ] **Step 3: Run → green** (`pytest tests/classify/test_prompt.py -v`, 3 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/classify/prompt.py tests/classify/test_prompt.py
git commit -m "feat(classify): shared prompt + severity rubric (v1)"
```

---

## Task 3: `adapters/base.py` — the Adapter interface (I give)

**Files:** Create `src/arbiter/classify/adapters/base.py` · Test (given): top of `tests/classify/test_adapter_openai_compat.py`

> The adapter's ONLY job: take a finished prompt + the target schema, do one provider call, return a parsed `dict` (raw, unvalidated). Validation + retry live in `core.classify` (provider-agnostic).

- [ ] **Step 1: Create `base.py`**
```python
# src/arbiter/classify/adapters/base.py
from typing import Protocol
from pydantic import BaseModel

class AdapterError(RuntimeError):
    """Raised when a provider call fails or returns unparseable output."""

class Adapter(Protocol):
    """One provider's calling convention. Returns a raw dict (unvalidated)."""
    def complete(self, prompt: str, schema: type[BaseModel]) -> dict: ...
```

- [ ] **Step 2: Test given — run, watch it pass**
```python
# tests/classify/test_adapter_openai_compat.py   (top — extended in Task 4)
from arbiter.classify.adapters.base import Adapter, AdapterError

class _FakeAdapter:
    def __init__(self, payload): self._payload = payload
    def complete(self, prompt, schema): return self._payload

def test_fake_adapter_satisfies_protocol():
    a: Adapter = _FakeAdapter({"verdicts": {}})
    assert a.complete("p", object) == {"verdicts": {}}

def test_adapter_error_is_an_exception():
    assert issubclass(AdapterError, Exception)
```
Run: `pytest tests/classify/test_adapter_openai_compat.py -v` → Expected: PASS (2).

- [ ] **Step 3: Commit** *(you run)*
```
git add src/arbiter/classify/adapters/base.py tests/classify/test_adapter_openai_compat.py
git commit -m "feat(classify): adapter protocol + AdapterError"
```

---

## Task 4: 🔨 `adapters/openai_compat.py` — the adapter

**Files:** Create `src/arbiter/classify/adapters/openai_compat.py` 🔨 · Test (given, append): `tests/classify/test_adapter_openai_compat.py`

**Spec — `OpenAICompatAdapter`:**
- `__init__(self, base_url: str, api_key: str, model: str)` → build & store one `openai.OpenAI(base_url=, api_key=)` client + the model name.
- `complete(prompt, schema) -> dict`:
  1. `client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, temperature=0)`.
  2. `json.loads(resp.choices[0].message.content)` → `dict`.
  3. Return the dict **unvalidated** (core validates). `schema` is accepted for interface symmetry / future strict-mode use — don't validate here.
  4. Wrap any exception: `raise AdapterError(...) from e`.
- **Import `OpenAI` as `from openai import OpenAI`** at module top (the test patches `arbiter.classify.adapters.openai_compat.OpenAI`).
- **Later note (not now):** OpenAI's strict `json_schema` mode rejects open-ended `dict`. `json_object` + our Pydantic validation handles it. Keep `json_object` for the skeleton.

- [ ] **Step 1: Append the given test — run, watch it fail**
```python
# tests/classify/test_adapter_openai_compat.py   (append)
import json
from unittest.mock import MagicMock, patch
import pytest
from arbiter.classify.adapters.openai_compat import OpenAICompatAdapter
from arbiter.classify.adapters.base import AdapterError
from arbiter.classify.schema import ClassifyResult

def _resp(content):
    m = MagicMock(); m.choices = [MagicMock(message=MagicMock(content=content))]; return m

@patch("arbiter.classify.adapters.openai_compat.OpenAI")
def test_complete_returns_parsed_dict(mock_openai):
    client = mock_openai.return_value
    payload = {"verdicts": {"toxic": {"severity": 1, "reason": "mild", "span": None}}}
    client.chat.completions.create.return_value = _resp(json.dumps(payload))
    a = OpenAICompatAdapter(base_url="https://x", api_key="k", model="deepseek-chat")
    out = a.complete("prompt", ClassifyResult)
    assert out == payload
    _, kw = client.chat.completions.create.call_args
    assert kw["model"] == "deepseek-chat" and kw["temperature"] == 0
    assert kw["response_format"] == {"type": "json_object"}

@patch("arbiter.classify.adapters.openai_compat.OpenAI")
def test_complete_wraps_bad_json_in_adapter_error(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = _resp("not json{{")
    a = OpenAICompatAdapter(base_url="https://x", api_key="k", model="deepseek-chat")
    with pytest.raises(AdapterError):
        a.complete("prompt", ClassifyResult)
```
Run: `pytest tests/classify/test_adapter_openai_compat.py -v` → Expected: FAIL (`ModuleNotFoundError: ...openai_compat`).

- [ ] **Step 2: 🔨 Write `openai_compat.py`** to the spec + tests. Skeleton:
```python
# src/arbiter/classify/adapters/openai_compat.py
import json
from pydantic import BaseModel
from openai import OpenAI
from .base import AdapterError

class OpenAICompatAdapter:
    def __init__(self, base_url: str, api_key: str, model: str):
        ...  # 🔨
    def complete(self, prompt: str, schema: type[BaseModel]) -> dict:
        ...  # 🔨
```

- [ ] **Step 3: Run → green** (`pytest tests/classify/test_adapter_openai_compat.py -v`, 4 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/classify/adapters/openai_compat.py tests/classify/test_adapter_openai_compat.py
git commit -m "feat(classify): OpenAI-compatible adapter (DeepSeek/OpenAI)"
```

---

## Task 5: 🔨 `registry.py` — model registry

**Files:** Create `src/arbiter/classify/registry.py` 🔨 · Test (given): `tests/classify/test_registry.py`

**Spec:**
- `REGISTRY: dict[str, dict]` — one row per model-id; each row = `{"adapter": <cls>, "base_url": str, "api_key_env": str, "model": str}`. Rows to include (factual values you need):

| model-id | adapter | base_url | api_key_env | model |
|---|---|---|---|---|
| `deepseek-chat` | `OpenAICompatAdapter` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `gpt-4o-mini` | `OpenAICompatAdapter` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | `gpt-4o-mini` |

- `get_adapter(model_id: str) -> Adapter`: look up `REGISTRY[model_id]` (let `KeyError` propagate on unknown id); read the API key from `os.environ[row["api_key_env"]]` — if missing/empty raise `RuntimeError(...)`; construct and return `row["adapter"](base_url=..., api_key=..., model=...)`.

- [ ] **Step 1: Test given — run, watch it fail**
```python
# tests/classify/test_registry.py
import pytest
from arbiter.classify.registry import get_adapter, REGISTRY
from arbiter.classify.adapters.openai_compat import OpenAICompatAdapter

def test_deepseek_and_openai_are_registered():
    assert "deepseek-chat" in REGISTRY and "gpt-4o-mini" in REGISTRY

def test_get_adapter_builds_openai_compat_for_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    assert isinstance(get_adapter("deepseek-chat"), OpenAICompatAdapter)

def test_unknown_model_raises():
    with pytest.raises(KeyError):
        get_adapter("no-such-model")

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_adapter("deepseek-chat")
```
Run: `pytest tests/classify/test_registry.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 Write `registry.py`** to the spec + table + tests.

- [ ] **Step 3: Run → green** (4 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/classify/registry.py tests/classify/test_registry.py
git commit -m "feat(classify): model registry + get_adapter()"
```

---

## Task 6: 🔨 `core.py` — `classify()`

**Files:** Create `src/arbiter/classify/core.py` 🔨 · Modify `src/arbiter/classify/__init__.py` · Test (given): `tests/classify/test_core.py`

**Spec — `classify(model: str, comment: str, categories: list[str] = ALL_6) -> ClassifyResult`:**
1. `adapter = get_adapter(model)`.
2. `prompt = build_prompt(comment, categories)`.
3. `raw = adapter.complete(prompt, ClassifyResult)`.
4. Validate: `ClassifyResult.model_validate(raw)`.
5. **Retry once:** if step 3 or 4 raises on the first attempt, do steps 3–4 again; if the second attempt also raises, let it propagate.
6. Return the validated `ClassifyResult`. (Don't enforce "exactly the requested keys" yet — later refinement.)

> Import `get_adapter` as `from .registry import get_adapter` (the test patches `arbiter.classify.core.get_adapter`).

- [ ] **Step 1: Test given — run, watch it fail**
```python
# tests/classify/test_core.py
from unittest.mock import patch
import pytest
from arbiter.classify.core import classify
from arbiter.classify.schema import ClassifyResult, Severity

class _ScriptedAdapter:
    def __init__(self, *payloads): self._q = list(payloads)
    def complete(self, prompt, schema):
        item = self._q.pop(0)
        if isinstance(item, Exception): raise item
        return item

GOOD = {"verdicts": {"toxic": {"severity": 2, "reason": "rude", "span": "idiot"}}}
BAD  = {"verdicts": {"toxic": {"severity": 99, "reason": "x", "span": None}}}

def test_classify_returns_validated_result():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(GOOD)):
        r = classify("deepseek-chat", "you idiot", ["toxic"])
    assert isinstance(r, ClassifyResult) and r.verdicts["toxic"].severity == Severity.medium

def test_classify_retries_once_then_succeeds():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(BAD, GOOD)):
        r = classify("deepseek-chat", "you idiot", ["toxic"])
    assert r.verdicts["toxic"].severity == Severity.medium

def test_classify_raises_after_two_failures():
    with patch("arbiter.classify.core.get_adapter", return_value=_ScriptedAdapter(BAD, BAD)):
        with pytest.raises(Exception):
            classify("deepseek-chat", "you idiot", ["toxic"])
```
Run: `pytest tests/classify/test_core.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 Write `core.py`** to the spec + tests. Skeleton:
```python
# src/arbiter/classify/core.py
from .schema import ClassifyResult, ALL_6
from .prompt import build_prompt
from .registry import get_adapter

def classify(model: str, comment: str, categories: list[str] = ALL_6) -> ClassifyResult:
    ...  # 🔨
```

- [ ] **Step 3: Re-export (I give)** — `src/arbiter/classify/__init__.py`:
```python
from .core import classify
from .schema import ALL_6, Severity, CategoryVerdict, ClassifyResult
__all__ = ["classify", "ALL_6", "Severity", "CategoryVerdict", "ClassifyResult"]
```

- [ ] **Step 4: Whole suite → green** (`pytest tests/classify -v`, all green).

- [ ] **Step 5: Commit** *(you run)*
```
git add src/arbiter/classify/core.py src/arbiter/classify/__init__.py tests/classify/test_core.py
git commit -m "feat(classify): classify() core with validate + retry-once"
```

---

## Task 7: Live smoke test on DeepSeek (I give the harness)

**Files:** Create `scripts/smoke_classify.py` (not in the pytest suite — costs money + needs a key).

- [ ] **Step 1: `scripts/smoke_classify.py`**
```python
# scripts/smoke_classify.py
"""Manual smoke test: real DeepSeek call. Needs DEEPSEEK_API_KEY in .env."""
from dotenv import load_dotenv
from arbiter.classify import classify, ALL_6

load_dotenv()
CASES = [
    "I will find you and kill you.",          # expect threat-ish
    "Thanks so much, this really helped!",    # expect all none
    "oh great, ANOTHER genius idea 🙄",        # gray: sarcasm
]
for text in CASES:
    print("\n" + "=" * 60); print("COMMENT:", text)
    r = classify("deepseek-chat", text, ALL_6)
    for cat, v in r.verdicts.items():
        if v.severity > 0:
            print(f"  {cat:14} sev={v.severity.name:6} span={v.span!r}  {v.reason}")
    if all(v.severity == 0 for v in r.verdicts.values()):
        print("  (all none)")
```

- [ ] **Step 2: Real key** — copy `.env.example` → `.env`, set `DEEPSEEK_API_KEY=...` (gitignored).

- [ ] **Step 3: Run** — `python scripts/smoke_classify.py`. Expected: three blocks; threat case shows a non-`none` severity + span; thank-you case prints `(all none)`. Eyeball sanity — exact severities needn't match.

- [ ] **Step 4: Commit** *(you run)*
```
git add scripts/smoke_classify.py
git commit -m "chore(classify): live DeepSeek smoke script"
```

---

## Definition of done (Plan 1)
- `pytest tests/classify -v` fully green (no network).
- `python scripts/smoke_classify.py` returns sane verdicts from real DeepSeek.
- `from arbiter.classify import classify, ALL_6` works.

## Next increment (NOT this plan)
- `adapters/gemini.py` + 1 registry row → `adapters/anthropic.py` + 1 registry row (same `complete()` contract; `core.py`/schema unchanged).
- Then → **Plan 2: eval harness** (sample → collect → score → fairness → routing_table.json).
```
