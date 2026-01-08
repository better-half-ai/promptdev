"""
Test suite for llm_client module.

Tests cover:
- Response parsing
- Input validation
- Model validation
- Configuration loading
- Live API calls (when LLM available)
"""

import pytest
import os

from llm_client import (
    call_mistral,
    call_mistral_simple,
    health_check,
    MistralResponse,
    MistralTimings,
    MistralConnectionError,
    MistralTimeoutError,
    MistralResponseError,
    MistralError,
    ClientConfig,
    LLMBackend,
    get_client_config,
    _parse_response,
    _parse_local_response,
    _parse_venice_response,
)


# ============================================================================
# Test Response Parsing - Local
# ============================================================================

def test_parse_local_response_full():
    """Test parsing a complete local response with all fields."""
    data = {
        "content": "This is a test response.",
        "tokens_predicted": 5,
        "tokens_evaluated": 10,
        "timings": {
            "predicted_ms": 150.5,
            "predicted_n": 5,
            "predicted_per_second": 33.2,
            "prompt_ms": 50.2,
            "prompt_n": 10,
            "prompt_per_second": 199.2
        }
    }
    result = _parse_local_response(data)
    
    assert isinstance(result, MistralResponse)
    assert result.content == "This is a test response."
    assert result.tokens_predicted == 5
    assert result.tokens_evaluated == 10
    assert result.timings is not None
    assert result.timings.predicted_ms == 150.5


def test_parse_local_response_minimal():
    """Test parsing a minimal valid local response."""
    data = {
        "content": "Response text",
        "tokens_predicted": 2,
        "tokens_evaluated": 3
    }
    result = _parse_local_response(data)
    
    assert isinstance(result, MistralResponse)
    assert result.content == "Response text"
    assert result.tokens_predicted == 2
    assert result.tokens_evaluated == 3
    assert result.timings is None


def test_parse_local_response_missing_content():
    """Test parsing fails when content field is missing."""
    with pytest.raises(MistralResponseError, match="missing 'content'"):
        _parse_local_response({"tokens_predicted": 5})


def test_parse_local_response_empty_dict():
    """Test parsing fails with empty response."""
    with pytest.raises(MistralResponseError, match="missing 'content'"):
        _parse_local_response({})


def test_parse_local_response_content_only():
    """Test parsing with only content field."""
    data = {"content": "Just content"}
    result = _parse_local_response(data)
    
    assert result.content == "Just content"
    assert result.tokens_predicted == 0
    assert result.tokens_evaluated == 0


# ============================================================================
# Test Response Parsing - Venice
# ============================================================================

def test_parse_venice_response_full():
    """Test parsing a complete Venice response."""
    data = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help?"
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }
    result = _parse_venice_response(data)
    
    assert isinstance(result, MistralResponse)
    assert result.content == "Hello! How can I help?"
    assert result.tokens_predicted == 5
    assert result.tokens_evaluated == 10


def test_parse_venice_response_missing_choices():
    """Test parsing fails when choices field is missing."""
    with pytest.raises(MistralResponseError, match="missing 'choices'"):
        _parse_venice_response({"id": "test"})


def test_parse_venice_response_empty_choices():
    """Test parsing fails with empty choices."""
    with pytest.raises(MistralResponseError, match="missing 'choices'"):
        _parse_venice_response({"choices": []})


# ============================================================================
# Test Response Parsing - Router
# ============================================================================

def test_parse_response_routes_to_local():
    """Test _parse_response routes to local parser for local format."""
    data = {"content": "test", "tokens_predicted": 1, "tokens_evaluated": 1}
    result = _parse_response(data)
    assert result.content == "test"


def test_parse_response_routes_to_venice():
    """Test _parse_response routes to venice parser for OpenAI format."""
    data = {
        "choices": [{"message": {"content": "test"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1}
    }
    result = _parse_response(data)
    assert result.content == "test"


def test_parse_response_invalid_structure():
    """Test parsing fails with completely invalid structure."""
    with pytest.raises(MistralResponseError):
        _parse_response(None)


def test_parse_response_invalid_type():
    """Test parsing fails with invalid type."""
    with pytest.raises(MistralResponseError):
        _parse_response("not a dict")


# ============================================================================
# Test Input Validation
# ============================================================================

@pytest.mark.asyncio
async def test_empty_prompt_raises_error():
    """Test empty prompt is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="non-empty string"):
        await call_mistral("", config=config)


@pytest.mark.asyncio
async def test_invalid_prompt_type_raises_error():
    """Test invalid prompt type is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="non-empty string"):
        await call_mistral(None, config=config)


@pytest.mark.asyncio
async def test_negative_max_tokens_raises_error():
    """Test negative max_tokens is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="must be positive"):
        await call_mistral("test", max_tokens=-1, config=config)


@pytest.mark.asyncio
async def test_zero_max_tokens_raises_error():
    """Test zero max_tokens is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="must be positive"):
        await call_mistral("test", max_tokens=0, config=config)


