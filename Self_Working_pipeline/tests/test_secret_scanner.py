from pathlib import Path

from core.secret_scanner import scan_for_secrets


def test_secret_scanner_detects_live_like_keys(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    fake_key = "sk-" + ("A" * 24)
    target.write_text(f"OPENAI_API_KEY={fake_key}\n", encoding="utf-8")

    findings = scan_for_secrets(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "sample.txt"


def test_secret_scanner_ignores_env_example(tmp_path: Path) -> None:
    target = tmp_path / ".env.example"
    fake_key = "sk-" + ("A" * 24)
    target.write_text(f"OPENAI_API_KEY={fake_key}\n", encoding="utf-8")

    findings = scan_for_secrets(tmp_path)

    assert findings == []
