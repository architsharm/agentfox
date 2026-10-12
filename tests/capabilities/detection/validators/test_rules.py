"""Rule validators ported from Guardrails AI: text, structure, sql, web, disclosure, lists.

Every example here is written for this file; none is taken from a benchmark.
"""

from __future__ import annotations

import pytest

from agentfox.capabilities.detection.validators import (
    CheckContext,
    check,
    get_validator,
)


def _run(name, text, params=None, ctx=None):
    return check(name, text, params, ctx)


def _spans(name, text, params=None, ctx=None):
    return [text[f.start : f.end] for f in _run(name, text, params, ctx)]


def _passes(name, text, params=None, ctx=None):
    return _run(name, text, params, ctx) == []


# ------------------------------------------------------------------------ text


def test_regex_match_fullmatch_and_search():
    assert _passes("regex_match", "AB-123", {"regex": r"[A-Z]{2}-\d+"})
    assert not _passes("regex_match", "id AB-123", {"regex": r"[A-Z]{2}-\d+"})
    assert _passes("regex_match", "id AB-123", {"regex": r"[A-Z]{2}-\d+", "match_type": "search"})


def test_regex_match_rejects_bad_pattern():
    with pytest.raises(ValueError):
        get_validator("regex_match").params({"regex": "(unclosed"})


def test_contains_string():
    assert _passes("contains_string", "order ref: X1", {"substring": "ref:"})
    assert not _passes("contains_string", "order X1", {"substring": "ref:"})


def test_ends_with_multichar_suffix():
    # Upstream compared only the last character, so this always failed.
    assert _passes("ends_with", "Thanks, Support Team", {"end": "Support Team"})
    assert not _passes("ends_with", "Thanks", {"end": "Support Team"})
    assert not _passes("ends_with", "", {"end": "."})


def test_case_checks_point_at_offending_character():
    assert _passes("lowercase", "all quiet here")
    assert _spans("lowercase", "all Quiet") == ["Q"]
    assert _passes("uppercase", "LOUD 123")
    assert _spans("uppercase", "LOUd") == ["d"]


def test_one_line():
    assert _passes("one_line", "just one line")
    assert _spans("one_line", "first\nsecond\nthird") == ["second\nthird"]


def test_two_words():
    assert _passes("two_words", "hello there")
    assert not _passes("two_words", "hello")
    assert not _passes("two_words", "one two three")


def test_valid_length_chars_and_items():
    assert _passes("valid_length", "abcde", {"min": 2, "max": 5})
    assert not _passes("valid_length", "a", {"min": 2})
    assert _spans("valid_length", "abcdefg", {"max": 5}) == ["fg"]
    assert _passes("valid_length", "[1, 2]", {"max": 2, "unit": "items"})
    assert not _passes("valid_length", "[1, 2, 3]", {"max": 2, "unit": "items"})
    assert not _passes("valid_length", "not a list", {"max": 2, "unit": "items"})
    with pytest.raises(ValueError):
        get_validator("valid_length").params({"min": 5, "max": 1})


def test_valid_choice():
    assert _passes("valid_choice", "  yes \n", {"choices": ["yes", "no"]})
    assert not _passes("valid_choice", "maybe", {"choices": ["yes", "no"]})


def test_valid_range():
    assert _passes("valid_range", "7", {"min": 1, "max": 10})
    assert _passes("valid_range", "2.5", {"min": 1})
    assert not _passes("valid_range", "11", {"max": 10})
    assert not _passes("valid_range", "seven", {"max": 10})
    # Upstream cast the bound to int for an int value, so 5 passed min=5.5.
    assert not _passes("valid_range", "5", {"min": 5.5})


def test_reading_time():
    assert _passes("reading_time", "word " * 100, {"reading_time": 1})
    assert not _passes("reading_time", "word " * 450, {"reading_time": 2})


def test_reading_level():
    easy = "The cat sat. The dog ran. We had fun."
    hard = (
        "Notwithstanding contemporaneous jurisprudential considerations, institutional "
        "accountability necessitates comprehensive organizational transformation."
    )
    assert _passes("reading_level", easy, {"min": 0, "max": 6})
    assert not _passes("reading_level", hard, {"min": 0, "max": 8})
    assert not _passes("reading_level", easy, {"min": 6, "max": 12})


