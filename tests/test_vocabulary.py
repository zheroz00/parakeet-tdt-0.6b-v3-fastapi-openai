import logging
import os

from text_cleanup.vocabulary import Vocabulary, parse_vocabulary

SAMPLE = """
# Right spelling = misheard variants
Corkie = Corky, core key, corkey
the Corkie = the quirky
"""


def apply(content, text):
    return parse_vocabulary(content).apply(text)


def test_replaces_variants_case_insensitively():
    text, changes = apply(SAMPLE, "I opened corky and the CORE KEY.")
    assert text == "I opened Corkie and the Corkie."
    assert changes == [("corky", "Corkie"), ("CORE KEY", "Corkie")]


def test_whole_words_only():
    assert apply(SAMPLE, "corkys corkyness")[0] == "corkys corkyness"


def test_possessive_follows():
    assert apply(SAMPLE, "Corky's code tab")[0] == "Corkie's code tab"


def test_multiword_variant_tolerates_extra_spaces():
    assert apply(SAMPLE, "the core   key app")[0] == "the Corkie app"


def test_context_rule_only_fixes_in_context():
    text = "It's quirky. Check the quirky now."
    assert apply(SAMPLE, text)[0] == "It's quirky. Check the Corkie now."


def test_keeps_sentence_start_capital():
    assert apply(SAMPLE, "The quirky is up.")[0] == "The Corkie is up."


def test_longer_variant_wins():
    rules = "Big = core\nCorkie = core key"
    assert apply(rules, "the core key")[0] == "the Corkie"


def test_unchanged_text_reports_nothing():
    assert apply("Corkie = corkie", "Corkie") == ("Corkie", [])


def test_bad_lines_are_skipped_and_logged(caplog):
    content = "bad line\n = nothing on the left\nNothing on the right =\nCorkie = Corky\n"
    with caplog.at_level(logging.WARNING):
        rules = parse_vocabulary(content, source="test.txt")
    assert rules.apply("Corky")[0] == "Corkie"
    assert len([r for r in caplog.records if "skipped" in r.message]) == 3


def test_empty_file_means_no_rules():
    assert apply("# only comments\n\n", "Corky stays") == ("Corky stays", [])


def test_missing_file_means_no_rules(tmp_path, caplog):
    vocab = Vocabulary(str(tmp_path / "missing.txt"))
    with caplog.at_level(logging.WARNING):
        assert vocab.rules().apply("Corky")[0] == "Corky"
        vocab.rules()
    assert len([r for r in caplog.records if "not found" in r.message]) == 1


def test_reloads_when_file_changes(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Corkie = Corky\n")
    vocab = Vocabulary(str(path))
    assert vocab.rules().apply("Corky core key")[0] == "Corkie core key"

    path.write_text("Corkie = Corky, core key\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert vocab.rules().apply("Corky core key")[0] == "Corkie Corkie"


def test_unreadable_file_keeps_previous_rules(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Corkie = Corky\n")
    vocab = Vocabulary(str(path))
    assert vocab.rules().apply("Corky")[0] == "Corkie"

    path.write_bytes(b"\xff\xfe not utf-8 \xff")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert vocab.rules().apply("Corky")[0] == "Corkie"
