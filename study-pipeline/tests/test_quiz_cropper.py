from pathlib import Path

import quiz_cropper


def test_crop_textbook_problems_fallback_when_textbook_missing(config):
    result = quiz_cropper.crop_textbook_problems("organic_chem", "ch1", config)
    assert result["status"] == "skipped"
    assert result["reason"] == "textbook_path_missing"
    assert result["count"] == 0


class _DummyPixmap:
    def save(self, _path: str) -> None:
        raise AssertionError("should not save image when no pattern matches")


class _DummyPage:
    def get_text(self, mode: str):
        assert mode == "blocks"
        return [(0, 0, 10, 10, "just ordinary paragraph")]

    def get_pixmap(self, clip=None, dpi: int = 220):
        return _DummyPixmap()


class _DummyDoc:
    def __len__(self) -> int:
        return 1

    def __getitem__(self, _idx: int):
        return _DummyPage()

    def close(self) -> None:
        return None


def test_crop_textbook_problems_fallback_when_pattern_match_zero(config, monkeypatch, tmp_path):
    subject_dir = Path(config["vault_path"]) / config["notes_dir"] / "유기화학"
    subject_dir.mkdir(parents=True, exist_ok=True)
    dummy_pdf = subject_dir / "PDF" / "dummy.pdf"
    dummy_pdf.parent.mkdir(parents=True, exist_ok=True)
    dummy_pdf.write_bytes(b"%PDF-1.4\n")

    config["subjects"]["organic_chem"]["textbook"] = "PDF/dummy.pdf"
    config["pipeline_dir"] = str(tmp_path)

    class _DummyFitz:
        @staticmethod
        def open(_path: str):
            return _DummyDoc()

        @staticmethod
        def Rect(x0: float, y0: float, x1: float, y1: float):
            return (x0, y0, x1, y1)

    monkeypatch.setattr(quiz_cropper, "fitz", _DummyFitz)

    result = quiz_cropper.crop_textbook_problems("organic_chem", "ch1", config)
    assert result["status"] == "no_matches"
    assert result["reason"] == "pattern_match_0"
    assert result["count"] == 0
