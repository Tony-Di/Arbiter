from arbiter.classify.adapters.base import Adapter, AdapterError


class _FakeAdapter:
    def __init__(self, payload):
        self._payload = payload

    def complete(self, prompt, schema):
        return self._payload


def test_fake_adapter_satisfies_protocol():
    a: Adapter = _FakeAdapter({"verdicts": {}})
    assert a.complete("p", object) == {"verdicts": {}}


def test_adapter_error_is_an_exception():
    assert issubclass(AdapterError, Exception)
