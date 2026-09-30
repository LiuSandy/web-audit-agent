"""Tests for exploratory agent LangSmith trace metadata."""

from src.agents.exploratory import build_step_metadata
from src.types.index import OrderedSet


def test_build_step_metadata_captures_step_state():
    state = {"steps": 3, "visitedUrls": OrderedSet(["https://a", "https://b"]),
             "todoQueue": ["https://c"]}
    metadata = build_step_metadata("session-1", state, "https://a")
    assert metadata == {"sessionId": "session-1", "step": 3, "url": "https://a",
                        "visitedCount": 2, "queueLength": 1}


def test_build_step_metadata_defaults_empty_session_id():
    state = {"steps": 1, "visitedUrls": OrderedSet(), "todoQueue": []}
    metadata = build_step_metadata(None, state, "https://x")
    assert metadata["sessionId"] == ""
    assert metadata["step"] == 1
    assert metadata["visitedCount"] == 0
    assert metadata["queueLength"] == 0


def test_step_and_execute_action_are_traceable_wrapped():
    import src.agents.exploratory as exploratory
    for method in ("_step", "execute_action", "perform_automatic_bug_scanning", "generate_tests"):
        wrapped = getattr(exploratory.ExploratoryAgent, method)
        assert getattr(wrapped, "__langsmith_traceable__", False) or \
            getattr(wrapped, "__wrapped__", None) is not None, \
            f"ExploratoryAgent.{method} 应被 @traceable 包装"
