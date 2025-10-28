import base64
import json
from typing import Any

import pytest

from sam.integrations.coinbase_x402 import CoinbaseX402Tools

from x402.types import (  # type: ignore[import-untyped]
    DiscoveryResourcesPagination,
    DiscoveredResource,
    ListDiscoveryResourcesRequest,
    ListDiscoveryResourcesResponse,
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    VerifyResponse,
)


class StubFacilitator:
    async def list(self, request):
        item = DiscoveredResource(
            resource="https://api.example.com/x402/paid",
            type="http",
            x402_version=1,
            accepts=[
                PaymentRequirements(
                    scheme="exact",
                    network="base",
                    max_amount_required="500000",
                    resource="https://api.example.com/x402/paid",
                    description="Example resource",
                    mime_type="application/json",
                    pay_to="0x0000000000000000000000000000000000000001",
                    max_timeout_seconds=60,
                    asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                )
            ],
            metadata={"category": "demo"},
            last_updated="2025-01-01T00:00:00Z",
        )
        pagination = DiscoveryResourcesPagination(limit=request.limit or 20, offset=request.offset or 0, total=1)
        return ListDiscoveryResourcesResponse(x402_version=1, items=[item], pagination=pagination)

    async def verify(self, payment: PaymentPayload, requirements: PaymentRequirements) -> VerifyResponse:
        return VerifyResponse(is_valid=True, invalid_reason=None, payer=payment.payload.authorization.to)

    async def settle(self, payment: PaymentPayload, requirements: PaymentRequirements) -> SettleResponse:
        return SettleResponse(success=True, payer=payment.payload.authorization.to, transaction="0xabc")


class StubAccount:
    def __init__(self, address: str) -> None:
        self.address = address


class StubResponse:
    def __init__(self, status_code: int, data: dict[str, str], payment: dict[str, str]) -> None:
        self.status_code = status_code
        self._data = data
        encoded = base64.b64encode(json.dumps(payment).encode("utf-8")).decode("ascii")
        self.headers = {"x-payment-response": encoded, "content-type": "application/json"}

    def json(self) -> dict[str, str]:
        return self._data

    @property
    def text(self) -> str:
        return json.dumps(self._data)


class StubHttpClient:
    def __init__(self, response: StubResponse) -> None:
        self._response = response
        self.request_args: dict[str, Any] | None = None

    async def request(self, method: str, path: str, **kwargs):
        self.request_args = {"method": method, "path": path, **kwargs}
        return self._response


class StubClientContext:
    def __init__(self, client: StubHttpClient) -> None:
        self._client = client

    async def __aenter__(self) -> StubHttpClient:
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def build_client_factory(response: StubResponse):
    client = StubHttpClient(response)

    def _factory(account, base_url, timeout):
        return StubClientContext(client)

    _factory.client = client  # type: ignore[attr-defined]
    return _factory


@pytest.mark.asyncio
async def test_coinbase_x402_list_resources_success():
    tools = CoinbaseX402Tools(facilitator=StubFacilitator(), account=StubAccount("0xabc"))
    result = await tools.list_resources({"limit": 5})
    assert result["pagination"]["limit"] == 5
    assert result["items"]
    assert result["items"][0]["resource"].startswith("https://api.example.com")


@pytest.mark.asyncio
async def test_coinbase_x402_verify_and_settle():
    facilitator = StubFacilitator()
    tools = CoinbaseX402Tools(facilitator=facilitator, account=StubAccount("0xabc"))

    requirements = facilitator.list(ListDiscoveryResourcesRequest(limit=1))  # type: ignore
    requirements = await requirements
    req = requirements.items[0].accepts[0]

    payload = PaymentPayload(  # type: ignore
        x402_version=1,
        scheme="exact",
        network="base",
        payload={
            "signature": "0x",
            "authorization": {
                "from": "0xabc",
                "to": req.pay_to,
                "value": "1",
                "valid_after": "0",
                "valid_before": "9999999999",
                "nonce": "0x01",
            },
        },
    )

    verify = await tools.verify_payment(
        {
            "payment_payload": json.loads(payload.model_dump_json()),
            "payment_requirements": json.loads(req.model_dump_json()),
        }
    )
    assert verify.get("is_valid") is True

    settle = await tools.settle_payment(
        {
            "payment_payload": json.loads(payload.model_dump_json()),
            "payment_requirements": json.loads(req.model_dump_json()),
        }
    )
    assert settle.get("success") is True


@pytest.mark.asyncio
async def test_coinbase_x402_auto_pay_requires_wallet():
    tools = CoinbaseX402Tools(facilitator=None, account=None)
    result = await tools.auto_pay({"url": "https://api.example.com/paid"})
    assert "error" in result
    assert "private key" in result["error"].lower()


@pytest.mark.asyncio
async def test_coinbase_x402_auto_pay_success(monkeypatch):
    response = StubResponse(200, {"status": "ok"}, {"transaction": "0xabc"})
    factory = build_client_factory(response)
    tools = CoinbaseX402Tools(
        facilitator=None,
        account=StubAccount("0xabc"),
        client_factory=factory,
    )

    result = await tools.auto_pay({"url": "https://api.example.com/paid"})
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"
    assert result["payment_response"]["transaction"] == "0xabc"
    client_args = factory.client.request_args  # type: ignore[attr-defined]
    assert client_args["path"] == "/paid"
