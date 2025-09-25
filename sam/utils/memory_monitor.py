"""Memory monitoring and management utilities."""

import asyncio
from asyncio import Task
import functools
import logging
import psutil
import gc
import sys
from typing import Any, Callable, DefaultDict, Dict, Optional, TypeVar, cast
from dataclasses import dataclass
from collections import defaultdict
import time

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class MemoryStats:
    """Memory usage statistics."""

    total_ram: int
    available_ram: int
    used_ram: int
    ram_percentage: float
    process_rss: int
    process_vms: int
    process_percentage: float
    gc_objects: int


@dataclass
class MemoryThresholds:
    """Memory usage thresholds for alerts and actions."""

    warning_threshold: float = 80.0  # Warn at 80% memory usage
    critical_threshold: float = 90.0  # Take action at 90% memory usage
    max_cache_size_mb: int = 100  # Max cache size in MB
    gc_frequency: int = 100  # GC every N operations


class MemoryMonitor:
    """Memory monitoring and management system."""

    def __init__(self, thresholds: Optional[MemoryThresholds] = None):
        self.thresholds = thresholds or MemoryThresholds()
        self._operation_count = 0
        self._cache_sizes: DefaultDict[str, int] = defaultdict(int)
        self._last_gc_time = time.time()
        self._memory_alerts: DefaultDict[str, int] = defaultdict(int)
        logger.info(f"Memory monitor initialized with thresholds: {self.thresholds}")

    def get_memory_stats(self) -> MemoryStats:
        """Get current memory usage statistics."""
        # System memory
        system_mem = psutil.virtual_memory()

        # Process memory
        process = psutil.Process()
        process_mem = process.memory_info()

        # Python GC objects
        gc_count = len(gc.get_objects())

        return MemoryStats(
            total_ram=system_mem.total,
            available_ram=system_mem.available,
            used_ram=system_mem.used,
            ram_percentage=system_mem.percent,
            process_rss=process_mem.rss,
            process_vms=process_mem.vms,
            process_percentage=process.memory_percent(),
            gc_objects=gc_count,
        )

    def check_memory_thresholds(self) -> Dict[str, Any]:
        """Check if memory usage exceeds thresholds."""
        stats = self.get_memory_stats()
        alerts = {}

        if stats.ram_percentage > self.thresholds.critical_threshold:
            alerts["critical"] = f"System memory at {stats.ram_percentage:.1f}%"
            self._memory_alerts["critical"] += 1
        elif stats.ram_percentage > self.thresholds.warning_threshold:
            alerts["warning"] = f"System memory at {stats.ram_percentage:.1f}%"
            self._memory_alerts["warning"] += 1

        if stats.process_percentage > self.thresholds.warning_threshold:
            alerts["process_warning"] = f"Process memory at {stats.process_percentage:.1f}%"

        return alerts

    def register_cache_usage(self, cache_name: str, size_bytes: int) -> None:
        """Register cache size for monitoring."""
        self._cache_sizes[cache_name] = size_bytes

        # Check if any cache exceeds limits
        max_bytes = self.thresholds.max_cache_size_mb * 1024 * 1024
        if size_bytes > max_bytes:
            logger.warning(
                f"Cache '{cache_name}' exceeds limit: {size_bytes / 1024 / 1024:.1f}MB > "
                f"{self.thresholds.max_cache_size_mb}MB"
            )

    def should_run_gc(self) -> bool:
        """Check if garbage collection should be run."""
        self._operation_count += 1
        current_time = time.time()

        # Run GC based on operation count or time interval
        if (
            self._operation_count % self.thresholds.gc_frequency == 0
            or current_time - self._last_gc_time > 300
        ):  # 5 minutes
            return True

        # Run GC if memory is high
        alerts = self.check_memory_thresholds()
        return "warning" in alerts or "critical" in alerts

    def run_garbage_collection(self) -> Dict[str, int]:
        """Run garbage collection and log results."""
        before_objects = len(gc.get_objects())
        before_mem = psutil.Process().memory_info().rss

        # Run all GC generations
        collected = sum(gc.collect(generation) for generation in range(3))

        after_objects = len(gc.get_objects())
        after_mem = psutil.Process().memory_info().rss

        freed_objects = before_objects - after_objects
        freed_memory = before_mem - after_mem

        if collected > 0 or freed_objects > 100:
            logger.info(
                f"Garbage collection: {collected} objects collected, "
                f"{freed_objects} objects freed, "
                f"{freed_memory / 1024 / 1024:.1f}MB memory freed"
            )

        self._last_gc_time = time.time()
        return {
            "collected": collected,
            "freed_objects": freed_objects,
            "freed_memory": freed_memory,
        }

    def get_system_info(self) -> Dict[str, Any]:
        """Get comprehensive system and memory information."""
        stats = self.get_memory_stats()

        return {
            "memory": {
                "system": {
                    "total_gb": stats.total_ram / 1024**3,
                    "available_gb": stats.available_ram / 1024**3,
                    "used_percentage": stats.ram_percentage,
                },
                "process": {
                    "rss_mb": stats.process_rss / 1024**2,
                    "vms_mb": stats.process_vms / 1024**2,
                    "percentage": stats.process_percentage,
                },
                "python": {
                    "gc_objects": stats.gc_objects,
                    "reference_cycles": len(gc.garbage),
                },
            },
            "caches": {
                name: f"{size / 1024 / 1024:.2f}MB" for name, size in self._cache_sizes.items()
            },
            "alerts": dict(self._memory_alerts),
            "cpu": {
                "count": psutil.cpu_count(),
                "usage_percent": psutil.cpu_percent(interval=0.1),
            },
            "thresholds": {
                "warning": f"{self.thresholds.warning_threshold}%",
                "critical": f"{self.thresholds.critical_threshold}%",
                "max_cache": f"{self.thresholds.max_cache_size_mb}MB",
            },
        }

    async def periodic_check(self, interval: int = 60) -> None:
        """Run periodic memory checks and cleanup."""
        while True:
            try:
                alerts = self.check_memory_thresholds()

                if alerts:
                    for level, message in alerts.items():
                        if level == "critical":
                            logger.error(f"CRITICAL: {message}")
                            # Force GC on critical memory usage
                            self.run_garbage_collection()
                        else:
                            logger.warning(f"WARNING: {message}")

                if self.should_run_gc():
                    self.run_garbage_collection()

                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"Error in memory monitor periodic check: {e}")
                await asyncio.sleep(interval)


# Global memory monitor instance
_global_monitor: Optional[MemoryMonitor] = None


def get_memory_monitor(thresholds: Optional[MemoryThresholds] = None) -> MemoryMonitor:
    """Get global memory monitor instance."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = MemoryMonitor(thresholds)
    return _global_monitor


async def start_memory_monitoring(
    interval: int = 60, thresholds: Optional[MemoryThresholds] = None
) -> Task[None]:
    """Start background memory monitoring task."""
    monitor = get_memory_monitor(thresholds)
    task = asyncio.create_task(monitor.periodic_check(interval))
    logger.info(f"Started memory monitoring with {interval}s interval")
    return task


# Decorator for automatic memory monitoring
def monitor_memory(cache_name: Optional[str] = None) -> Callable[[F], F]:
    """Decorator to monitor memory usage of functions."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            monitor = get_memory_monitor()

            if monitor.should_run_gc():
                monitor.run_garbage_collection()

            result = func(*args, **kwargs)

            if cache_name and hasattr(result, "__len__"):
                try:
                    size = sys.getsizeof(result)
                    monitor.register_cache_usage(cache_name, size)
                except (TypeError, AttributeError):
                    pass

            return result

        return cast(F, wrapper)

    return decorator