def test_syllable_heuristic():
    from agentfox.capabilities.detection.validators.builtin.text import syllables

    assert syllables("cat") == 1
    assert syllables("make") == 1
    assert syllables("table") == 2
    assert syllables("organization") >= 4


def test_redundant_sentences_spans_the_repeat():
    text = "The parcel ships on Monday. Our store opens at nine. The parcel ships on Monday!"
    assert _spans("redundant_sentences", text) == ["The parcel ships on Monday!"]
    assert _passes("redundant_sentences", "Red apples are sweet. Trains run late at night.")
    assert _passes("redundant_sentences", "")


def test_cucumber_expression_match():
    pytest.importorskip("cucumber_expressions")
    params = {"expression": "I buy {int} apple(s)"}
    assert _passes("cucumber_expression_match", "I buy 3 apples", params)
    assert not _passes("cucumber_expression_match", "I buy many melons", params)


# ------------------------------------------------------------------- structure


def test_valid_json():
    assert _passes("valid_json", '{"a": [1, 2]}')
    # Upstream rejected falsy documents; these are all valid JSON.
    for doc in ("0", "false", "null", "[]", "{}", '""'):
        assert _passes("valid_json", doc), doc
    [f] = _run("valid_json", '{"a": 1,}')
    assert f.start > 0
    assert not _passes("valid_json", '{"a": ')


def test_valid_python():
    assert _passes("valid_python", "def add(a, b):\n    return a + b\n")
    [f] = _run("valid_python", "def add(a, b:\n    return a\n")
    assert f.end > f.start
    assert not _passes("valid_python", "for x in\n")


def test_valid_url():
    assert _passes("valid_url", "https://example.org/path?q=1")
    assert not _passes("valid_url", "example.org/path")
    assert not _passes("valid_url", "http://")


def test_has_url_flags_urls_and_domains():
    text = "Read https://docs.example.org/guide or visit sample.net today."
    assert _spans("has_url", text) == ["https://docs.example.org", "sample.net"]
    assert _passes("has_url", "No links in this sentence at all.")
    # File names are not links, and agent replies carry links routinely, so this runs
    # only as a rule someone chose, not on every request.
    assert _passes("has_url", "Edit main.py and notes.txt.")
    assert get_validator("has_url").describe()["detector"] is False


def test_valid_html():
    assert _passes("valid_html", "<div><p>hello</p><br><img src='a.png'></div>")
    assert _spans("valid_html", "<div><p>hello</div>") == ["</div>"]
    assert _spans("valid_html", "<section><p>open</p>") == ["<section>"]
    assert not _passes("valid_html", "</p>")


def test_valid_open_api_spec():
    pytest.importorskip("jsonschema")
    pytest.importorskip("yaml")
    good = "openapi: 3.0.3\ninfo:\n  title: Pets\n  version: '1.0'\npaths:\n  /pets: {}\n"
    assert _passes("valid_open_api_spec", good)
    assert not _passes("valid_open_api_spec", '{"openapi": "3.0.3", "paths": {}}')
    assert not _passes("valid_open_api_spec", "just prose")


def test_valid_address_reads_api_response():
    from agentfox.capabilities.detection.validators.builtin.structure import ValidAddress

    def response(**kw):
        comps = [{"componentType": "route", **kw}, {"componentType": "postal_code"}]
        return {
            "result": {
                "verdict": {},
                "address": {"addressComponents": comps, "formattedAddress": "1 Main St"},
            }
        }

    assert ValidAddress.outcome(response()) == []
    assert ValidAddress.outcome(response(inferred=True))
    assert ValidAddress.outcome(response(spellCorrected=True))
    unconfirmed = response()
    unconfirmed["result"]["verdict"]["hasUnconfirmedComponents"] = True
    assert ValidAddress.outcome(unconfirmed)


def test_network_validators_are_gated_on_egress(monkeypatch):
    from agentfox.capabilities.detection.validators.builtin import structure

    monkeypatch.setattr(structure, "_egress_allowed", lambda: False)
    for name in ("valid_address", "endpoint_is_reachable"):
        v = get_validator(name)
        assert not v.available()
        assert v.unavailable_reason()
    with pytest.raises(RuntimeError):
        _run("endpoint_is_reachable", "https://example.org")


