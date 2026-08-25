"""Tool registry, search parsing, and conversation trimming."""
from jarvis.brain import tools
from jarvis.brain.agent import _starts_with_tool_result
from jarvis.brain.prompts import build_system_prompt
from jarvis.brain.tools.web import _clean_ddg_url, _parse_ddg, _strip_tags


def test_every_tool_has_a_valid_schema():
    for schema in tools.schemas():
        assert schema["name"] and schema["description"]
        assert schema["input_schema"]["type"] == "object"
        # Every required field must actually be declared.
        properties = schema["input_schema"]["properties"]
        for field in schema["input_schema"]["required"]:
            assert field in properties, f"{schema['name']}: '{field}' required but not defined"


def test_core_tools_are_registered():
    names = tools.tool_names()
    for expected in ("organize_files", "web_search", "find_files", "undo_last_organize",
                     "open_application", "search_web_in_browser"):
        assert expected in names


def test_dispatch_unknown_tool_is_graceful():
    assert "don't have a tool" in tools.dispatch("nonexistent", {}, {})


def test_dispatch_catches_tool_exceptions():
    # Missing required argument - must come back as text, not raise.
    result = tools.dispatch("move_file", {}, {"files": {"safe_roots": []}})
    assert "failed" in result.lower()


def test_organize_schema_documents_dry_run():
    schema = next(s for s in tools.schemas() if s["name"] == "organize_files")
    assert "dry_run" in schema["input_schema"]["properties"]
    assert "dry_run=true" in schema["description"]


def test_system_prompt_names_the_safe_roots():
    cfg = {
        "assistant": {"name": "JARVIS", "address_user_as": "sir"},
    }
    prompt = build_system_prompt(cfg, ["/home/tony/Downloads"])
    assert "/home/tony/Downloads" in prompt
    assert "sir" in prompt


def test_ddg_redirect_urls_are_unwrapped():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert _clean_ddg_url(wrapped) == "https://example.com/page"


def test_plain_urls_pass_through():
    assert _clean_ddg_url("https://example.com/x") == "https://example.com/x"


def test_ddg_regex_fallback_parses_results():
    page = '''
    <div class="result"><a class="result__a" href="https://example.com/a">First result</a>
    <a class="result__snippet">A <b>snippet</b> of text</a></div>
    <div class="result"><a class="result__a" href="https://example.com/b">Second</a>
    <a class="result__snippet">More text</a></div>
    '''
    results = _parse_ddg(page, max_results=5)
    assert len(results) >= 2
    assert results[0]["title"] == "First result"
    assert results[0]["url"] == "https://example.com/a"
    assert "snippet" in results[0]["snippet"]


def test_strip_tags_unescapes_entities():
    assert _strip_tags("<b>caf&eacute;</b> &amp; bar") == "café & bar"


def test_orphaned_tool_result_is_detected():
    assert _starts_with_tool_result({"content": [{"type": "tool_result", "content": "x"}]})
    assert not _starts_with_tool_result({"content": [{"type": "text", "text": "hi"}]})
    assert not _starts_with_tool_result({"content": "plain string"})