@pytest.mark.asyncio
async def test_invalid_temperature_too_low():
    """Test temperature below 0.0 is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="between 0.0 and 2.0"):
        await call_mistral("test", temperature=-0.1, config=config)


@pytest.mark.asyncio
async def test_invalid_temperature_too_high():
    """Test temperature above 2.0 is rejected."""
    config = ClientConfig(base_url="http://fake:8080", backend=LLMBackend.LOCAL, max_retries=1)
    with pytest.raises(ValueError, match="between 0.0 and 2.0"):
        await call_mistral("test", temperature=2.1, config=config)


# ============================================================================
# Test Model Validation
# ============================================================================

def test_mistral_response_model_validation():
    """Test MistralResponse model."""
    response = MistralResponse(
        content="test",
        tokens_predicted=5,
        tokens_evaluated=10
    )
    assert response.content == "test"
    assert response.tokens_predicted == 5
    assert response.tokens_evaluated == 10


def test_mistral_timings_model():
    """Test MistralTimings model."""
    timings = MistralTimings(
        predicted_ms=100.0,
        predicted_n=5,
        predicted_per_second=50.0
    )
    assert timings.predicted_ms == 100.0
    assert timings.predicted_n == 5
    assert timings.predicted_per_second == 50.0


def test_mistral_timings_all_optional():
    """Test MistralTimings with no fields."""
    timings = MistralTimings()
    assert timings.predicted_ms is None
    assert timings.predicted_n is None


def test_client_config_defaults():
    """Test ClientConfig default values."""
    config = ClientConfig(base_url="http://test:8080")
    assert config.base_url == "http://test:8080"
    assert config.backend == LLMBackend.LOCAL
    assert config.timeout_seconds == 30.0
    assert config.max_retries == 3
    assert config.retry_delay == 1.0


def test_client_config_venice():
    """Test ClientConfig for Venice."""
    config = ClientConfig(
        base_url="https://api.venice.ai/api/v1",
        backend=LLMBackend.VENICE,
        api_key="test-key",
        model="mistral-31-24b"
    )
    assert config.backend == LLMBackend.VENICE
    assert config.api_key == "test-key"
    assert config.model == "mistral-31-24b"


# ============================================================================
# Test Live API Calls (when LLM available)
# ============================================================================

@pytest.mark.asyncio
async def test_health_check_live(mistral_available, llm_backend, llm_url):
    """Test health check against live server."""
    if not mistral_available:
        pytest.skip("LLM backend not available")
    
    if llm_backend == "venice":
        config = ClientConfig(
            base_url=llm_url,
            backend=LLMBackend.VENICE,
            api_key=os.environ.get("VENICE_API_KEY", ""),
            model=os.environ.get("VENICE_MODEL", "mistral-31-24b")
        )
    else:
        config = ClientConfig(base_url=llm_url, backend=LLMBackend.LOCAL)
    
    result = await health_check(config=config)
    assert result is True


@pytest.mark.asyncio
async def test_call_mistral_live(mistral_available, llm_backend, llm_url):
    """Test actual LLM API call."""
    if not mistral_available:
        pytest.skip("LLM backend not available")
    
    if llm_backend == "venice":
        config = ClientConfig(
            base_url=llm_url,
            backend=LLMBackend.VENICE,
            api_key=os.environ.get("VENICE_API_KEY", ""),
            model=os.environ.get("VENICE_MODEL", "mistral-31-24b")
        )
    else:
        config = ClientConfig(base_url=llm_url, backend=LLMBackend.LOCAL)
    
    result = await call_mistral(
        prompt="Say hello in exactly one word.",
        max_tokens=10,
        temperature=0.1,
        config=config
    )
    
    assert isinstance(result, MistralResponse)
    assert len(result.content) > 0
    assert result.tokens_predicted > 0


@pytest.mark.asyncio
async def test_call_mistral_simple_live(mistral_available, llm_backend, llm_url):
    """Test simplified LLM call."""
    if not mistral_available:
        pytest.skip("LLM backend not available")
    
    if llm_backend == "venice":
        config = ClientConfig(
            base_url=llm_url,
            backend=LLMBackend.VENICE,
            api_key=os.environ.get("VENICE_API_KEY", ""),
            model=os.environ.get("VENICE_MODEL", "mistral-31-24b")
        )
    else:
        config = ClientConfig(base_url=llm_url, backend=LLMBackend.LOCAL)
    
    result = await call_mistral_simple("What is 1+1? Answer with just the number.", config=config)
    
    assert isinstance(result, str)
    assert len(result) > 0
