"""Type stubs for dexscreener package."""

from typing import List, Optional, Any

class Token:
    address: str
    name: str
    symbol: str

class PriceChange:
    h24: Optional[float]

class Volume:
    h24: Optional[float]

class Liquidity:
    usd: Optional[float]

class TokenPair:
    chain_id: str
    dex_id: str
    pair_address: str
    base_token: Token
    quote_token: Token
    price_usd: Optional[float]
    price_change: Optional[PriceChange]
    volume: Optional[Volume]
    liquidity: Optional[Liquidity]
    market_cap: Optional[float]
    pair_created_at: Optional[str]

class DexscreenerClient:
    def __init__(self) -> None: ...
    def search_pairs(self, query: str) -> List[TokenPair]: ...
    def get_tokens(self, addresses: List[str]) -> List[TokenPair]: ...
    def get_token_pairs(self, address: str) -> List[TokenPair]: ...
    def get_pairs_by_chain_and_address(self, chain_id: str, pair_address: str) -> TokenPair: ...
    def get_latest_token_profiles(self) -> List[Any]: ...
