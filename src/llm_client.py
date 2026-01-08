"""
Unified LLM Client for local Mistral and Venice.ai API.

Supports:
- Local Mistral via llama.cpp /completion endpoint
- Venice.ai via OpenAI-compatible /chat/completions endpoint

Includes comprehensive error handling, retry logic, and structured response parsing.
"""

import os
import httpx
import logging
from typing import Optional, Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass
from enum import Enum

from src.config import get_config

logger = logging.getLogger(__name__)


# ============================================================================
# Backend Types
# ============================================================================

class LLMBackend(str, Enum):
    LOCAL = "local"
    VENICE = "venice"


# ============================================================================
# Response Models
# ============================================================================

class MistralTimings(BaseModel):
    """Timing information from Mistral response."""
    predicted_ms: Optional[float] = None
    predicted_n: Optional[int] = None
    predicted_per_second: Optional[float] = None
    prompt_ms: Optional[float] = None
    prompt_n: Optional[int] = None
    prompt_per_second: Optional[float] = None


class MistralResponse(BaseModel):
    """Structured response from LLM API."""
    content: str = Field(description="Generated text response")
    tokens_predicted: int = Field(description="Number of tokens generated")
    tokens_evaluated: int = Field(description="Number of prompt tokens processed")
    timings: Optional[MistralTimings] = Field(default=None, description="Performance timings")


# ============================================================================
# Exceptions
# ============================================================================

class MistralError(Exception):
    """Base exception for LLM client errors."""
    pass


class MistralConnectionError(MistralError):
    """Raised when cannot connect to LLM server."""
    pass


class MistralTimeoutError(MistralError):
    """Raised when request times out."""
    pass


class MistralResponseError(MistralError):
    """Raised when response is malformed or invalid."""
    pass


# ============================================================================
# Client Configuration
# ============================================================================

@dataclass
class ClientConfig:
    """Configuration for LLM client."""
    base_url: str
    backend: LLMBackend = LLMBackend.LOCAL
    api_key: Optional[str] = None
    model: str = "mistral-31-24b"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0


def get_client_config(backend: Optional[str] = None) -> ClientConfig:
    """
    Load client configuration from application config.
    
    Args:
        backend: Override backend selection ('local' or 'venice')
    """
    cfg = get_config()
    
    # Determine backend
    if backend is None:
        backend = os.environ.get("LLM_BACKEND", "local")
    
    if backend == "venice":
        api_key = os.environ.get("VENICE_API_KEY", "")
        return ClientConfig(
            base_url=os.environ.get("VENICE_API_URL", "https://api.venice.ai/api/v1"),
            backend=LLMBackend.VENICE,
            api_key=api_key,
            model=os.environ.get("VENICE_MODEL", "mistral-31-24b"),
            timeout_seconds=60.0,
            max_retries=3,
            retry_delay=1.0
        )
    
    # Local Mistral
    if os.environ.get("USE_TEST_DB") == "1" and cfg.test_mistral:
        base_url = cfg.test_mistral.url
    else:
        base_url = cfg.mistral.url
    
    return ClientConfig(
        base_url=base_url,
        backend=LLMBackend.LOCAL,
        timeout_seconds=30.0,
        max_retries=3,
        retry_delay=1.0
    )


# ============================================================================
# Core Client Functions
# ============================================================================

async def call_mistral(
    prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.7,
    stop: Optional[list[str]] = None,
    config: Optional[ClientConfig] = None
) -> MistralResponse:
    """
    Call LLM with the given prompt.
    
    Automatically routes to local Mistral or Venice.ai based on config.
    
    Args:
        prompt: The input text prompt
        max_tokens: Maximum number of tokens to generate (default: 512)
        temperature: Sampling temperature 0.0-2.0 (default: 0.7)
        stop: Optional list of stop sequences
        config: Optional client configuration (uses default if not provided)
        
    Returns:
        MistralResponse with generated text and metadata
        
    Raises:
        MistralConnectionError: Cannot connect to LLM server
        MistralTimeoutError: Request timed out
        MistralResponseError: Invalid or malformed response
        MistralError: Other unexpected errors
    """
    if config is None:
        config = get_client_config()
    
    # Validate inputs
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if not 0.0 <= temperature <= 2.0:
        raise ValueError("temperature must be between 0.0 and 2.0")
    
    # Route to appropriate backend
    if config.backend == LLMBackend.VENICE:
        return await _call_venice(prompt, max_tokens, temperature, stop, config)
    else:
        return await _call_local(prompt, max_tokens, temperature, stop, config)


