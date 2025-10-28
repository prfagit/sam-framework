import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sam.integrations.payai_facilitator import PayAIFacilitatorTools


@pytest.mark.asyncio
async def test_payai_tools_requires_configuration():
    tools = PayAIFacilitatorTools(base_url=None, default_network="solana")
    result = await tools.verify_payment(
        {"payment_payload": {"x402Version": 1}, "payment_requirements": {"scheme": "exact"}}
    )
    assert "error" in result
    assert "not configured" in result["error"].lower()


@pytest.mark.asyncio
async def test_payai_verify_payment_success():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")
    payload = {"x402Version": 1, "scheme": "exact"}
    requirements = {"scheme": "exact"}
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
    assert kwargs["json"]["paymentPayload"]["network"] == "solana"
    assert kwargs["json"]["paymentRequirements"]["network"] == "solana"


@pytest.mark.asyncio
async def test_payai_verify_payment_error():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")
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
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")

    curated_payload = {
        "items": [
            {
                "resource": "https://x402.payai.network/api/solana/paid-content",
                "accepts": [{"network": "solana", "scheme": "exact"}],
            }
        ],
        "x402Version": 1,
    }

    with patch.object(
        PayAIFacilitatorTools,
        "_curated_echo_resources",
        new=AsyncMock(return_value=curated_payload),
    ):
        result = await tools.discover_resources(
            {"metadata": {"provider": "Echo Merchant"}, "limit": 5}
        )

    assert "items" in result
    # When using curated resources, the request bypasses the API call
    # so we just verify the result structure
    assert len(result["items"]) > 0
    assert result["x402Version"] == 1


@pytest.mark.asyncio
async def test_payai_get_payment_requirements_prefers_default_network():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")

    discover_payload = {
        "x402Version": 1,
        "items": [
            {
                "resource": "https://x402.payai.network/api/solana/paid-content",
                "accepts": [
                    {"network": "solana", "scheme": "exact", "maxAmountRequired": "10"},
                    {"network": "base", "scheme": "exact", "maxAmountRequired": "20"},
                ],
            }
        ],
        "pagination": {"limit": 10, "offset": 0},
    }

    with patch.object(
        PayAIFacilitatorTools,
        "_curated_echo_resources",
        new=AsyncMock(return_value=discover_payload),
    ):
        result = await tools.get_payment_requirements(
            {"resource": "https://x402.payai.network/api/solana/paid-content"}
        )

    assert result["network"] == "solana"
    assert result["payment_requirements"]["maxAmountRequired"] == "10"


@pytest.mark.asyncio
async def test_payai_get_payment_requirements_fallback_hits_resource():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")

    with patch(
        "sam.integrations.payai_facilitator.PayAIFacilitatorTools.discover_resources",
        new=AsyncMock(return_value={"items": []}),
    ):
        mock_response = MagicMock()
        mock_response.status = 402
        mock_response.json = AsyncMock(
            return_value={
                "accepts": [
                    {
                        "scheme": "exact",
                        "network": "solana",
                        "maxAmountRequired": "100",
                        "payTo": "Foo",
                        "asset": "Bar",
                    }
                ]
            }
        )

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_cm

        with patch(
            "sam.integrations.payai_facilitator.get_session",
            new=AsyncMock(return_value=mock_session),
        ):
            result = await tools.get_payment_requirements(
                {"resource": "https://x402.payai.network/api/solana/paid-content"}
            )

    assert result["network"] == "solana"
    assert result["payment_requirements"]["maxAmountRequired"] == "100"


@pytest.mark.asyncio
async def test_payai_auto_pay_resource_flow():
    solana_tools = MagicMock()
    solana_tools.keypair = MagicMock()

    tools = PayAIFacilitatorTools(
        base_url="https://facilitator.test",
        default_network="solana",
        solana_tools=solana_tools,
    )

    tools.get_payment_requirements = AsyncMock(
        return_value={
            "network": "solana",
            "payment_requirements": {
                "scheme": "exact",
                "network": "solana",
                "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "payTo": "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4",
                "maxAmountRequired": "10000",
                "extra": {"feePayer": "2wKupLR9q6wXYppw8Gr2NvWxKBUqm4PPJKkQfoxHDBg4"},
            },
        }
    )
    tools._build_solana_payment_transaction = AsyncMock(
        return_value={"transaction": "dHJhbnNhY3Rpb24="}
    )
    tools.verify_payment = AsyncMock(return_value={"verification": {"isValid": True}})
    tools.settle_payment = AsyncMock(
        return_value={"settlement": {"success": True, "transaction": "abc123"}}
    )

    result = await tools.pay_resource(
        {"resource": "https://x402.payai.network/api/solana/paid-content"}
    )

    assert result.get("success") is True
    tools._build_solana_payment_transaction.assert_awaited()
    tools.verify_payment.assert_awaited()
    tools.settle_payment.assert_awaited()


@pytest.mark.asyncio
async def test_payai_auto_pay_requires_solana_wallet():
    tools = PayAIFacilitatorTools(base_url="https://facilitator.test", default_network="solana")
    result = await tools.pay_resource(
        {"resource": "https://x402.payai.network/api/solana/paid-content"}
    )
    assert "error" in result
    assert "wallet" in result.get("error", "").lower()
