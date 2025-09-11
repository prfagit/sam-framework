import pytest
import asyncio
import time
import psutil
from unittest.mock import patch, MagicMock, AsyncMock
from sam.utils.memory_monitor import (
    MemoryStats,
    MemoryThresholds,
    MemoryMonitor,
    get_memory_monitor,
    start_memory_monitoring,
    monitor_memory
)


class TestMemoryStats:
    """Test MemoryStats dataclass."""

    def test_memory_stats_creation(self):
        """Test MemoryStats creation with all fields."""
        stats = MemoryStats(
            total_ram=16 * 1024**3,  # 16 GB
            available_ram=8 * 1024**3,  # 8 GB
            used_ram=8 * 1024**3,  # 8 GB
            ram_percentage=50.0,
            process_rss=512 * 1024**2,  # 512 MB
            process_vms=1024 * 1024**2,  # 1 GB
            process_percentage=3.2,
            gc_objects=10000
        )

        assert stats.total_ram == 16 * 1024**3
        assert stats.available_ram == 8 * 1024**3
        assert stats.used_ram == 8 * 1024**3
        assert stats.ram_percentage == 50.0
        assert stats.process_rss == 512 * 1024**2
        assert stats.process_vms == 1024 * 1024**2
        assert stats.process_percentage == 3.2
        assert stats.gc_objects == 10000


class TestMemoryThresholds:
    """Test MemoryThresholds dataclass."""

    def test_memory_thresholds_defaults(self):
        """Test MemoryThresholds default values."""
        thresholds = MemoryThresholds()

        assert thresholds.warning_threshold == 80.0
        assert thresholds.critical_threshold == 90.0
        assert thresholds.max_cache_size_mb == 100
        assert thresholds.gc_frequency == 100

    def test_memory_thresholds_custom_values(self):
        """Test MemoryThresholds with custom values."""
        thresholds = MemoryThresholds(
            warning_threshold=70.0,
            critical_threshold=85.0,
            max_cache_size_mb=200,
            gc_frequency=50
        )

        assert thresholds.warning_threshold == 70.0
        assert thresholds.critical_threshold == 85.0
        assert thresholds.max_cache_size_mb == 200
        assert thresholds.gc_frequency == 50


