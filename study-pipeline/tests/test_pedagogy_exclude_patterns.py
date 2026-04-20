from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verifier import _load_pedagogy_rules, check_pedagogy


def _run(line: str) -> dict:
    rules = _load_pedagogy_rules()
    return check_pedagogy(line, rules)


def test_lone_pair_negation_context_passes() -> None:
    result = _run("lone pair는 결합에 참여하지 않는 전자쌍이다.")
    assert result["pass"] is True
    assert result["issues"] == []


def test_lp_bp_repulsion_comparison_passes() -> None:
    result = _run("LP-BP 반발은 BP-BP 반발보다 크다.")
    assert result["pass"] is True
    assert result["issues"] == []


def test_lone_pair_equals_bonding_pair_fails() -> None:
    result = _run("lone pair는 bonding pair와 같다.")
    assert result["pass"] is False
    assert any(issue["problem"] == "lone pair와 bonding pair를 혼동한 표현" for issue in result["issues"])


def test_lone_pair_forms_bond_fails() -> None:
    result = _run("lone pair가 bond를 형성한다.")
    assert result["pass"] is False
    assert any("lone pair" in issue["text"].lower() for issue in result["issues"])
