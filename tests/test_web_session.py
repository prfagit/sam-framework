import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from sam.web.session import get_agent, close_agent, run_once, run_with_events


class TestWebSession:
    """Test web session functionality."""

    @pytest.mark.asyncio
    @patch("sam.web.session._factory")
    async def test_get_agent_singleton(self, mock_factory):
        """Test that get_agent returns a singleton instance."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_factory.get_agent = AsyncMock(return_value=mock_agent)

        # First call
        agent1 = await get_agent()
        assert agent1 is mock_agent

        # Second call should return same instance
        agent2 = await get_agent()
        assert agent2 is agent1
        assert agent2 is mock_agent

        # Factory should only be called once
        assert mock_factory.get_agent.await_count == 1

    @pytest.mark.asyncio
    @patch("sam.web.session._factory")
    async def test_get_agent_exception_handling(self, mock_factory):
        """Test get_agent handles exceptions during agent building."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_factory.get_agent = AsyncMock(side_effect=Exception("Build failed"))

        with pytest.raises(Exception, match="Build failed"):
            await get_agent()

        # Agent should not be cached on failure
        assert sam.web.session._agent_singleton is None
        assert sam.web.session._legacy_singleton is None

    @pytest.mark.asyncio
    async def test_close_agent(self):
        """Test close_agent functionality."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        # Set up a mock agent
        mock_agent = MagicMock()
        sam.web.session._agent_singleton = mock_agent
        sam.web.session._legacy_singleton = mock_agent

        with patch("sam.web.session.cleanup_agent_fast", new_callable=AsyncMock) as mock_cleanup:
            await close_agent()

            mock_cleanup.assert_called_once()
            assert sam.web.session._agent_singleton is None
            assert sam.web.session._legacy_singleton is None

    @pytest.mark.asyncio
    async def test_close_agent_with_exception(self):
        """Test close_agent handles exceptions."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        # Set up a mock agent
        mock_agent = MagicMock()
        sam.web.session._agent_singleton = mock_agent
        sam.web.session._legacy_singleton = mock_agent

        with patch("sam.web.session.cleanup_agent_fast", new_callable=AsyncMock) as mock_cleanup:
            mock_cleanup.side_effect = Exception("Cleanup failed")

            # Should not raise exception
            await close_agent()

            assert sam.web.session._agent_singleton is None
            assert sam.web.session._legacy_singleton is None

    @pytest.mark.asyncio
    async def test_close_agent_no_agent(self):
        """Test close_agent when no agent is set."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        with patch("sam.web.session.cleanup_agent_fast", new_callable=AsyncMock) as mock_cleanup:
            await close_agent()

            mock_cleanup.assert_called_once()

    def test_run_once(self):
        """Test run_once synchronous helper."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="test response")

        # Mock the async get_agent call
        async def mock_get_agent(*_, **__):
            return mock_agent

        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            result = run_once("test prompt", "test_session")

            assert result == "test response"
            mock_agent.run.assert_called_once_with("test prompt", "test_session", context=None)

    @pytest.mark.asyncio
    async def test_run_with_events_basic(self):
        """Test run_with_events basic functionality."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="test response")

        async def mock_get_agent(*_, **__):
            return mock_agent

        with (
            patch("sam.web.session.get_agent", side_effect=mock_get_agent),
            patch("sam.web.session.get_event_bus") as mock_get_bus,
        ):
            mock_bus = MagicMock()
            mock_get_bus.return_value = mock_bus

            async with run_with_events("test prompt", "test_session") as event_iter:
                # Test that event iterator is returned
                assert event_iter is not None

                # Test subscribing to events
                mock_bus.subscribe.assert_called()

                # Events that should be subscribed to
                expected_events = [
                    "tool.called",
                    "tool.succeeded",
                    "tool.failed",
                    "llm.usage",
                    "agent.status",
                    "agent.delta",
                    "agent.message",
                ]

                assert mock_bus.subscribe.call_count == len(expected_events)

                # Allow background runner to start
                await asyncio.sleep(0)
                # Test that agent.run is called
                mock_agent.run.assert_called_once_with(
                    "test prompt",
                    "test_session",
                    publish_final_event=False,
                    context=None,
                )

    @pytest.mark.asyncio
    async def test_run_with_events_with_real_events(self):
        """Test run_with_events with actual event publishing."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="test response")

        async def mock_get_agent(*_, **__):
            return mock_agent

        # Use real event bus so publish triggers subscribers
        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            async with run_with_events("test prompt", "test_session") as event_iter:
                # Manually publish a delta via the bus
                from sam.core.events import get_event_bus

                bus = get_event_bus()
                await bus.publish(
                    "agent.delta",
                    {
                        "session_id": "test_session",
                        "user_id": "default",
                        "content": "test delta",
                    },
                )

                # Collect events from iterator
                events = []
                async for event in event_iter:
                    events.append(event)
                    if len(events) >= 1:  # Just test one event
                        break

                assert len(events) == 1
                assert events[0]["event"] == "agent.delta"
                assert events[0]["payload"]["content"] == "test delta"
                assert events[0]["payload"].get("user_id") == "default"

    @pytest.mark.asyncio
    async def test_run_with_events_session_filtering(self):
        """Test that run_with_events filters events by session_id."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="test response")

        async def mock_get_agent(*_, **__):
            return mock_agent

        # Use real bus; publish events for different sessions
        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            async with run_with_events("test prompt", "test_session") as event_iter:
                from sam.core.events import get_event_bus

                bus = get_event_bus()

                # Event for our session - should be included
                await bus.publish(
                    "agent.delta",
                    {
                        "session_id": "test_session",
                        "user_id": "default",
                        "content": "our session delta",
                    },
                )
                # Event for different session - should be filtered out
                await bus.publish(
                    "agent.delta",
                    {
                        "session_id": "other_session",
                        "user_id": "default",
                        "content": "other session delta",
                    },
                )

                # Collect events
                events = []
                async for event in event_iter:
                    events.append(event)

                # Should only get events for our session, not for other_session
                assert all(e["payload"].get("session_id") != "other_session" for e in events)
                assert any(
                    e["event"] == "agent.delta" and e["payload"]["content"] == "our session delta"
                    for e in events
                )

    @pytest.mark.asyncio
    async def test_run_with_events_cleanup(self):
        """Test that run_with_events properly cleans up event subscriptions."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="test response")

        async def mock_get_agent(*_, **__):
            return mock_agent

        with (
            patch("sam.web.session.get_agent", side_effect=mock_get_agent),
            patch("sam.web.session.get_event_bus") as mock_get_bus,
        ):
            mock_bus = MagicMock()
            mock_get_bus.return_value = mock_bus

            async with run_with_events("test prompt", "test_session"):
                pass  # Just enter and exit context

            # Should unsubscribe from all events
            expected_events = [
                "tool.called",
                "tool.succeeded",
                "tool.failed",
                "llm.usage",
                "agent.status",
                "agent.delta",
                "agent.message",
            ]

            assert mock_bus.unsubscribe.call_count == len(expected_events)

    @pytest.mark.asyncio
    async def test_run_with_events_agent_run_failure(self):
        """Test run_with_events when agent.run fails."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(side_effect=Exception("Agent run failed"))

        async def mock_get_agent(*_, **__):
            return mock_agent

        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            with pytest.raises(Exception, match="Agent run failed"):
                async with run_with_events("test prompt", "test_session"):
                    pass

    @pytest.mark.asyncio
    async def test_run_with_events_delta_streaming(self):
        """Test run_with_events delta streaming functionality."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Hello world response")

        async def mock_get_agent(*_, **__):
            return mock_agent

        # Use real event bus and iterator
        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            async with run_with_events("test prompt", "test_session") as event_iter:
                # Collect all events
                events = []
                async for event in event_iter:
                    events.append(event)

                # Should have delta events for streaming
                delta_events = [e for e in events if e["event"] == "agent.delta"]
                assert len(delta_events) > 0

                # Should have final message event
                message_events = [e for e in events if e["event"] == "agent.message"]
                assert len(message_events) == 1

                # Final message should contain full response
                final_message = message_events[0]
                assert final_message["payload"]["content"] == "Hello world response"
                assert final_message["payload"]["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_run_with_events_empty_response(self):
        """Test run_with_events with empty response."""
        # Reset global state
        import sam.web.session

        sam.web.session._agent_singleton = None
        sam.web.session._legacy_singleton = None

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=None)

        async def mock_get_agent(*_, **__):
            return mock_agent

        # Use real event bus
        with patch("sam.web.session.get_agent", side_effect=mock_get_agent):
            async with run_with_events("test prompt", "test_session") as event_iter:
                # Collect all events
                events = []
                async for event in event_iter:
                    events.append(event)

                # Should still have final message event even with None response
                message_events = [e for e in events if e["event"] == "agent.message"]
                assert len(message_events) == 1

                # Final message content should be empty string when response is None
                final_message = message_events[0]
                assert final_message["payload"]["content"] == ""
                assert final_message["payload"]["session_id"] == "test_session"


if __name__ == "__main__":
    pytest.main([__file__])
