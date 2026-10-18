from wuxing.repairer import Repairer, classify_failure


def test_classify_provider_jitter():
    assert classify_failure("provider 返回非 JSON（status=200）") == "provider"

def test_repair_provider_suggests_retry():
    r = Repairer()
    assert "重试" in r.repair("provider", "provider jitter")

def test_classify_http_429():
    assert classify_failure("HTTPError: 429") == "provider"

def test_classify_http_5xx():
    assert classify_failure("HTTPError: 503 Service Unavailable") == "provider"

def test_existing_classes_unchanged():
    assert classify_failure("guard: budget/rounds exhausted") == "budget"
    assert classify_failure("tool: unknown") == "tool"
    assert classify_failure("contract: missing") == "contract"
