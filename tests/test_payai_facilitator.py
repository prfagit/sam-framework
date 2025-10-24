import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sam.integrations.payai_facilitator import PayAIFacilitatorTools


@pytest.mark.asyncio
async def test_payai_tools_requires_configuration():
    tools = PayAIFacilitatorTools(base_url=None)
    result = await tools.verify_payment(
        {"payment_payload": {"x402Version": 1}, "payment_requirements": {"scheme": "exact"}}
    )
    assert "error" in result
    assert "not configured" in result["error"].lower()


@pytest.mark.asyncio
async def test_payai_verify_payment_success():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test")
    payload = {"x402Version": 1, "scheme": "exact"}
    requirements = {"scheme": "exact", "network": "solana"}
    expected = {"isValid": True, "payer": "test"}

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=json.dumps(expected))

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.request.return_value = mock_cm

    with patch(
        "sam.integrations.payai_facilitator.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_get_session.return_value = mock_session
        result = await tools.verify_payment(
            {"payment_payload": payload, "payment_requirements": requirements}
        )

    assert result["verification"] == expected
    args, kwargs = mock_session.request.call_args
    assert args[0] == "POST"
    assert args[1].endswith("/verify")
    assert kwargs["json"]["paymentPayload"] == payload


@pytest.mark.asyncio
async def test_payai_verify_payment_error():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test")
    payload = {"x402Version": 1, "scheme": "exact"}
    requirements = {"scheme": "exact"}

    mock_response = MagicMock()
    mock_response.status = 400
    mock_response.text = AsyncMock(return_value="bad request")

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.request.return_value = mock_cm

    with patch(
        "sam.integrations.payai_facilitator.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_get_session.return_value = mock_session
        result = await tools.verify_payment(
            {"payment_payload": payload, "payment_requirements": requirements}
        )

    assert "error" in result
    assert "status 400" in result["error"]


@pytest.mark.asyncio
async def test_payai_discover_resources_metadata():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test")

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(
        return_value=json.dumps(
            {"x402Version": 1, "items": [], "pagination": {"limit": 5, "offset": 0}}
        )
    )

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.request.return_value = mock_cm

    with patch(
        "sam.integrations.payai_facilitator.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_get_session.return_value = mock_session
        result = await tools.discover_resources(
            {"metadata": {"provider": "Echo Merchant"}, "limit": 5}
        )

    assert "items" in result
    _, kwargs = mock_session.request.call_args
    params = kwargs["params"]
    assert params["limit"] == 5
    assert params["metadata[provider]"] == "Echo Merchant"
