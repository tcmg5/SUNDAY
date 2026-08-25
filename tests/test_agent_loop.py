"""The tool-use loop, driven by a stubbed Claude client.

No network. We script the model's responses and assert that the loop calls the
right tools, feeds results back correctly, and terminates.
"""
import copy
from dataclasses import dataclass

import pytest

from jarvis.brain.agent import MAX_TOOL_ROUNDS, Agent


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str = "tu_1"
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        # Snapshot: the agent mutates its message list in place, so a live
        # reference would show us the state after the call, not during it.
        self.calls.append({**kwargs, "messages": copy.deepcopy(kwargs["messages"])})
        return self.script.pop(0) if self.script else FakeResponse([TextBlock("Done.")])


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path / "Downloads"
    root.mkdir()
    return {
        "assistant": {
            "name": "JARVIS", "address_user_as": "sir", "model": "claude-opus-5",
            "max_tokens": 1024, "history_turns": 4,
        },
        "files": {
            "safe_roots": [str(root)], "confirm_threshold": 25, "use_trash": True,
            "journal_path": str(tmp_path / "journal.jsonl"),
        },
        "secrets": {"anthropic_api_key": "sk-ant-test"},
        "_downloads": root,
    }


def make_agent(cfg, script):
    agent = Agent.__new__(Agent)  # bypass __init__, which builds a real client
    agent.cfg = cfg
    agent.model = cfg["assistant"]["model"]
    agent.max_tokens = cfg["assistant"]["max_tokens"]
    agent.history_turns = cfg["assistant"]["history_turns"]
    agent.messages = []
    agent.system_prompt = "test"
    agent.client = FakeClient(script)
    return agent


def test_plain_answer_returns_text(cfg):
    agent = make_agent(cfg, [FakeResponse([TextBlock("Seventeen degrees and clear.")])])
    assert agent.ask("what's the weather") == "Seventeen degrees and clear."


def test_missing_api_key_is_a_clear_error(cfg):
    cfg["secrets"]["anthropic_api_key"] = ""
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Agent(cfg)


def test_tool_call_is_executed_and_fed_back(cfg):
    (cfg["_downloads"] / "photo.jpg").write_text("x")
    script = [
        FakeResponse(
            [ToolUseBlock("inspect_directory", {"directory": str(cfg["_downloads"])})],
            stop_reason="tool_use",
        ),
        FakeResponse([TextBlock("One image in there, sir.")]),
    ]
    agent = make_agent(cfg, script)
    assert agent.ask("what's in my downloads") == "One image in there, sir."

    # The second API call must carry the tool result back to the model.
    second_call = agent.client.messages.calls[1]
    tool_results = [
        block
        for message in second_call["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_results) == 1
    assert "Images: 1" in tool_results[0]["content"]
    assert tool_results[0]["tool_use_id"] == "tu_1"


def test_on_tool_callback_fires(cfg):
    script = [
        FakeResponse([ToolUseBlock("get_system_status", {})], stop_reason="tool_use"),
        FakeResponse([TextBlock("All nominal.")]),
    ]
    agent = make_agent(cfg, script)
    seen = []
    agent.ask("status", on_tool=lambda name, args: seen.append(name))
    assert seen == ["get_system_status"]


def test_tools_are_offered_to_the_model(cfg):
    agent = make_agent(cfg, [FakeResponse([TextBlock("ok")])])
    agent.ask("hello")
    offered = {t["name"] for t in agent.client.messages.calls[0]["tools"]}
    assert "organize_files" in offered and "web_search" in offered


def test_runaway_tool_loop_terminates(cfg):
    """A model that only ever calls tools must not spin forever."""
    script = [
        FakeResponse([ToolUseBlock("get_system_status", {})], stop_reason="tool_use")
        for _ in range(MAX_TOOL_ROUNDS + 5)
    ]
    agent = make_agent(cfg, script)
    result = agent.ask("loop please")
    assert "stuck in a loop" in result
    assert len(agent.client.messages.calls) == MAX_TOOL_ROUNDS


def test_history_is_trimmed_but_stays_valid(cfg):
    """Trimming must never leave a tool_result as the first message."""
    agent = make_agent(cfg, [])
    agent.messages = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    agent.messages.insert(
        12, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "y"}]}
    )
    agent._trim()
    assert len(agent.messages) <= agent.history_turns * 2
    first = agent.messages[0]["content"]
    if isinstance(first, list):
        assert first[0].get("type") != "tool_result"


def test_short_history_is_left_alone(cfg):
    agent = make_agent(cfg, [])
    agent.messages = [{"role": "user", "content": "hi"}]
    agent._trim()
    assert len(agent.messages) == 1


def test_conversation_accumulates_across_turns(cfg):
    agent = make_agent(cfg, [
        FakeResponse([TextBlock("First.")]),
        FakeResponse([TextBlock("Second.")]),
    ])
    agent.ask("one")
    agent.ask("two")
    sent = agent.client.messages.calls[1]["messages"]
    assert sent[0]["content"] == "one"
    assert len(sent) == 3  # user, assistant, user


def test_reset_clears_history(cfg):
    agent = make_agent(cfg, [FakeResponse([TextBlock("ok")])])
    agent.ask("hello")
    agent.reset()
    assert agent.messages == []