class TestMemoryMonitor:
    """Test MemoryMonitor functionality."""

    def test_memory_monitor_initialization(self):
        """Test MemoryMonitor initialization."""
        thresholds = MemoryThresholds(warning_threshold=75.0)
        monitor = MemoryMonitor(thresholds=thresholds)

        assert monitor.thresholds.warning_threshold == 75.0
        assert monitor._operation_count == 0
        assert monitor._cache_sizes == {}
        assert isinstance(monitor._last_gc_time, float)
        assert monitor._memory_alerts == {}

    def test_memory_monitor_default_thresholds(self):
        """Test MemoryMonitor with default thresholds."""
        monitor = MemoryMonitor()

        assert monitor.thresholds.warning_threshold == 80.0
        assert monitor.thresholds.critical_threshold == 90.0

    @patch("psutil.virtual_memory")
    @patch("psutil.Process")
    @patch("gc.get_objects")
    def test_get_memory_stats(self, mock_gc_objects, mock_process_class, mock_virtual_memory):
        """Test memory statistics retrieval."""
        # Mock system memory
        mock_system_mem = MagicMock()
        mock_system_mem.total = 16 * 1024**3
        mock_system_mem.available = 10 * 1024**3
        mock_system_mem.used = 6 * 1024**3
        mock_system_mem.percent = 37.5
        mock_virtual_memory.return_value = mock_system_mem

        # Mock process memory
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=256 * 1024**2, vms=512 * 1024**2)
        mock_process.memory_percent.return_value = 1.6
        mock_process_class.return_value = mock_process

        # Mock GC objects
        mock_gc_objects.return_value = [MagicMock()] * 5000

        monitor = MemoryMonitor()
        stats = monitor.get_memory_stats()

        assert stats.total_ram == 16 * 1024**3
        assert stats.available_ram == 10 * 1024**3
        assert stats.used_ram == 6 * 1024**3
        assert stats.ram_percentage == 37.5
        assert stats.process_rss == 256 * 1024**2
        assert stats.process_vms == 512 * 1024**2
        assert stats.process_percentage == 1.6
        assert stats.gc_objects == 5000

    @patch("psutil.virtual_memory")
    def test_check_memory_thresholds_no_alerts(self, mock_virtual_memory):
        """Test memory threshold checking with no alerts."""
        mock_system_mem = MagicMock()
        mock_system_mem.percent = 50.0  # Below warning threshold
        mock_system_mem.total = 8 * 1024**3  # 8GB total memory
        mock_virtual_memory.return_value = mock_system_mem

        monitor = MemoryMonitor()
        alerts = monitor.check_memory_thresholds()

        assert alerts == {}

    @patch("psutil.virtual_memory")
    @patch("psutil.Process")
    def test_check_memory_thresholds_warning(self, mock_process_class, mock_virtual_memory):
        """Test memory threshold checking with warning alert."""
        mock_system_mem = MagicMock()
        mock_system_mem.percent = 85.0  # Above warning threshold
        mock_virtual_memory.return_value = mock_system_mem

        mock_process = MagicMock()
        mock_process.memory_percent.return_value = 2.0
        mock_process_class.return_value = mock_process

        monitor = MemoryMonitor()
        alerts = monitor.check_memory_thresholds()

        assert "warning" in alerts
        assert "System memory at 85.0%" in alerts["warning"]
        assert monitor._memory_alerts["warning"] == 1

    @patch("psutil.virtual_memory")
    @patch("psutil.Process")
    def test_check_memory_thresholds_critical(self, mock_process_class, mock_virtual_memory):
        """Test memory threshold checking with critical alert."""
        mock_system_mem = MagicMock()
        mock_system_mem.percent = 95.0  # Above critical threshold
        mock_virtual_memory.return_value = mock_system_mem

        mock_process = MagicMock()
        mock_process.memory_percent.return_value = 2.0
        mock_process_class.return_value = mock_process

        monitor = MemoryMonitor()
        alerts = monitor.check_memory_thresholds()

        assert "critical" in alerts
        assert "System memory at 95.0%" in alerts["critical"]
        assert monitor._memory_alerts["critical"] == 1

    @patch("psutil.Process")
    def test_check_memory_thresholds_process_warning(self, mock_process_class):
        """Test memory threshold checking with process warning."""
        mock_process = MagicMock()
        mock_process.memory_percent.return_value = 85.0  # High process memory
        mock_process_class.return_value = mock_process

        with patch("psutil.virtual_memory") as mock_virtual_memory:
            mock_system_mem = MagicMock()
            mock_system_mem.percent = 50.0  # Normal system memory
            mock_virtual_memory.return_value = mock_system_mem

            monitor = MemoryMonitor()
            alerts = monitor.check_memory_thresholds()

            assert "process_warning" in alerts

    def test_register_cache_usage(self):
        """Test cache usage registration."""
        monitor = MemoryMonitor()

        monitor.register_cache_usage("test_cache", 50 * 1024**2)  # 50 MB

        assert monitor._cache_sizes["test_cache"] == 50 * 1024**2

    def test_register_cache_usage_over_limit(self):
        """Test cache usage registration when over limit."""
        monitor = MemoryMonitor()

        with patch("sam.utils.memory_monitor.logger") as mock_logger:
            # Register cache over the default limit (100 MB)
            monitor.register_cache_usage("large_cache", 150 * 1024**2)  # 150 MB

            mock_logger.warning.assert_called_once()

    def test_should_run_gc_operation_count(self):
        """Test GC trigger based on operation count."""
        monitor = MemoryMonitor(MemoryThresholds(gc_frequency=5))

        # Should not trigger initially
        assert not monitor.should_run_gc()

        # Trigger after reaching frequency
        for _ in range(3):
            monitor._operation_count += 1

        assert monitor.should_run_gc()

    def test_should_run_gc_time_based(self):
        """Test GC trigger based on time interval."""
        monitor = MemoryMonitor()

        # Set last GC time to 6 minutes ago
        monitor._last_gc_time = time.time() - 360

        assert monitor.should_run_gc()

    @patch("psutil.virtual_memory")
    def test_should_run_gc_memory_based(self, mock_virtual_memory):
        """Test GC trigger based on memory usage."""
        mock_system_mem = MagicMock()
        mock_system_mem.percent = 85.0  # Above warning threshold
        mock_virtual_memory.return_value = mock_system_mem

        monitor = MemoryMonitor()

        assert monitor.should_run_gc()

    @patch("gc.get_objects")
    @patch("gc.collect")
    @patch("psutil.Process")
    def test_run_garbage_collection(self, mock_process_class, mock_gc_collect, mock_gc_get_objects):
        """Test garbage collection execution."""
        mock_process = MagicMock()
        mock_process.memory_info.side_effect = [
            MagicMock(rss=100 * 1024**2),  # Before
            MagicMock(rss=80 * 1024**2)    # After
        ]
        mock_process_class.return_value = mock_process

        mock_gc_collect.side_effect = [10, 5, 2]  # Different generations

        # Control GC objects count before/after
        mock_gc_get_objects.side_effect = [
            [MagicMock()] * 120,  # before
            [MagicMock()] * 100,  # after
        ]

        monitor = MemoryMonitor()
        result = monitor.run_garbage_collection()

        assert result["collected"] == 17  # Sum of generations
        assert result["freed_objects"] == 20  # Before - after
        assert result["freed_memory"] == 20 * 1024**2  # 20 MB

        # Should have updated last GC time
        assert monitor._last_gc_time <= time.time()

    @patch("psutil.virtual_memory")
    @patch("psutil.Process")
    @patch("psutil.cpu_count")
    @patch("psutil.cpu_percent")
    @patch("gc.get_objects")
    @patch("gc.garbage")
    def test_get_system_info(self, mock_gc_garbage, mock_gc_objects, mock_cpu_percent,
                           mock_cpu_count, mock_process_class, mock_virtual_memory):
        """Test comprehensive system information retrieval."""
        # Mock system memory
        mock_system_mem = MagicMock()
        mock_system_mem.total = 8 * 1024**3
        mock_system_mem.available = 4 * 1024**3
        mock_system_mem.percent = 50.0
        mock_virtual_memory.return_value = mock_system_mem

        # Mock process
        mock_process = MagicMock()
        mock_process.memory_info.return_value = MagicMock(rss=256 * 1024**2, vms=512 * 1024**2)
        mock_process.memory_percent.return_value = 3.2
        mock_process_class.return_value = mock_process

        # Mock CPU
        mock_cpu_count.return_value = 4
        mock_cpu_percent.return_value = 25.0

        # Mock GC
        mock_gc_objects.return_value = [MagicMock()] * 1000
        mock_gc_garbage.__len__.return_value = 5

        monitor = MemoryMonitor()
        monitor._cache_sizes["test_cache"] = 10 * 1024**2  # 10 MB
        monitor._memory_alerts["warning"] = 2

        info = monitor.get_system_info()

        assert info["memory"]["system"]["total_gb"] == 8.0
        assert info["memory"]["system"]["available_gb"] == 4.0
        assert info["memory"]["system"]["used_percentage"] == 50.0
        assert info["memory"]["process"]["rss_mb"] == 256.0
        assert info["memory"]["process"]["percentage"] == 3.2
        assert info["memory"]["python"]["gc_objects"] == 1000
        assert info["memory"]["python"]["reference_cycles"] == 5
        assert info["caches"]["test_cache"] == "10.00MB"
        assert info["alerts"]["warning"] == 2
        assert info["cpu"]["count"] == 4
        assert info["cpu"]["usage_percent"] == 25.0

    @patch("sam.utils.memory_monitor.logger")
    async def test_periodic_check_normal(self, mock_logger):
        """Test periodic memory check under normal conditions."""
        monitor = MemoryMonitor()

        with patch.object(monitor, "check_memory_thresholds", return_value={}), \
             patch.object(monitor, "should_run_gc", return_value=False):

            # Run periodic check briefly
            task = asyncio.create_task(monitor.periodic_check(interval=0.01))
            await asyncio.sleep(0.02)  # Let it run briefly
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            # No specific assertions; ensure no exceptions

    @patch("sam.utils.memory_monitor.logger")
    async def test_periodic_check_with_alerts(self, mock_logger):
        """Test periodic memory check with alerts."""
        monitor = MemoryMonitor()

        with patch.object(monitor, "check_memory_thresholds", return_value={"warning": "High memory"}), \
             patch.object(monitor, "should_run_gc", return_value=False):

            # Run periodic check briefly
            task = asyncio.create_task(monitor.periodic_check(interval=0.01))
            await asyncio.sleep(0.02)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_logger.warning.assert_called()

    @patch("sam.utils.memory_monitor.logger")
    async def test_periodic_check_with_gc(self, mock_logger):
        """Test periodic memory check triggering GC."""
        monitor = MemoryMonitor()

        with patch.object(monitor, "check_memory_thresholds", return_value={"critical": "Very high memory"}), \
             patch.object(monitor, "should_run_gc", return_value=True), \
             patch.object(monitor, "run_garbage_collection") as mock_gc:

            # Run periodic check briefly
            task = asyncio.create_task(monitor.periodic_check(interval=0.01))
            await asyncio.sleep(0.02)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_logger.error.assert_called()
            mock_gc.assert_called()

    @patch("sam.utils.memory_monitor.logger")
    async def test_periodic_check_exception_handling(self, mock_logger):
        """Test periodic memory check exception handling."""
        monitor = MemoryMonitor()

        with patch.object(monitor, "check_memory_thresholds", side_effect=Exception("Test error")):

            # Run periodic check briefly
            task = asyncio.create_task(monitor.periodic_check(interval=0.01))
            await asyncio.sleep(0.02)
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_logger.error.assert_called()


