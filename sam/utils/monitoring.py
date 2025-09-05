"""Monitoring and metrics utilities for SAM framework."""

import asyncio
import functools
import logging
import time
import psutil
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SystemMetrics:
    """System performance metrics."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    disk_percent: float
    process_memory_mb: float
    process_cpu_percent: float
    open_files: int
    thread_count: int


@dataclass
class ComponentMetric:
    """Component-specific performance metric."""
    component: str
    operation: str
    duration: float
    timestamp: float
    success: bool
    error_type: Optional[str] = None


class MetricsCollector:
    """Collect and track performance metrics."""
    
    def __init__(self, max_metrics: int = 1000, collection_interval: int = 60):
        self.max_metrics = max_metrics
        self.collection_interval = collection_interval
        
        # Metrics storage
        self.system_metrics: List[SystemMetrics] = []
        self.component_metrics: List[ComponentMetric] = []
        
        # Operation counters
        self.operation_counts: Dict[str, int] = {}
        self.error_counts: Dict[str, int] = {}
        
        # Performance tracking
        self.slow_operations: List[ComponentMetric] = []
        
        self._collection_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        logger.info(f"Initialized metrics collector (max_metrics: {max_metrics})")
    
    def start_collection(self):
        """Start automatic metrics collection."""
        if self._collection_task is None or self._collection_task.done():
            self._collection_task = asyncio.create_task(self._collect_system_metrics())
    
    async def _collect_system_metrics(self):
        """Collect system metrics periodically."""
        while not self._shutdown:
            try:
                await asyncio.sleep(self.collection_interval)
                
                if self._shutdown:
                    break
                
                # Get system metrics
                metrics = SystemMetrics(
                    timestamp=time.time(),
                    cpu_percent=psutil.cpu_percent(interval=1),
                    memory_percent=psutil.virtual_memory().percent,
                    memory_used_mb=psutil.virtual_memory().used / (1024 * 1024),
                    disk_percent=psutil.disk_usage('/').percent,
                    process_memory_mb=psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024),
                    process_cpu_percent=psutil.Process(os.getpid()).cpu_percent(),
                    open_files=len(psutil.Process(os.getpid()).open_files()),
                    thread_count=psutil.Process(os.getpid()).num_threads()
                )
                
                # Store metrics (with rotation)
                self.system_metrics.append(metrics)
                if len(self.system_metrics) > self.max_metrics:
                    self.system_metrics = self.system_metrics[-self.max_metrics:]
                
                # Log warnings for high resource usage
                if metrics.memory_percent > 90:
                    logger.warning(f"High memory usage: {metrics.memory_percent:.1f}%")
                
                if metrics.cpu_percent > 90:
                    logger.warning(f"High CPU usage: {metrics.cpu_percent:.1f}%")
                
                if metrics.open_files > 100:
                    logger.warning(f"High number of open files: {metrics.open_files}")
                
            except Exception as e:
                logger.error(f"Error collecting system metrics: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    def record_operation(
        self, 
        component: str, 
        operation: str, 
        duration: float, 
        success: bool = True,
        error_type: Optional[str] = None
    ):
        """Record an operation metric."""
        metric = ComponentMetric(
            component=component,
            operation=operation,
            duration=duration,
            timestamp=time.time(),
            success=success,
            error_type=error_type
        )
        
        # Store metric
        self.component_metrics.append(metric)
        if len(self.component_metrics) > self.max_metrics:
            self.component_metrics = self.component_metrics[-self.max_metrics:]
        
        # Update counters
        key = f"{component}.{operation}"
        self.operation_counts[key] = self.operation_counts.get(key, 0) + 1
        
        if not success and error_type:
            error_key = f"{component}.{error_type}"
            self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Track slow operations (>5 seconds)
        if duration > 5.0:
            self.slow_operations.append(metric)
            if len(self.slow_operations) > 100:  # Keep last 100 slow operations
                self.slow_operations = self.slow_operations[-100:]
            
            logger.warning(f"Slow operation: {component}.{operation} took {duration:.3f}s")
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get current system health metrics."""
        if not self.system_metrics:
            return {"status": "no_data", "message": "No system metrics available"}
        
        latest = self.system_metrics[-1]
        
        # Determine health status
        issues = []
        if latest.memory_percent > 85:
            issues.append(f"High memory usage: {latest.memory_percent:.1f}%")
        if latest.cpu_percent > 85:
            issues.append(f"High CPU usage: {latest.cpu_percent:.1f}%")
        if latest.open_files > 150:
            issues.append(f"Many open files: {latest.open_files}")
        
        status = "critical" if any("High" in issue for issue in issues) else \
                "warning" if issues else "healthy"
        
        return {
            "status": status,
            "issues": issues,
            "timestamp": latest.timestamp,
            "metrics": {
                "cpu_percent": latest.cpu_percent,
                "memory_percent": latest.memory_percent,
                "memory_used_mb": latest.memory_used_mb,
                "process_memory_mb": latest.process_memory_mb,
                "open_files": latest.open_files,
                "thread_count": latest.thread_count
            }
        }
    
    def get_performance_stats(self, component: Optional[str] = None, hours: int = 1) -> Dict[str, Any]:
        """Get performance statistics for components."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter metrics
        recent_metrics = [m for m in self.component_metrics if m.timestamp > cutoff_time]
        if component:
            recent_metrics = [m for m in recent_metrics if m.component == component]
        
        if not recent_metrics:
            return {"status": "no_data", "component": component, "hours": hours}
        
        # Calculate stats
        total_operations = len(recent_metrics)
        successful_operations = len([m for m in recent_metrics if m.success])
        failed_operations = total_operations - successful_operations
        
        durations = [m.duration for m in recent_metrics]
        avg_duration = sum(durations) / len(durations)
        max_duration = max(durations)
        min_duration = min(durations)
        
        # Get top errors
        error_counts = {}
        for metric in recent_metrics:
            if not metric.success and metric.error_type:
                error_counts[metric.error_type] = error_counts.get(metric.error_type, 0) + 1
        
        top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "component": component or "all",
            "hours": hours,
            "total_operations": total_operations,
            "successful_operations": successful_operations,
            "failed_operations": failed_operations,
            "success_rate": (successful_operations / total_operations) * 100 if total_operations > 0 else 0,
            "performance": {
                "avg_duration": avg_duration,
                "max_duration": max_duration,
                "min_duration": min_duration
            },
            "top_errors": top_errors
        }
    
    def get_slow_operations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent slow operations."""
        recent_slow = sorted(
            self.slow_operations, 
            key=lambda x: x.duration, 
            reverse=True
        )[:limit]
        
        return [
            {
                "component": op.component,
                "operation": op.operation,
                "duration": op.duration,
                "timestamp": op.timestamp,
                "success": op.success,
                "error_type": op.error_type
            }
            for op in recent_slow
        ]
    
    async def shutdown(self):
        """Shutdown metrics collection."""
        self._shutdown = True
        if self._collection_task and not self._collection_task.done():
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Metrics collector shutdown completed")


