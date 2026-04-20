from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verifier


def _pedagogy_rules() -> list[dict[str, object]]:
    return verifier._load_pedagogy_rules(SCRIPTS_DIR / "templates" / "pedagogy_rules.yaml")


def test_lone_pair_negation_sentence_is_excluded() -> None:
    result = verifier.check_pedagogy("lone pair는 결합에 참여하지 않는 전자쌍이다.", _pedagogy_rules())
    assert result["pass"] is True


def test_vsepr_lp_bp_repulsion_sentence_is_excluded() -> None:
    result = verifier.check_pedagogy("LP-BP 반발은 BP-BP 반발보다 크다.", _pedagogy_rules())
    assert result["pass"] is True


def test_explicit_confusion_still_fails() -> None:
    result = verifier.check_pedagogy("lone pair는 bonding pair와 동일하다.", _pedagogy_rules())
    assert result["pass"] is False


def test_wrong_claim_about_bond_formation_still_fails() -> None:
    result = verifier.check_pedagogy("lone pair가 직접 bond를 형성한다.", _pedagogy_rules())
    assert result["pass"] is False