def test_endpoint_is_reachable_refuses_non_http_and_internal(monkeypatch):
    from agentfox.capabilities.detection.validators.builtin import structure

    monkeypatch.setattr(structure, "_egress_allowed", lambda: True)
    assert _run("endpoint_is_reachable", "file:///etc/hosts")[0].reason == "not an http(s) URL"
    [f] = _run("endpoint_is_reachable", "http://127.0.0.1:9/")
    assert "inside the network" in f.reason


# ------------------------------------------------------------------------- sql


def test_valid_sql():
    pytest.importorskip("sqlglot")
    assert _passes("valid_sql", "SELECT id, name FROM customers WHERE id = 4")
    assert _passes("valid_sql", "SELECT 1; UPDATE t SET a = 2", {"dialect": "postgres"})
    [f] = _run("valid_sql", "SELECT id FROM customers WHERE")
    assert f.end > f.start
    assert not _passes("valid_sql", "please list the customers")
    assert not _passes("valid_sql", "SELECT (id FROM t")
    with pytest.raises(ValueError):
        get_validator("valid_sql").params({"dialect": "no-such-dialect"})


def test_exclude_sql_predicates_text_and_tool_args():
    pytest.importorskip("sqlglot")
    params = {"predicates": ["Drop", "Delete"]}
    assert _passes("exclude_sql_predicates", "SELECT * FROM t", params)
    [f] = _run("exclude_sql_predicates", "DROP TABLE accounts", params)
    assert f.detail["predicate"] == "Drop"
    args = '{"sql": "DELETE FROM accounts", "limit": 5}'
    assert _run("exclude_sql_predicates", args, params, CheckContext(surface="tool_args"))
    with pytest.raises(ValueError):
        get_validator("exclude_sql_predicates").params({"predicates": ["NotAThing"]})


def test_sql_column_presence():
    pytest.importorskip("sqlglot")
    params = {"cols": ["id", "name"]}
    assert _passes("sql_column_presence", "SELECT id, name FROM people WHERE id = 3", params)
    [f] = _run("sql_column_presence", "SELECT id, salary FROM people", params)
    assert f.detail["columns"] == ["salary"]


# ------------------------------------------------------------------------- web


def test_web_sanitization_spans():
    text = (
        'Hi <img src=x onerror=alert(1)> <a href="javascript:void(0)">x</a> '
        "<script>run()</script> <iframe srcdoc='x'></iframe>"
    )
    spans = _spans("web_sanitization", text)
    assert "<img src=x onerror=" in spans
    assert "javascript:" in spans
    assert "<script>" in spans
    assert "<iframe" in spans
    assert any("srcdoc" in s for s in spans)
    assert _passes("web_sanitization", "Use <b>bold</b> & the expression (a + b) here.")
    assert _spans("web_sanitization", '<p style="width: expression(go())">') == ["expression("]
    assert _spans("web_sanitization", "<a href='data:text/html,hi'>")
    assert get_validator("web_sanitization").owasp_id == "LLM05"


def test_internal_domains_on_host_boundaries():
    params = {"internal_domains": ["corp.example.com"]}
    text = (
        "See https://wiki.corp.example.com/onboarding. Unrelated: notcorp.example.com, "
        "corp.example.company and https://example.com. Ask ops@corp.example.com."
    )
    assert _spans("internal_domains", text, params) == [
        "https://wiki.corp.example.com/onboarding",
        "ops@corp.example.com",
    ]
    assert _passes("internal_domains", "Visit https://www.example.com", params)
    assert _spans("internal_domains", "host: corp.example.com", params) == ["corp.example.com"]


# ------------------------------------------------------------------ disclosure

PROMPT = (
    "You are Pip, the assistant for a garden supply store. Never mention supplier "
    "names or wholesale prices. Recommend only products from the current catalogue "
    "and answer in two sentences or fewer."
)


def test_system_prompt_leak_run_span():
    out = (
        "My rules: never mention supplier names or wholesale prices. Recommend only "
        "products from the current catalogue."
    )
    [f] = _run("system_prompt_leak", out, {"system_prompt": PROMPT})
    assert out[f.start : f.end].lower().startswith("never mention supplier")
    assert f.detail["words"] >= 8


