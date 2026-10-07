"""Every bundled demo must be solvable end to end by the offline mock provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.agent import RunStatus
from devpilot.config import Settings
from devpilot.llm.mock import find_suggestions
from devpilot.service import run_task

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MOCK = Settings(provider="mock", max_steps=15, command_timeout=60)
DEMOS = sorted(p.name for p in EXAMPLES.iterdir() if p.is_dir() and p.name != "issues")


def test_every_demo_has_an_issue() -> None:
    assert {"buggy-calculator", "shopping-cart"} <= set(DEMOS)
    for name in DEMOS:
        assert (EXAMPLES / "issues" / f"{name}.md").is_file(), name


@pytest.mark.parametrize("name", DEMOS)
def test_demo_goes_from_red_to_green(name: str) -> None:
    issue = (EXAMPLES / "issues" / f"{name}.md").read_text(encoding="utf-8")
    result = run_task(EXAMPLES / name, issue, settings=MOCK)

    assert result.status is RunStatus.COMPLETED, result.summary
    assert result.tests_passed is True
    first_test = next(s for s in result.steps if s.tool == "run_tests")
    assert "exit_code=0" not in first_test.observation  # the bug reproduces first


def test_shopping_cart_needs_two_iterations() -> None:
    issue = (EXAMPLES / "issues" / "shopping-cart.md").read_text(encoding="utf-8")
    result = run_task(EXAMPLES / "shopping-cart", issue, settings=MOCK)

    assert result.changed_files == ["shopcart/models.py", "shopcart/pricing.py"]
    tools = [s.tool for s in result.steps]
    assert tools.count("replace_in_file") == 2
    assert tools.count("run_tests") == 3  # reproduce, still red after fix 1, green after fix 2
    assert "2 edit/test iterations" in result.summary
    assert "+        return self.unit_price * self.quantity" in result.diff
    # the bundled demo itself is never modified
    original = (EXAMPLES / "shopping-cart" / "shopcart" / "models.py").read_text()
    assert "unit_price + self.quantity" in original


def test_find_suggestions_keeps_reading_order() -> None:
    issue = "Change `b = 2` to `b = 3`. Also `a = 1` should be `a = 0`; replace `c` with `d`."
    assert find_suggestions(issue) == [("b = 2", "b = 3"), ("a = 1", "a = 0"), ("c", "d")]
    assert find_suggestions("nothing concrete here") == []
