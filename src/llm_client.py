"""
LLM Client for Mistral API communication.

Handles all communication with the self-hosted Mistral LLM server via llama.cpp's
/completion endpoint. Includes comprehensive error handling, retry logic, and
structured response parsing.
"""

import os
import httpx
import logging
from typing import Optional
from pydantic import BaseModel, Field
from dataclasses import dataclass

from src.config import get_config

# Configure logging
logger = logging.getLogger(__name__)


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
    """Structured response from Mistral API."""
    content: str = Field(description="Generated text response")
    tokens_predicted: int = Field(description="Number of tokens generated")
    tokens_evaluated: int = Field(description="Number of prompt tokens processed")
    timings: Optional[MistralTimings] = Field(default=None, description="Performance timings")
    

# ============================================================================
# Exceptions
# ============================================================================

class MistralError(Exception):
    """Base exception for Mistral client errors."""
    pass


class MistralConnectionError(MistralError):
    """Raised when cannot connect to Mistral server."""
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
    """Configuration for Mistral client."""
    base_url: str
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0


def get_client_config() -> ClientConfig:
    """Load client configuration from application config."""
    cfg = get_config()
    
    # Use test_mistral if in test mode
    if os.environ.get("USE_TEST_DB") == "1" and cfg.test_mistral:
        base_url = cfg.test_mistral.url
    else:
        base_url = cfg.mistral.url
    
    return ClientConfig(
        base_url=base_url,
        timeout_seconds=30.0,  # Could be added to config.toml if needed
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
    Call Mistral LLM with the given prompt.
    
    Args:
        prompt: The input text prompt
        max_tokens: Maximum number of tokens to generate (default: 512)
        temperature: Sampling temperature 0.0-2.0 (default: 0.7)
        stop: Optional list of stop sequences
        config: Optional client configuration (uses default if not provided)
        
    Returns:
        MistralResponse with generated text and metadata
        
    Raises:
        MistralConnectionError: Cannot connect to Mistral server
        MistralTimeoutError: Request timed out
        MistralResponseError: Invalid or malformed response
        MistralError: Other unexpected errors
        
    Example:
        >>> response = await call_mistral("Hello, how are you?", max_tokens=100)
        >>> print(response.content)
        "I'm doing well, thank you for asking!"
        >>> print(f"Generated {response.tokens_predicted} tokens")
        Generated 8 tokens
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
    
    # Build request payload
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "stream": False  # We don't support streaming yet
    }
    
    if stop:
        payload["stop"] = stop
        
    # Attempt request with retries
    last_error: Optional[Exception] = None
    
    for attempt in range(config.max_retries):
        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                response = await client.post(
                    f"{config.base_url}/completion",
                    json=payload
                )
                response.raise_for_status()
                
                # Parse and validate response
                return _parse_response(response.json())
                
        except httpx.ConnectError as e:
            last_error = MistralConnectionError(f"Cannot connect to Mistral at {config.base_url}: {e}")
            logger.warning(f"Connection attempt {attempt + 1}/{config.max_retries} failed: {e}")
            
        except httpx.TimeoutException as e:
            last_error = MistralTimeoutError(f"Request timed out after {config.timeout_seconds}s: {e}")
            logger.warning(f"Timeout attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except httpx.HTTPStatusError as e:
            # Don't retry 4xx errors (client errors)
            if 400 <= e.response.status_code < 500:
                raise MistralResponseError(f"Client error {e.response.status_code}: {e.response.text}")
            last_error = MistralError(f"HTTP error {e.response.status_code}: {e.response.text}")
            logger.warning(f"HTTP error attempt {attempt + 1}/{config.max_retries}: {e}")
            
        except MistralResponseError:
            # Don't retry on response parsing errors
            raise
            
        except Exception as e:
            last_error = MistralError(f"Unexpected error: {e}")
            logger.error(f"Unexpected error attempt {attempt + 1}/{config.max_retries}: {e}")
            
        # Wait before retrying (except on last attempt)
        if attempt < config.max_retries - 1:
            import asyncio
            await asyncio.sleep(config.retry_delay * (attempt + 1))  # Exponential backoff
            
    # All retries exhausted
    raise last_error if last_error else MistralError("All retry attempts failed")


def _parse_response(data: dict) -> MistralResponse:
    """
    Parse and validate Mistral API response.
    
    Args:
        data: Raw JSON response from Mistral API
        
    Returns:
        Validated MistralResponse object
        
    Raises:
        MistralResponseError: If response is malformed or missing required fields
    """
    try:
        # Validate data is a dict
        if not isinstance(data, dict):
            raise MistralResponseError(f"Expected dict response, got {type(data).__name__}")
        
        # llama.cpp returns these fields
        content = data.get("content")
        if content is None:
            raise MistralResponseError("Response missing 'content' field")
            
        tokens_predicted = data.get("tokens_predicted", 0)
        tokens_evaluated = data.get("tokens_evaluated", 0)
        
        # Parse timings if present
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


# ============================================================================
# Convenience Functions
# ============================================================================

async def call_mistral_simple(prompt: str) -> str:
    """
    Simplified Mistral call that returns just the text content.
    
    Args:
        prompt: The input text prompt
        
    Returns:
        Generated text as string
        
    Raises:
        MistralError: If request fails
        
    Example:
        >>> text = await call_mistral_simple("What is 2+2?")
        >>> print(text)
        "2+2 equals 4."
    """
    response = await call_mistral(prompt)
    return response.content


async def health_check(config: Optional[ClientConfig] = None) -> bool:
    """
    Check if Mistral server is reachable and responding.
    
    Args:
        config: Optional client configuration
        
    Returns:
        True if server is healthy, False otherwise
    """
    if config is None:
        config = get_client_config()
        
    try:
        # Simple prompt to check if server responds
        await call_mistral("test", max_tokens=1, config=config)
        return True
    except MistralError:
        return False