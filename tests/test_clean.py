import text_cleanup
from text_cleanup import Vocabulary, clean, clean_segments


def vocab_file(tmp_path, content="Corkie = Corky, core key\n"):
    path = tmp_path / "vocabulary.txt"
    path.write_text(content)
    return Vocabulary(str(path))


def test_vocabulary_then_numbers(tmp_path):
    result = clean("Pin it to Corky at four point two volts.", vocab_file(tmp_path))
    assert result.text == "Pin it to Corkie at 4.2 volts."
    assert result.changes == (("Corky", "Corkie"), ("four point two", "4.2"))


def test_numbers_only_without_vocabulary():
    assert clean("two options").text == "2 options"


def test_never_raises(monkeypatch, caplog):
    def boom(text):
        raise RuntimeError("bug in a rule")

    monkeypatch.setattr(text_cleanup, "convert_numbers", boom)
    result = clean("four point two volts")
    assert result.text == "four point two volts"
    assert result.changes == ()
    assert "number stage) failed" in caplog.text


def test_vocabulary_failure_does_not_stop_numbers(tmp_path, monkeypatch, caplog):
    vocab = vocab_file(tmp_path)

    def boom():
        raise RuntimeError("bad vocabulary")

    monkeypatch.setattr(vocab, "rules", boom)
    result = clean("two options", vocab)
    assert result.text == "2 options"
    assert result.changes == (("two", "2"),)
    assert "vocabulary" in caplog.text


def test_number_failure_keeps_vocabulary_fixes(tmp_path, monkeypatch):
    def boom(text):
        raise RuntimeError("bug in a rule")

    monkeypatch.setattr(text_cleanup, "convert_numbers", boom)
    result = clean("Corky has two tabs", vocab_file(tmp_path))
    assert result.text == "Corkie has two tabs"
    assert result.changes == (("Corky", "Corkie"),)


def test_clean_segments_in_place(tmp_path):
    segments = [
        {"start": 0.0, "end": 1.0, "segment": "core key has two tabs"},
        {"start": 1.0, "end": 2.0, "segment": "nothing here"},
    ]
    changes = clean_segments(segments, vocab_file(tmp_path))
    assert [s["segment"] for s in segments] == ["Corkie has 2 tabs", "nothing here"]
    assert segments[0]["start"] == 0.0
    assert changes == [("core key", "Corkie"), ("two", "2")]
