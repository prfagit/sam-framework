from pydantic import BaseModel, field_validator, ConfigDict
from typing import Any, Dict
import re


class SolanaAddress(BaseModel):
    """Validate Solana wallet/token addresses."""
    address: str
    
    @field_validator('address')
    @classmethod
    def validate_solana_address(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError('Address must be a string')
        
        # Solana addresses are base58 encoded, typically 32-44 characters
        if not (32 <= len(v) <= 44):
            raise ValueError('Invalid Solana address length')
        
        # Check for valid base58 characters
        base58_pattern = r'^[1-9A-HJ-NP-Za-km-z]+$'
        if not re.match(base58_pattern, v):
            raise ValueError('Invalid Solana address format')
        
        return v


class TradeAmount(BaseModel):
    """Validate trade amounts."""
    amount: float
    
    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Amount must be positive')
        
        if v > 1000:  # Safety limit
            raise ValueError('Amount exceeds safety limit of 1000 SOL')
        
        return v


class SlippageTolerance(BaseModel):
    """Validate slippage tolerance."""
    slippage: int
    
    @field_validator('slippage')
    @classmethod
    def validate_slippage(cls, v: int) -> int:
        if not (0 <= v <= 50):
            raise ValueError('Slippage must be between 0 and 50 percent')
        
        return v


class SellPercentage(BaseModel):
    """Validate percentage of holdings to sell."""
    percentage: int
    
    @field_validator('percentage')
    @classmethod
    def validate_percentage(cls, v: int) -> int:
        if not (1 <= v <= 100):
            raise ValueError('Percentage must be between 1 and 100')
        
        return v


class SessionId(BaseModel):
    """Validate session ID."""
    session_id: str
    
    @field_validator('session_id')
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError('Session ID must be a string')
        
        if not (1 <= len(v) <= 100):
            raise ValueError('Session ID must be 1-100 characters')
        
        # Allow alphanumeric, dash, underscore
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('Session ID contains invalid characters')
        
        return v


class ToolArguments(BaseModel):
    """Base class for validating tool arguments."""
    model_config = ConfigDict(extra="forbid")  # Reject unknown fields


def validate_tool_input(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Validate tool input arguments based on tool type."""
    
    if tool_name == "get_balance":
        # No arguments needed for balance check
        return {}
    
    elif tool_name == "transfer_sol":
        validated = SolanaAddress(address=args.get("to_address", ""))
        amount = TradeAmount(amount=args.get("amount", 0))
        return {
            "to_address": validated.address,
            "amount": amount.amount
        }
    
    elif tool_name == "pump_fun_buy":
        validated_address = SolanaAddress(address=args.get("mint", ""))
        validated_amount = TradeAmount(amount=args.get("amount", 0))
        validated_slippage = SlippageTolerance(slippage=args.get("slippage", 1))
        
        result = {
            "mint": validated_address.address,
            "amount": validated_amount.amount,
            "slippage": validated_slippage.slippage
        }
        
        if "public_key" in args:
            public_key = SolanaAddress(address=args["public_key"])
            result["public_key"] = public_key.address
        
        return result
    
    elif tool_name == "pump_fun_sell":
        validated_address = SolanaAddress(address=args.get("mint", ""))
        validated_percentage = SellPercentage(percentage=args.get("percentage", 100))
        validated_slippage = SlippageTolerance(slippage=args.get("slippage", 1))
        
        result = {
            "mint": validated_address.address,
            "percentage": validated_percentage.percentage,
            "slippage": validated_slippage.slippage
        }
        
        if "public_key" in args:
            public_key = SolanaAddress(address=args["public_key"])
            result["public_key"] = public_key.address
        
        return result
    
    elif tool_name == "get_token_data":
        validated = SolanaAddress(address=args.get("address", ""))
        return {"address": validated.address}
    
    else:
        # For unknown tools, return args as-is but log warning
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"No validation defined for tool: {tool_name}")
        return args