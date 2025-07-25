"""Tests for the Ollama integration."""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from freezegun.api import FrozenDateTimeFactory
from ollama import Message, ResponseError
import pytest
from syrupy.assertion import SnapshotAssertion
import voluptuous as vol

from homeassistant.components import conversation, ollama
from homeassistant.components.conversation import trace
from homeassistant.const import ATTR_SUPPORTED_FEATURES, CONF_LLM_HASS_API, MATCH_ALL
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    intent,
    llm,
)

from tests.common import MockConfigEntry


@pytest.fixture(autouse=True)
def mock_ulid_tools():
    """Mock generated ULIDs for tool calls."""
    with patch("homeassistant.helpers.llm.ulid_now", return_value="mock-tool-call"):
        yield


async def stream_generator(response: dict | list[dict]) -> AsyncGenerator[dict]:
    """Generate a response from the assistant."""
    if not isinstance(response, list):
        response = [response]
    for msg in response:
        yield msg


@pytest.mark.parametrize("agent_id", [None, "conversation.ollama_conversation"])
async def test_chat(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
    agent_id: str,
) -> None:
    """Test that the chat function is called with the appropriate arguments."""

    if agent_id is None:
        agent_id = mock_config_entry.entry_id

    entry = MockConfigEntry()
    entry.add_to_hass(hass)

    with patch(
        "ollama.AsyncClient.chat",
        return_value=stream_generator(
            {"message": {"role": "assistant", "content": "test response"}}
        ),
    ) as mock_chat:
        result = await conversation.async_converse(
            hass,
            "test message",
            None,
            Context(),
            agent_id=agent_id,
        )

        assert mock_chat.call_count == 1
        args = mock_chat.call_args.kwargs
        prompt = args["messages"][0]["content"]

        assert args["model"] == "test_model:latest"
        assert args["messages"] == [
            Message(role="system", content=prompt),
            Message(role="user", content="test message"),
        ]

        assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
            result
        )
        assert result.response.speech["plain"]["speech"] == "test response"

    # Test Conversation tracing
    traces = trace.async_get_traces()
    assert traces
    last_trace = traces[-1].as_dict()
    trace_events = last_trace.get("events", [])
    assert [event["event_type"] for event in trace_events] == [
        trace.ConversationTraceEventType.ASYNC_PROCESS,
        trace.ConversationTraceEventType.AGENT_DETAIL,
    ]
    # AGENT_DETAIL event contains the raw prompt passed to the model
    detail_event = trace_events[1]
    assert "Current time is" in detail_event["data"]["messages"][0]["content"]


async def test_chat_stream(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
) -> None:
    """Test chat messages are assembled across streamed responses."""

    entry = MockConfigEntry()
    entry.add_to_hass(hass)

    with patch(
        "ollama.AsyncClient.chat",
        return_value=stream_generator(
            [
                {"message": {"role": "assistant", "content": "test "}},
                {
                    "message": {"role": "assistant", "content": "response"},
                    "done": True,
                    "done_reason": "stop",
                },
            ],
        ),
    ) as mock_chat:
        result = await conversation.async_converse(
            hass,
            "test message",
            None,
            Context(),
            agent_id=mock_config_entry.entry_id,
        )

        assert mock_chat.call_count == 1
        args = mock_chat.call_args.kwargs
        prompt = args["messages"][0]["content"]

        assert args["model"] == "test_model:latest"
        assert args["messages"] == [
            Message(role="system", content=prompt),
            Message(role="user", content="test message"),
        ]

        assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
            result
        )
        assert result.response.speech["plain"]["speech"] == "test response"