async def _call_local(
    prompt: str,
    max_tokens: int,
    temperature: float,
    stop: Optional[list[str]],
    config: ClientConfig
) -> MistralResponse:
    """Call local Mistral via llama.cpp /completion endpoint."""
    
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "stream": False
    }
    
    if stop:
        payload["stop"] = stop
    
    last_error: Optional[Exception] = None
    
    for attempt in range(config.max_retries):
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(
                    f"{config.base_url}/completion",
                    json=payload
                )
                response.raise_for_status()
                return _parse_local_response(response.json())
                
        except httpx.ConnectError as e:
            last_error = MistralConnectionError(f"Cannot connect to Mistral at {config.base_url}: {e}")
            logger.warning(f"Connection attempt {attempt + 1}/{config.max_retries} failed: {e}")
            
        except httpx.TimeoutException as e:
            last_error = MistralTimeoutError(f"Request timed out after {config.timeout_seconds}s: {e}")
            logger.warning(f"Timeout attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise MistralResponseError(f"Client error {e.response.status_code}: {e.response.text}")
            last_error = MistralError(f"HTTP error {e.response.status_code}: {e.response.text}")
            logger.warning(f"HTTP error attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except MistralResponseError:
            raise
            
        except Exception as e:
            last_error = MistralError(f"Unexpected error: {e}")
            logger.error(f"Unexpected error attempt {attempt + 1}/{config.max_retries}: {e}")
        
        if attempt < config.max_retries - 1:
            import asyncio
            await asyncio.sleep(config.retry_delay * (attempt + 1))
    
    raise last_error if last_error else MistralError("All retry attempts failed")


async def _call_venice(
    prompt: str,
    max_tokens: int,
    temperature: float,
    stop: Optional[list[str]],
    config: ClientConfig
) -> MistralResponse:
    """Call Venice.ai via OpenAI-compatible /chat/completions endpoint."""
    
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    if stop:
        payload["stop"] = stop
    
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json"
    }
    
    last_error: Optional[Exception] = None
    
    for attempt in range(config.max_retries):
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(
                    f"{config.base_url}/chat/completions",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                return _parse_venice_response(response.json())
                
        except httpx.ConnectError as e:
            last_error = MistralConnectionError(f"Cannot connect to Venice at {config.base_url}: {e}")
            logger.warning(f"Connection attempt {attempt + 1}/{config.max_retries} failed: {e}")
            
        except httpx.TimeoutException as e:
            last_error = MistralTimeoutError(f"Request timed out after {config.timeout_seconds}s: {e}")
            logger.warning(f"Timeout attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise MistralResponseError(f"Client error {e.response.status_code}: {e.response.text}")
            last_error = MistralError(f"HTTP error {e.response.status_code}: {e.response.text}")
            logger.warning(f"HTTP error attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except MistralResponseError:
            raise
            
        except Exception as e:
            last_error = MistralError(f"Unexpected error: {e}")
            logger.error(f"Unexpected error attempt {attempt + 1}/{config.max_retries}: {e}")
        
        if attempt < config.max_retries - 1:
            import asyncio
            await asyncio.sleep(config.retry_delay * (attempt + 1))
    
    raise last_error if last_error else MistralError("All retry attempts failed")


# ============================================================================
# Response Parsing
# ============================================================================

def _parse_response(data: dict) -> MistralResponse:
    """Parse response - routes to appropriate parser based on structure."""
    if not isinstance(data, dict):
        raise MistralResponseError(f"Expected dict response, got {type(data).__name__ if data else 'NoneType'}")
    if "choices" in data:
        return _parse_venice_response(data)
    return _parse_local_response(data)


def _parse_local_response(data: dict) -> MistralResponse:
    """Parse llama.cpp /completion response."""
    try:
        if not isinstance(data, dict):
            raise MistralResponseError(f"Expected dict response, got {type(data).__name__}")
        
        content = data.get("content")
        if content is None:
            raise MistralResponseError("Response missing 'content' field")
        
        tokens_predicted = data.get("tokens_predicted", 0)
        tokens_evaluated = data.get("tokens_evaluated", 0)
        
        timings = None
        if "timings" in data:
            timings_data = data["timings"]
            timings = MistralTimings(
                predicted_ms=timings_data.get("predicted_ms"),
                predicted_n=timings_data.get("predicted_n"),
                predicted_per_second=timings_data.get("predicted_per_second"),
                prompt_ms=timings_data.get("prompt_ms"),
                prompt_n=timings_data.get("prompt_n"),
                prompt_per_second=timings_data.get("prompt_per_second")
            )
        
        return MistralResponse(
            content=content,
            tokens_predicted=tokens_predicted,
            tokens_evaluated=tokens_evaluated,
            timings=timings
        )
        
    except (KeyError, TypeError, ValueError) as e:
        raise MistralResponseError(f"Failed to parse Mistral response: {e}")


def _parse_venice_response(data: dict) -> MistralResponse:
    """Parse OpenAI-compatible /chat/completions response."""
    try:
        if not isinstance(data, dict):
            raise MistralResponseError(f"Expected dict response, got {type(data).__name__}")
        
        choices = data.get("choices", [])
        if not choices:
            raise MistralResponseError("Response missing 'choices' field")
        
        message = choices[0].get("message", {})
        content = message.get("content", "")
        
        usage = data.get("usage", {})
        tokens_predicted = usage.get("completion_tokens", 0)
        tokens_evaluated = usage.get("prompt_tokens", 0)
        
        return MistralResponse(
            content=content,
            tokens_predicted=tokens_predicted,
            tokens_evaluated=tokens_evaluated,
            timings=None
        )
        
    except (KeyError, TypeError, ValueError) as e:
        raise MistralResponseError(f"Failed to parse Venice response: {e}")


# ============================================================================
# Convenience Functions
# ============================================================================

async def call_mistral_simple(prompt: str, config: Optional[ClientConfig] = None) -> str:
    """
    Simplified LLM call that returns just the text content.
    
    Args:
        prompt: The input text prompt
        config: Optional client configuration
        
    Returns:
        Generated text as string
    """
    response = await call_mistral(prompt, config=config)
    return response.content


async def health_check(config: Optional[ClientConfig] = None) -> bool:
    """
    Check if LLM server is reachable and responding.
    
    Args:
        config: Optional client configuration
        
    Returns:
        True if server is healthy, False otherwise
    """
    if config is None:
        config = get_client_config()
    
    try:
        await call_mistral("test", max_tokens=1, config=config)
        return True
    except MistralError:
        return False