# Global metrics collector
_global_metrics_collector: Optional[MetricsCollector] = None


async def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    global _global_metrics_collector
    
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
        _global_metrics_collector.start_collection()
    
    return _global_metrics_collector


async def cleanup_metrics_collector():
    """Cleanup global metrics collector."""
    global _global_metrics_collector
    if _global_metrics_collector:
        await _global_metrics_collector.shutdown()
        _global_metrics_collector = None


def record_operation_metric(component: str, operation: str, duration: float, success: bool = True, error_type: Optional[str] = None):
    """Convenience function to record operation metrics."""
    try:
        # Create a task to record the metric asynchronously
        async def _record():
            collector = await get_metrics_collector()
            collector.record_operation(component, operation, duration, success, error_type)
        
        # Try to schedule the task
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_record())
            else:
                logger.debug("Event loop not running, skipping metric recording")
        except RuntimeError:
            logger.debug("No event loop available, skipping metric recording")
    except Exception as e:
        logger.debug(f"Failed to record metric: {e}")


# Performance monitoring decorator
def monitor_performance(component: str, operation: str):
    """Decorator to monitor operation performance."""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            error_type = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_type = type(e).__name__
                raise
            finally:
                duration = time.time() - start_time
                record_operation_metric(component, operation, duration, success, error_type)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            error_type = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error_type = type(e).__name__
                raise
            finally:
                duration = time.time() - start_time
                record_operation_metric(component, operation, duration, success, error_type)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator