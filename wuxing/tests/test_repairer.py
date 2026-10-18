from wuxing.repairer import Repairer, classify_failure


def test_classify_budget():
    assert classify_failure("guard: budget/rounds exhausted") == "budget"
def test_classify_tool():
    assert classify_failure("tool: unknown tool 'rm'") == "tool"
def test_classify_contract():
    assert classify_failure("contract: missing key 'plan'") == "contract"
def test_classify_default():
    assert classify_failure("something else") == "unknown"

def test_repair_contract_gives_hint():
    r = Repairer()
    assert "修正" in r.repair("contract", "contract: missing key")
def test_repair_budget_tightens():
    r = Repairer()
    assert "护栏" in r.repair("budget", "guard: ...") or "预算" in r.repair("budget", "guard: ...")
