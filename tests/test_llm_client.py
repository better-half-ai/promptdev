"""
Comprehensive test suite for llm_client module.

Tests cover:
- Successful API calls
- Error handling (connection, timeout, malformed responses)
- Retry logic
- Input validation
- Response parsing
- Configuration loading
"""

import pytest
import httpx
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

# Import the module we're testing
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
    get_client_config,
    _parse_response
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_config():
    """Test configuration."""
    return ClientConfig(
        base_url="http://test-mistral:8080",
        timeout_seconds=5.0,
        max_retries=2,
        retry_delay=0.1  # Fast retries for tests
    )


@pytest.fixture
def mock_successful_response():
    """Mock a successful Mistral API response."""
    return {
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


@pytest.fixture
def mock_minimal_response():
    """Mock a minimal valid Mistral API response."""
    return {
        "content": "Response text",
        "tokens_predicted": 2,
        "tokens_evaluated": 3
    }


# ============================================================================
# Test Response Parsing
# ============================================================================

def test_parse_response_full(mock_successful_response):
    """Test parsing a complete response with all fields."""
    result = _parse_response(mock_successful_response)
    
    assert isinstance(result, MistralResponse)
    assert result.content == "This is a test response."
    assert result.tokens_predicted == 5
    assert result.tokens_evaluated == 10
    assert result.timings is not None
    assert result.timings.predicted_ms == 150.5


def test_parse_response_minimal(mock_minimal_response):
    """Test parsing a minimal valid response."""
    result = _parse_response(mock_minimal_response)
    
    assert isinstance(result, MistralResponse)
    assert result.content == "Response text"
    assert result.tokens_predicted == 2
    assert result.tokens_evaluated == 3
    assert result.timings is None  # Optional field


def test_parse_response_missing_content():
    """Test parsing fails when content field is missing."""
    with pytest.raises(MistralResponseError, match="missing 'content'"):
        _parse_response({"tokens_predicted": 5})


def test_parse_response_invalid_structure():
    """Test parsing fails with completely invalid structure."""
    with pytest.raises(MistralResponseError):
        _parse_response(None)  # type: ignore


def test_parse_response_empty_dict():
    """Test parsing fails with empty response."""
    with pytest.raises(MistralResponseError, match="missing 'content'"):
        _parse_response({})


# ============================================================================
# Test Successful API Calls
# ============================================================================

@pytest.mark.asyncio
async def test_call_mistral_success(test_config, mock_successful_response):
    """Test successful Mistral API call."""
    mock_response = Mock()
    mock_response.json.return_value = mock_successful_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral(
            prompt="Hello, Mistral!",
            max_tokens=100,
            temperature=0.7,
            config=test_config
        )
        
        assert isinstance(result, MistralResponse)
        assert result.content == "This is a test response."
        assert result.tokens_predicted == 5
        assert result.tokens_evaluated == 10
        
        # Verify the request was made correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://test-mistral:8080/completion"
        assert call_args[1]["json"]["prompt"] == "Hello, Mistral!"
        assert call_args[1]["json"]["n_predict"] == 100
        assert call_args[1]["json"]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_call_mistral_with_stop_sequences(test_config, mock_minimal_response):
    """Test Mistral call with stop sequences."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral(
            prompt="Count to 5:",
            stop=["5", "\n"],
            config=test_config
        )
        
        assert isinstance(result, MistralResponse)
        
        # Verify stop sequences were included
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["stop"] == ["5", "\n"]


@pytest.mark.asyncio
async def test_call_mistral_simple(test_config, mock_minimal_response):
    """Test simplified Mistral call that returns just text."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral_simple("Test prompt")
        
        assert isinstance(result, str)
        assert result == "Response text"


# ============================================================================
# Test Error Handling
# ============================================================================

@pytest.mark.asyncio
async def test_connection_error_with_retries(test_config):
    """Test connection error triggers retries then fails."""
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        with pytest.raises(MistralConnectionError, match="Cannot connect"):
            await call_mistral("test", config=test_config)
        
        # Should have tried max_retries times
        assert mock_client.post.call_count == test_config.max_retries


@pytest.mark.asyncio
async def test_timeout_error(test_config):
    """Test timeout error is properly handled."""
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        with pytest.raises(MistralTimeoutError, match="timed out"):
            await call_mistral("test", config=test_config)
        
        assert mock_client.post.call_count == test_config.max_retries


@pytest.mark.asyncio
async def test_http_4xx_no_retry(test_config):
    """Test 4xx errors don't trigger retries."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("Bad Request", request=Mock(), response=mock_response)
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        with pytest.raises(MistralResponseError, match="Client error 400"):
            await call_mistral("test", config=test_config)
        
        # Should only try once (no retries for 4xx)
        assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_http_5xx_with_retry(test_config):
    """Test 5xx errors trigger retries."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("Server Error", request=Mock(), response=mock_response)
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        with pytest.raises(MistralError, match="HTTP error 500"):
            await call_mistral("test", config=test_config)
        
        # Should retry
        assert mock_client.post.call_count == test_config.max_retries


@pytest.mark.asyncio
async def test_malformed_response_error(test_config):
    """Test malformed response raises appropriate error."""
    mock_response = Mock()
    mock_response.json.return_value = {"invalid": "structure"}
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        with pytest.raises(MistralResponseError, match="missing 'content'"):
            await call_mistral("test", config=test_config)


@pytest.mark.asyncio
async def test_retry_succeeds_after_failure(test_config, mock_minimal_response):
    """Test successful retry after initial failure."""
    # First call fails, second succeeds
    mock_response_success = Mock()
    mock_response_success.json.return_value = mock_minimal_response
    mock_response_success.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=[
                httpx.ConnectError("First attempt fails"),
                mock_response_success  # Second attempt succeeds
            ]
        )
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral("test", config=test_config)
        
        assert isinstance(result, MistralResponse)
        assert result.content == "Response text"
        assert mock_client.post.call_count == 2