def test_system_prompt_leak_passes_ordinary_answer():
    out = "Tomato seeds are in aisle four, and the store opens at nine."
    assert _passes("system_prompt_leak", out, {"system_prompt": PROMPT})


def test_system_prompt_leak_canary_not_in_reason():
    params = {"system_prompt": PROMPT, "canaries": ["cnry-7f3a9"]}
    [f] = _run("system_prompt_leak", "debug: cnry-7f3a9", params)
    assert "cnry-7f3a9" not in f.reason
    assert "debug: cnry-7f3a9"[f.start : f.end] == "cnry-7f3a9"


def test_system_prompt_leak_share_without_a_long_run():
    # Phrases of the prompt, reordered and broken up so no run reaches 8 words.
    out = (
        "answer in two sentences or fewer. Also: the assistant for a garden supply. "
        "And: from the current catalogue and answer. Plus: or wholesale prices. Recommend only"
    )
    params = {"system_prompt": PROMPT, "threshold": 0.2, "min_overlap_words": 12}
    findings = _run("system_prompt_leak", out, params)
    assert findings and "share" in findings[0].detail
    assert findings[0].detail["share"] >= 0.2


# ------------------------------------------------------------------------ lists


def test_mentions_drugs_multiword_and_boundaries():
    text = "Mix acetic acid carefully; ask about Zyflo CR and aspirin."
    assert _spans("mentions_drugs", text) == ["acetic acid", "Zyflo CR", "aspirin"]
    assert _passes("mentions_drugs", "We sell garden tools and seeds.")


def test_drug_list_loaded_from_data_file():
    from agentfox.capabilities.detection.validators.builtin.lists import drug_names

    names = drug_names()
    assert len(names) > 1000
    assert not any(n.startswith("#") for n in names)


def test_quotes_price():
    assert _spans("quotes_price", "That will be $1,299.50 total.") == ["$1,299.50"]
    assert _passes("quotes_price", "That will be about twelve dollars.")
    assert _passes("quotes_price", "Shipping is A$15.")
    assert _spans("quotes_price", "Shipping is A$15.", {"currency": "AUD"}) == ["A$15"]
    assert _spans("quotes_price", "Only \u20ac 20", {"currency": "EUR"}) == ["\u20ac 20"]


def test_competitor_check_word_boundaries_and_text_offsets():
    params = {"competitors": ["Globex", "Initech"]}
    text = "First sentence here. Globex is cheaper. Globexia is a town; initech too."
    findings = _run("competitor_check", text, params)
    # Upstream's spans were per-sentence offsets; these index the whole text. With
    # no spaCy model the plain match stands; with one, NER may drop "initech".
    assert findings[0].start == text.index("Globex")
    assert {text[f.start : f.end].lower() for f in findings} <= {"globex", "initech"}
    assert all(f.start != text.index("Globexia") for f in findings)
    assert _passes("competitor_check", "We compare favourably with nobody.", params)


def test_secrets_present():
    pytest.importorskip("detect_secrets")
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    text = f"config:\naws_access_key_id = {key}\n"
    findings = _run("secrets_present", text)
    assert findings and all(key not in f.reason for f in findings)
    assert _passes("secrets_present", "nothing to see here\n")


# ------------------------------------------------------------------ registry


@pytest.mark.parametrize(
    "name,entity",
    [
        ("regex_match", "FORMAT."),
        ("valid_sql", "CODE."),
        ("exclude_sql_predicates", "ACTION.SQL_PREDICATE"),
        ("web_sanitization", "CODE.XSS"),
        ("internal_domains", "DISCLOSURE.INTERNAL_DOMAIN"),
        ("system_prompt_leak", "DISCLOSURE.SYSTEM_PROMPT"),
        ("mentions_drugs", "SAFETY.DRUGS"),
        ("quotes_price", "BRAND.PRICE_QUOTE"),
        ("competitor_check", "BRAND.COMPETITOR"),
        ("secrets_present", "SECRET.DETECT_SECRETS"),
    ],
)
def test_registered_with_entity(name, entity):
    v = get_validator(name)
    assert v is not None and v.entity_type.startswith(entity)
    assert v.upstream and v.upstream.startswith("guardrails-ai/")
    v.describe()  # schema renders
