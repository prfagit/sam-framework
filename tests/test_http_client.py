import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from contextlib import asynccontextmanager
from sam.utils.http_client import (
    SharedHTTPClient,
    get_http_client,
    cleanup_http_client,
    get_session,
    http_request,
)


class TestSharedHTTPClient:
    """Test SharedHTTPClient class functionality."""

    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test that SharedHTTPClient follows singleton pattern."""
        # Clear any existing instance
        SharedHTTPClient._instance = None

        instance1 = await SharedHTTPClient.get_instance()
        instance2 = await SharedHTTPClient.get_instance()

        assert instance1 is instance2
        assert isinstance(instance1, SharedHTTPClient)

        # Cleanup
        if hasattr(instance1, "_session") and instance1._session:
            await instance1.close()

    @pytest.mark.asyncio
    async def test_get_session_creates_session(self):
        """Test that get_session creates a new session when none exists."""
        client = SharedHTTPClient()
        client._session = None

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            session = await client.get_session()

            assert session == mock_session
            mock_session_class.assert_called_once()

            # Cleanup
            await client.close()

    @pytest.mark.asyncio
    async def test_get_session_reuses_session(self):
        """Test that get_session reuses existing session."""
        import asyncio

        client = SharedHTTPClient()
        existing_session = AsyncMock()
        existing_session.closed = False
        client._session = existing_session
        client._closed = False
        client._loop = asyncio.get_running_loop()  # Set the correct loop

        session = await client.get_session()

        assert session == existing_session

    @pytest.mark.asyncio
    async def test_get_session_creates_after_close(self):
        """Test that get_session creates new session after close."""
        client = SharedHTTPClient()
        client._closed = True

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            session = await client.get_session()

            assert session == mock_session
            mock_session_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing HTTP session."""
        client = SharedHTTPClient()
        mock_session = AsyncMock()
        mock_session.closed = False
        client._session = mock_session

        await client.close()

        mock_session.close.assert_called_once()
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_close_already_closed_session(self):
        """Test closing already closed session."""
        client = SharedHTTPClient()
        mock_session = AsyncMock()
        mock_session.closed = True
        client._session = mock_session

        await client.close()

        mock_session.close.assert_not_called()
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager functionality."""
        client = SharedHTTPClient()
        mock_session = AsyncMock()
        mock_session.closed = False
        client._session = mock_session

        async with client:
            pass

        mock_session.close.assert_called_once()
        assert client._closed is True

    @pytest.mark.asyncio
    async def test_request_context_manager_success(self):
        """Test request context manager with successful response."""
        client = SharedHTTPClient()
        mock_session = MagicMock()
        mock_response = AsyncMock()
        mock_response.status = 200

        # Create a proper async context manager mock
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.request.return_value = mock_cm

        # Mock get_session to return our mock session
        with patch.object(client, "get_session", new_callable=AsyncMock, return_value=mock_session):
            async with client.request("GET", "http://example.com") as response:
                assert response == mock_response

            mock_session.request.assert_called_once_with("GET", "http://example.com")

    @pytest.mark.asyncio
    async def test_request_context_manager_error(self):
        """Test request context manager with error."""
        client = SharedHTTPClient()
        mock_session = MagicMock()

        # Create a proper async context manager mock that raises
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.request.return_value = mock_cm

        # Mock get_session to return our mock session
        with patch.object(client, "get_session", new_callable=AsyncMock, return_value=mock_session):
            with pytest.raises(Exception, match="Network error"):
                async with client.request("GET", "http://example.com"):
                    pass

        # Cleanup
        await client.close()

    @pytest.mark.asyncio
    async def test_session_configuration(self):
        """Test that session is created with proper configuration."""
        client = SharedHTTPClient()

        with patch("aiohttp.ClientSession") as mock_session_class:
            with patch("aiohttp.TCPConnector") as mock_connector_class:
                with patch("aiohttp.ClientTimeout") as mock_timeout_class:
                    mock_session = AsyncMock()
                    mock_session_class.return_value = mock_session

                    await client._create_session()

                    # Check connector configuration
                    mock_connector_class.assert_called_once()
                    connector_call = mock_connector_class.call_args
                    assert connector_call[1]["limit"] == 100
                    assert connector_call[1]["limit_per_host"] == 20

                    # Check timeout configuration
                    mock_timeout_class.assert_called_once()
                    timeout_call = mock_timeout_class.call_args
                    # In test mode (SAM_TEST_MODE=1), timeout is 20 seconds, otherwise 60
                    assert timeout_call[1]["total"] in (20, 60)
                    assert timeout_call[1]["connect"] in (5, 10)  # 5 in test mode, 10 in production

                    # Check session configuration
                    mock_session_class.assert_called_once()
                    session_call = mock_session_class.call_args
                    assert "User-Agent" in session_call[1]["headers"]


class TestGlobalHTTPClient:
    """Test global HTTP client functions."""

    @pytest.mark.asyncio
    async def test_get_http_client_singleton(self):
        """Test global HTTP client singleton pattern."""
        # Reset global state
        import sam.utils.http_client

        sam.utils.http_client._global_client = None

        client1 = await get_http_client()
        client2 = await get_http_client()

        assert client1 is client2

    @pytest.mark.asyncio
    async def test_cleanup_http_client(self):
        """Test cleanup of global HTTP client."""
        import sam.utils.http_client

        mock_client = AsyncMock()
        sam.utils.http_client._global_client = mock_client

        await cleanup_http_client()

        mock_client.close.assert_called_once()
        assert sam.utils.http_client._global_client is None

    @pytest.mark.asyncio
    async def test_get_session_global(self):
        """Test getting session from global client."""
        import sam.utils.http_client

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_client.get_session.return_value = mock_session
        sam.utils.http_client._global_client = mock_client

        session = await get_session()

        assert session == mock_session
        mock_client.get_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_request_context_manager(self):
        """Test global HTTP request context manager."""
        mock_client = AsyncMock()
        mock_response = AsyncMock()

        # Create a proper async context manager mock
        @asynccontextmanager
        async def mock_request(*args, **kwargs):
            yield mock_response

        mock_client.request = mock_request

        # Mock the get_http_client function to return our mock client
        with patch("sam.utils.http_client.get_http_client", return_value=mock_client):
            async with http_request("GET", "http://example.com") as response:
                assert response == mock_response


if __name__ == "__main__":
    pytest.main([__file__])