class TestGlobalMemoryMonitor:
    """Test global memory monitor functions."""

    def test_get_memory_monitor_singleton(self):
        """Test global memory monitor singleton pattern."""
        # Reset global state
        import sam.utils.memory_monitor
        sam.utils.memory_monitor._global_monitor = None

        monitor1 = get_memory_monitor()
        monitor2 = get_memory_monitor()

        assert monitor1 is monitor2
        assert isinstance(monitor1, MemoryMonitor)

    def test_get_memory_monitor_custom_thresholds(self):
        """Test global memory monitor with custom thresholds."""
        # Reset global state
        import sam.utils.memory_monitor
        sam.utils.memory_monitor._global_monitor = None

        thresholds = MemoryThresholds(warning_threshold=75.0)
        monitor = get_memory_monitor(thresholds)

        assert monitor.thresholds.warning_threshold == 75.0

    @patch("asyncio.create_task")
    async def test_start_memory_monitoring(self, mock_create_task):
        """Test starting background memory monitoring."""
        mock_task = MagicMock()
        mock_create_task.return_value = mock_task

        with patch("sam.utils.memory_monitor.logger") as mock_logger:
            task = await start_memory_monitoring(interval=30)

            assert task is mock_task
            mock_create_task.assert_called_once()
            mock_logger.info.assert_called_once()

    def test_monitor_memory_decorator(self):
        """Test memory monitoring decorator."""
        monitor = MemoryMonitor()

        @monitor_memory(cache_name="test_function")
        def test_function():
            return [1, 2, 3, 4, 5]  # Some data to measure

        with patch("sam.utils.memory_monitor.get_memory_monitor", return_value=monitor), \
             patch.object(monitor, "should_run_gc", return_value=False), \
             patch.object(monitor, "register_cache_usage") as mock_register:

            result = test_function()

            assert result == [1, 2, 3, 4, 5]
            mock_register.assert_called_once()

    def test_monitor_memory_decorator_with_gc(self):
        """Test memory monitoring decorator triggering GC."""
        monitor = MemoryMonitor()

        @monitor_memory()
        def test_function():
            return "test result"

        with patch("sam.utils.memory_monitor.get_memory_monitor", return_value=monitor), \
             patch.object(monitor, "should_run_gc", return_value=True), \
             patch.object(monitor, "run_garbage_collection") as mock_gc:

            result = test_function()

            assert result == "test result"
            mock_gc.assert_called_once()

    def test_monitor_memory_decorator_no_cache_name(self):
        """Test memory monitoring decorator without cache name."""
        monitor = MemoryMonitor()

        @monitor_memory()
        def test_function():
            return "test result"

        with patch("sam.utils.memory_monitor.get_memory_monitor", return_value=monitor), \
             patch.object(monitor, "should_run_gc", return_value=False), \
             patch.object(monitor, "register_cache_usage") as mock_register:

            result = test_function()

            assert result == "test result"
            # Should not register cache usage without cache name
            mock_register.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])

