import json
import base58
import pytest

from sam.integrations.solana.solana_tools import SolanaTools


def test_solana_private_key_base58_roundtrip():
    from solders.keypair import Keypair

    kp = Keypair()
    # Keypair API may differ; skip if to_bytes is unavailable
    if not hasattr(kp, "to_bytes"):
        import pytest

        pytest.skip("Keypair.to_bytes() not available in this solders version")
    secret_bytes = kp.to_bytes()
    secret_b58 = base58.b58encode(secret_bytes).decode()

    tools = SolanaTools("https://api.mainnet-beta.solana.com", private_key=secret_b58)
    assert tools.keypair is not None
    assert isinstance(tools.wallet_address, str)
    assert len(tools.wallet_address) >= 32


def test_solana_private_key_json_array():
    from solders.keypair import Keypair

    kp = Keypair()
    if not hasattr(kp, "to_bytes"):
        import pytest

        pytest.skip("Keypair.to_bytes() not available in this solders version")
    secret_bytes = kp.to_bytes()
    arr = list(secret_bytes)
    secret_json = json.dumps(arr)

    tools = SolanaTools("https://api.mainnet-beta.solana.com", private_key=secret_json)
    assert tools.keypair is not None
    assert isinstance(tools.wallet_address, str)
    assert len(tools.wallet_address) >= 32