async def test_template_variables(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that template variables work."""
    context = Context(user_id="12345")
    mock_user = Mock()
    mock_user.id = "12345"
    mock_user.name = "Test User"

    subentry = next(iter(mock_config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        mock_config_entry,
        subentry,
        data={
            "prompt": (
                "The user name is {{ user_name }}. "
                "The user id is {{ llm_context.context.user_id }}."
            ),
            ollama.CONF_MODEL: "test_model:latest",
        },
    )
    with (
        patch("ollama.AsyncClient.list"),
        patch(
            "ollama.AsyncClient.chat",
            return_value=stream_generator(
                {"message": {"role": "assistant", "content": "test response"}}
            ),
        ) as mock_chat,
        patch("homeassistant.auth.AuthManager.async_get_user", return_value=mock_user),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        result = await conversation.async_converse(
            hass, "hello", None, context, agent_id=mock_config_entry.entry_id
        )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE, (
        result
    )

    args = mock_chat.call_args.kwargs
    prompt = args["messages"][0]["content"]

    assert "The user name is Test User." in prompt
    assert "The user id is 12345." in prompt


@pytest.mark.parametrize(
    ("tool_args", "expected_tool_args"),
    [
        ({"param1": "test_value"}, {"param1": "test_value"}),
        ({"param2": 2}, {"param2": 2}),
        (
            {"param1": "test_value", "floor": ""},
            {"param1": "test_value"},  # Omit empty arguments
        ),
        (
            {"domain": '["light"]'},
            {"domain": ["light"]},  # Repair invalid json arguments
        ),
        (
            {"domain": "['light']"},
            {"domain": "['light']"},  # Preserve invalid json that can't be parsed
        ),
    ],
)
@patch("homeassistant.components.ollama.entity.llm.AssistAPI._async_get_tools")
async def test_function_call(
    mock_get_tools,
    hass: HomeAssistant,
    mock_config_entry_with_assist: MockConfigEntry,
    mock_init_component,
    tool_args: dict[str, Any],
    expected_tool_args: dict[str, Any],
) -> None:
    """Test function call from the assistant."""
    agent_id = mock_config_entry_with_assist.entry_id
    context = Context()

    mock_tool = AsyncMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "Test function"
    mock_tool.parameters = vol.Schema(
        {vol.Optional("param1", description="Test parameters"): str},
        extra=vol.ALLOW_EXTRA,
    )
    mock_tool.async_call.return_value = "Test response"

    mock_get_tools.return_value = [mock_tool]

    def completion_result(*args, messages, **kwargs):
        for message in messages:
            if message["role"] == "tool":
                return stream_generator(
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I have successfully called the function",
                        }
                    }
                )

        return stream_generator(
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "test_tool",
                                "arguments": tool_args,
                            }
                        }
                    ],
                }
            }
        )

    with patch(
        "ollama.AsyncClient.chat",
        side_effect=completion_result,
    ) as mock_chat:
        result = await conversation.async_converse(
            hass,
            "Please call the test function",
            None,
            context,
            agent_id=agent_id,
        )

    assert mock_chat.call_count == 2
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert (
        result.response.speech["plain"]["speech"]
        == "I have successfully called the function"
    )
    mock_tool.async_call.assert_awaited_once_with(
        hass,
        llm.ToolInput(
            id="mock-tool-call",
            tool_name="test_tool",
            tool_args=expected_tool_args,
        ),
        llm.LLMContext(
            platform="ollama",
            context=context,
            language="en",
            assistant="conversation",
            device_id=None,
        ),
    )


@patch("homeassistant.components.ollama.entity.llm.AssistAPI._async_get_tools")
async def test_function_exception(
    mock_get_tools,
    hass: HomeAssistant,
    mock_config_entry_with_assist: MockConfigEntry,
    mock_init_component,
) -> None:
    """Test function call with exception."""
    agent_id = mock_config_entry_with_assist.entry_id
    context = Context()

    mock_tool = AsyncMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "Test function"
    mock_tool.parameters = vol.Schema(
        {vol.Optional("param1", description="Test parameters"): str}
    )
    mock_tool.async_call.side_effect = HomeAssistantError("Test tool exception")

    mock_get_tools.return_value = [mock_tool]

    def completion_result(*args, messages, **kwargs):
        for message in messages:
            if message["role"] == "tool":
                return stream_generator(
                    {
                        "message": {
                            "role": "assistant",
                            "content": "There was an error calling the function",
                        }
                    }
                )

        return stream_generator(
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "test_tool",
                                "arguments": {"param1": "test_value"},
                            }
                        }
                    ],
                }
            }
        )

    with patch(
        "ollama.AsyncClient.chat",
        side_effect=completion_result,
    ) as mock_chat:
        result = await conversation.async_converse(
            hass,
            "Please call the test function",
            None,
            context,
            agent_id=agent_id,
        )

    assert mock_chat.call_count == 2
    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert (
        result.response.speech["plain"]["speech"]
        == "There was an error calling the function"
    )
    mock_tool.async_call.assert_awaited_once_with(
        hass,
        llm.ToolInput(
            id="mock-tool-call",
            tool_name="test_tool",
            tool_args={"param1": "test_value"},
        ),
        llm.LLMContext(
            platform="ollama",
            context=context,
            language="en",
            assistant="conversation",
            device_id=None,
        ),
    )


async def test_unknown_hass_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    mock_init_component,
) -> None:
    """Test when we reference an API that no longer exists."""
    subentry = next(iter(mock_config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        mock_config_entry,
        subentry,
        data={
            **subentry.data,
            CONF_LLM_HASS_API: "non-existing",
        },
    )
    await hass.async_block_till_done()

    result = await conversation.async_converse(
        hass,
        "hello",
        "1234",
        Context(),
        agent_id=mock_config_entry.entry_id,
    )

    assert result == snapshot


async def test_message_history_trimming(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that a single message history is trimmed according to the config."""
    response_idx = 0

    def response(*args, **kwargs) -> dict:
        nonlocal response_idx
        response_idx += 1
        return stream_generator(
            {"message": {"role": "assistant", "content": f"response {response_idx}"}}
        )

    with patch(
        "ollama.AsyncClient.chat",
        side_effect=response,
    ) as mock_chat:
        # mock_init_component sets "max_history" to 2
        for i in range(5):
            result = await conversation.async_converse(
                hass,
                f"message {i + 1}",
                conversation_id="1234",
                context=Context(),
                agent_id=mock_config_entry.entry_id,
            )
            assert (
                result.response.response_type == intent.IntentResponseType.ACTION_DONE
            ), result

        assert mock_chat.call_count == 5
        args = mock_chat.call_args_list
        prompt = args[0].kwargs["messages"][0]["content"]

        # system + user-1
        assert len(args[0].kwargs["messages"]) == 2
        assert args[0].kwargs["messages"][1]["content"] == "message 1"

        # Full history
        # system + user-1 + assistant-1 + user-2
        assert len(args[1].kwargs["messages"]) == 4
        assert args[1].kwargs["messages"][0]["role"] == "system"
        assert args[1].kwargs["messages"][0]["content"] == prompt
        assert args[1].kwargs["messages"][1]["role"] == "user"
        assert args[1].kwargs["messages"][1]["content"] == "message 1"
        assert args[1].kwargs["messages"][2]["role"] == "assistant"
        assert args[1].kwargs["messages"][2]["content"] == "response 1"
        assert args[1].kwargs["messages"][3]["role"] == "user"
        assert args[1].kwargs["messages"][3]["content"] == "message 2"

        # Full history
        # system + user-1 + assistant-1 + user-2 + assistant-2 + user-3
        assert len(args[2].kwargs["messages"]) == 6
        assert args[2].kwargs["messages"][0]["role"] == "system"
        assert args[2].kwargs["messages"][0]["content"] == prompt
        assert args[2].kwargs["messages"][1]["role"] == "user"
        assert args[2].kwargs["messages"][1]["content"] == "message 1"
        assert args[2].kwargs["messages"][2]["role"] == "assistant"
        assert args[2].kwargs["messages"][2]["content"] == "response 1"
        assert args[2].kwargs["messages"][3]["role"] == "user"
        assert args[2].kwargs["messages"][3]["content"] == "message 2"
        assert args[2].kwargs["messages"][4]["role"] == "assistant"
        assert args[2].kwargs["messages"][4]["content"] == "response 2"
        assert args[2].kwargs["messages"][5]["role"] == "user"
        assert args[2].kwargs["messages"][5]["content"] == "message 3"

        # Trimmed down to two user messages.
        # system + user-2 + assistant-2 + user-3 + assistant-3 + user-4
        assert len(args[3].kwargs["messages"]) == 6
        assert args[3].kwargs["messages"][0]["role"] == "system"
        assert args[3].kwargs["messages"][0]["content"] == prompt
        assert args[3].kwargs["messages"][1]["role"] == "user"
        assert args[3].kwargs["messages"][1]["content"] == "message 2"
        assert args[3].kwargs["messages"][2]["role"] == "assistant"
        assert args[3].kwargs["messages"][2]["content"] == "response 2"
        assert args[3].kwargs["messages"][3]["role"] == "user"
        assert args[3].kwargs["messages"][3]["content"] == "message 3"
        assert args[3].kwargs["messages"][4]["role"] == "assistant"
        assert args[3].kwargs["messages"][4]["content"] == "response 3"
        assert args[3].kwargs["messages"][5]["role"] == "user"
        assert args[3].kwargs["messages"][5]["content"] == "message 4"

        # Trimmed down to two user messages.
        # system + user-3 + assistant-3 + user-4 + assistant-4 + user-5
        assert len(args[3].kwargs["messages"]) == 6
        assert args[4].kwargs["messages"][0]["role"] == "system"
        assert args[4].kwargs["messages"][0]["content"] == prompt
        assert args[4].kwargs["messages"][1]["role"] == "user"
        assert args[4].kwargs["messages"][1]["content"] == "message 3"
        assert args[4].kwargs["messages"][2]["role"] == "assistant"
        assert args[4].kwargs["messages"][2]["content"] == "response 3"
        assert args[4].kwargs["messages"][3]["role"] == "user"
        assert args[4].kwargs["messages"][3]["content"] == "message 4"
        assert args[4].kwargs["messages"][4]["role"] == "assistant"
        assert args[4].kwargs["messages"][4]["content"] == "response 4"
        assert args[4].kwargs["messages"][5]["role"] == "user"
        assert args[4].kwargs["messages"][5]["content"] == "message 5"


async def test_message_history_unlimited(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_init_component
) -> None:
    """Test that message history is not trimmed when max_history = 0."""
    conversation_id = "1234"

    def stream(*args, **kwargs) -> AsyncGenerator[dict]:
        return stream_generator(
            {"message": {"role": "assistant", "content": "test response"}}
        )

    with (
        patch("ollama.AsyncClient.chat", side_effect=stream) as mock_chat,
    ):
        subentry = next(iter(mock_config_entry.subentries.values()))
        hass.config_entries.async_update_subentry(
            mock_config_entry,
            subentry,
            data={**subentry.data, ollama.CONF_MAX_HISTORY: 0},
        )
        for i in range(100):
            result = await conversation.async_converse(
                hass,
                f"message {i + 1}",
                conversation_id=conversation_id,
                context=Context(),
                agent_id=mock_config_entry.entry_id,
            )
            assert (
                result.response.response_type == intent.IntentResponseType.ACTION_DONE
            ), result

        args = mock_chat.call_args_list
        assert len(args) == 100
        recorded_messages = args[-1].kwargs["messages"]
        message_count = sum(
            (message["role"] == "user") for message in recorded_messages
        )
        assert message_count == 100


async def test_error_handling(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_init_component
) -> None:
    """Test error handling during converse."""
    with patch(
        "ollama.AsyncClient.chat",
        new_callable=AsyncMock,
        side_effect=ResponseError("test error"),
    ):
        result = await conversation.async_converse(
            hass, "hello", None, Context(), agent_id=mock_config_entry.entry_id
        )

    assert result.response.response_type == intent.IntentResponseType.ERROR, result
    assert result.response.error_code == "unknown", result


async def test_template_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that template error handling works."""
    subentry = next(iter(mock_config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        mock_config_entry,
        subentry,
        data={
            **subentry.data,
            "prompt": "talk like a {% if True %}smarthome{% else %}pirate please.",
        },
    )
    with patch(
        "ollama.AsyncClient.list",
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        result = await conversation.async_converse(
            hass, "hello", None, Context(), agent_id=mock_config_entry.entry_id
        )

    assert result.response.response_type == intent.IntentResponseType.ERROR, result
    assert result.response.error_code == "unknown", result


async def test_conversation_agent(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test OllamaConversationEntity."""
    agent = conversation.get_agent_manager(hass).async_get_agent(
        mock_config_entry.entry_id
    )
    assert agent.supported_languages == MATCH_ALL

    state = hass.states.get("conversation.ollama_conversation")
    assert state
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == 0

    entity_entry = entity_registry.async_get("conversation.ollama_conversation")
    assert entity_entry
    subentry = mock_config_entry.subentries.get(entity_entry.unique_id)
    assert subentry

    device_entry = device_registry.async_get(entity_entry.device_id)
    assert device_entry

    assert device_entry.identifiers == {(ollama.DOMAIN, subentry.subentry_id)}
    assert device_entry.name == subentry.title
    assert device_entry.manufacturer == "Ollama"
    assert device_entry.entry_type == dr.DeviceEntryType.SERVICE

    model, _, version = subentry.data[ollama.CONF_MODEL].partition(":")
    assert device_entry.model == model
    assert device_entry.sw_version == version


async def test_conversation_agent_with_assist(
    hass: HomeAssistant,
    mock_config_entry_with_assist: MockConfigEntry,
    mock_init_component,
) -> None:
    """Test OllamaConversationEntity."""
    agent = conversation.get_agent_manager(hass).async_get_agent(
        mock_config_entry_with_assist.entry_id
    )
    assert agent.supported_languages == MATCH_ALL

    state = hass.states.get("conversation.ollama_conversation")
    assert state
    assert (
        state.attributes[ATTR_SUPPORTED_FEATURES]
        == conversation.ConversationEntityFeature.CONTROL
    )


@pytest.mark.parametrize(
    ("mock_config_entry_options", "expected_options"),
    [
        ({}, {"num_ctx": 8192}),
        ({"num_ctx": 16384}, {"num_ctx": 16384}),
    ],
)
async def test_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
    expected_options: dict[str, Any],
) -> None:
    """Test that options are passed correctly to ollama client."""
    with patch(
        "ollama.AsyncClient.chat",
        return_value=stream_generator(
            {"message": {"role": "assistant", "content": "test response"}}
        ),
    ) as mock_chat:
        await conversation.async_converse(
            hass,
            "test message",
            None,
            Context(),
            agent_id="conversation.ollama_conversation",
        )

        assert mock_chat.call_count == 1
        args = mock_chat.call_args.kwargs
        assert args.get("options") == expected_options


@pytest.mark.parametrize(
    "think",
    [False, True],
    ids=["no_think", "think"],
)
async def test_reasoning_filter(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_init_component,
    think: bool,
) -> None:
    """Test that think option is passed correctly to client."""

    agent_id = mock_config_entry.entry_id
    entry = MockConfigEntry()
    entry.add_to_hass(hass)

    subentry = next(iter(mock_config_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        mock_config_entry,
        subentry,
        data={
            **subentry.data,
            ollama.CONF_THINK: think,
        },
    )

    with patch(
        "ollama.AsyncClient.chat",
        return_value=stream_generator(
            {"message": {"role": "assistant", "content": "test response"}}
        ),
    ) as mock_chat:
        await conversation.async_converse(
            hass,
            "test message",
            None,
            Context(),
            agent_id=agent_id,
        )

        # Assert called with the expected think value
        for call in mock_chat.call_args_list:
            kwargs = call.kwargs
            assert kwargs.get("think") == think