# ============================================================================
# Test Input Validation
# ============================================================================

@pytest.mark.asyncio
async def test_empty_prompt_raises_error(test_config):
    """Test empty prompt is rejected."""
    with pytest.raises(ValueError, match="non-empty string"):
        await call_mistral("", config=test_config)


@pytest.mark.asyncio
async def test_invalid_prompt_type_raises_error(test_config):
    """Test invalid prompt type is rejected."""
    with pytest.raises(ValueError, match="non-empty string"):
        await call_mistral(None, config=test_config)  # type: ignore


@pytest.mark.asyncio
async def test_negative_max_tokens_raises_error(test_config):
    """Test negative max_tokens is rejected."""
    with pytest.raises(ValueError, match="must be positive"):
        await call_mistral("test", max_tokens=-1, config=test_config)


@pytest.mark.asyncio
async def test_zero_max_tokens_raises_error(test_config):
    """Test zero max_tokens is rejected."""
    with pytest.raises(ValueError, match="must be positive"):
        await call_mistral("test", max_tokens=0, config=test_config)


@pytest.mark.asyncio
async def test_invalid_temperature_too_low(test_config):
    """Test temperature below 0.0 is rejected."""
    with pytest.raises(ValueError, match="between 0.0 and 2.0"):
        await call_mistral("test", temperature=-0.1, config=test_config)


@pytest.mark.asyncio
async def test_invalid_temperature_too_high(test_config):
    """Test temperature above 2.0 is rejected."""
    with pytest.raises(ValueError, match="between 0.0 and 2.0"):
        await call_mistral("test", temperature=2.1, config=test_config)


# ============================================================================
# Test Configuration Loading
# ============================================================================

def test_get_client_config():
    """Test loading client configuration from app config."""
    # This will use the actual config.toml from the project
    config = get_client_config()
    
    assert isinstance(config, ClientConfig)
    assert config.base_url  # Should have a value from config
    assert config.timeout_seconds > 0
    assert config.max_retries > 0
    assert config.retry_delay > 0


# ============================================================================
# Test Health Check
# ============================================================================

@pytest.mark.asyncio
async def test_health_check_success(test_config, mock_minimal_response):
    """Test health check succeeds when server responds."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await health_check(config=test_config)
        
        assert result is True


@pytest.mark.asyncio
async def test_health_check_failure(test_config):
    """Test health check fails when server is unreachable."""
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await health_check(config=test_config)
        
        assert result is False


# ============================================================================
# Test Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_very_long_prompt(test_config, mock_minimal_response):
    """Test handling of very long prompts."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        long_prompt = "test " * 10000  # Very long prompt
        result = await call_mistral(long_prompt, config=test_config)
        
        assert isinstance(result, MistralResponse)


@pytest.mark.asyncio
async def test_zero_temperature(test_config, mock_minimal_response):
    """Test temperature=0.0 (deterministic) is valid."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral("test", temperature=0.0, config=test_config)
        
        assert isinstance(result, MistralResponse)
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_max_temperature(test_config, mock_minimal_response):
    """Test temperature=2.0 (max randomness) is valid."""
    mock_response = Mock()
    mock_response.json.return_value = mock_minimal_response
    mock_response.raise_for_status = Mock()
    
    with patch('httpx.AsyncClient') as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        result = await call_mistral("test", temperature=2.0, config=test_config)
        
        assert isinstance(result, MistralResponse)
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["temperature"] == 2.0


def test_mistral_response_model_validation():
    """Test Pydantic validation of MistralResponse."""
    # Valid response
    response = MistralResponse(
        content="test",
        tokens_predicted=5,
        tokens_evaluated=10
    )
    assert response.content == "test"
    
    # Invalid: missing required fields
    with pytest.raises(Exception):  # Pydantic ValidationError
        MistralResponse(content="test")  # type: ignore


def test_mistral_timings_model():
    """Test MistralTimings model."""
    timings = MistralTimings(
        predicted_ms=100.0,
        predicted_n=5,
        predicted_per_second=50.0
    )
    assert timings.predicted_ms == 100.0
    
    # All fields optional
    empty_timings = MistralTimings()
    assert empty_timings.predicted_ms is None
