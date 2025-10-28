import base64
import json
import pytest

from sam.integrations.aixbt import (
    AixbtClient,
    AixbtError,
    AixbtTools,
    IndigoAgentInput,
    IndigoMessage,
    IndigoResult,
    ProjectsInput,
    _summarize_project,
)


class StubAixbtClient:
    def __init__(self) -> None:
        self.last_params = None
        self.last_messages = None
        self.projects: list[dict[str, object]] = []
        self.meta: dict[str, object] = {}
        self.indigo_response: dict[str, object] = {"text": "Example narrative"}
        self.payment = None
        self.raise_error: Exception | None = None
        self._has_wallet = True

    async def list_projects(self, params: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        if self.raise_error:
            raise self.raise_error
        self.last_params = params
        return self.projects, self.meta

    async def query_indigo(self, messages: list[dict[str, str]]) -> IndigoResult:
        if self.raise_error:
            raise self.raise_error
        self.last_messages = messages
        return IndigoResult(result=self.indigo_response, payment=self.payment)

    @property
    def has_wallet(self) -> bool:
        return self._has_wallet


def test_projects_input_aliases():
    filters = ProjectsInput(limit=10, x_handle="@aixbt", sort_by="score", min_score=0.5)
    params = filters.model_dump(by_alias=True, exclude_none=True)
    assert params["xHandle"] == "@aixbt"
    assert params["sortBy"] == "score"
    assert params["minScore"] == 0.5
    assert params["limit"] == 10


def test_projects_input_requires_messages_or_prompt():
    with pytest.raises(ValueError):
        IndigoAgentInput()

    payload = IndigoAgentInput(prompt="What narratives are emerging?")
    assert payload.messages and payload.messages[0].role == "user"
    assert payload.messages[0].content == "What narratives are emerging?"


def test_summarize_project_drops_empty_fields():
    raw = {
        "name": "Symbiotic",
        "ticker": "SYMB",
        "score": 97.5,
        "popularityScore": 88.0,
        "rationale": "Restaking momentum accelerating across chains.",
        "links": [],
        "url": None,
    }
    summary = _summarize_project(raw)
    assert summary["name"] == "Symbiotic"
    assert "links" not in summary
    assert "url" not in summary


@pytest.mark.asyncio
async def test_aixbt_tools_projects_success():
    client = StubAixbtClient()
    client.projects = [
        {"name": "Symbiotic", "ticker": "SYMB", "score": 97.1, "rationale": "Cross-chain restaking."}
    ]
    client.meta = {"limit": 1}
    tools = AixbtTools(client)

    result = await tools.list_top_projects({"limit": 1})

    assert result["count"] == 1
    assert result["projects"][0]["ticker"] == "SYMB"
    assert result["filters"]["limit"] == 1
    assert client.last_params == {"limit": 1}


@pytest.mark.asyncio
async def test_aixbt_tools_projects_surface_errors():
    client = StubAixbtClient()
    client.raise_error = AixbtError("missing credentials")
    tools = AixbtTools(client)

    result = await tools.list_top_projects({"limit": 5})
    assert "error" in result
    assert "missing credentials" in result["error"]


@pytest.mark.asyncio
async def test_aixbt_tools_require_private_key():
    client = StubAixbtClient()
    client._has_wallet = False
    tools = AixbtTools(client)

    result = await tools.list_top_projects({"limit": 1})
    assert "error" in result
    assert "AIXBT_PRIVATE_KEY" in result["error"]


@pytest.mark.asyncio
async def test_aixbt_tools_indigo_uses_prompt_conversion():
    client = StubAixbtClient()
    tools = AixbtTools(client)

    result = await tools.indigo_research({"prompt": "Identify Base narratives."})

    assert result["response"]["text"] == "Example narrative"
    assert client.last_messages == [{"role": "user", "content": "Identify Base narratives."}]


def test_aixbt_client_parse_payment_decodes_header():
    client = AixbtClient()
    payload = {"transactionHash": "0xabc"}
    header_value = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    decoded = client._parse_payment({"x-payment-response": header_value})
    assert decoded == payload

    # Fallback to raw header when decoding fails
    decoded_raw = client._parse_payment({"x-payment-response": "not-base64"})
    assert decoded_raw == {"raw": "not-base64"}
