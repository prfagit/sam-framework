"""Health check command for SAM CLI."""

from ..config.settings import Settings


async def run_health_check() -> int:
    """Run health checks on SAM framework components."""
    print("🏥 SAM Framework Health Check")

    try:
        from ..utils.error_handling import get_health_checker, get_error_tracker
        from ..utils.secure_storage import get_secure_storage
        from ..utils.rate_limiter import get_rate_limiter
        from ..core.memory import MemoryManager

        health_checker = get_health_checker()

        async def database_health():
            memory = MemoryManager(Settings.SAM_DB_PATH)
            await memory.initialize()
            stats = await memory.get_session_stats()
            return {"status": "ok", "stats": stats}

        async def secure_storage_health():
            storage = get_secure_storage()
            test_results = storage.test_keyring_access()
            diagnostics = storage.diagnostics()

            status = "healthy"
            if not test_results.get("keyring_available"):
                status = "degraded"
            if diagnostics.get("stale_cipher_blobs"):
                status = "attention"

            details = {
                "keyring_available": test_results.get("keyring_available"),
                "fallback_active": diagnostics.get("fallback_active"),
                "fallback_keys": diagnostics.get("fallback_keys"),
                "stale_keys": diagnostics.get("stale_keys"),
                "tracked_keys": diagnostics.get("tracked_keys"),
                "fallback_path": diagnostics.get("fallback_path"),
            }

            return {"status": status, "details": details}

        async def rate_limiter_health():
            limiter = await get_rate_limiter()
            num_keys = len(limiter.request_history)
            return {"status": "healthy", "active_keys": num_keys}

        async def error_tracker_health():
            tracker = await get_error_tracker()
            stats = await tracker.get_error_stats(24)
            return {"recent_errors": stats.get("total_errors", 0)}

        health_checker.register_health_check("database", database_health, 0)
        health_checker.register_health_check("secure_storage", secure_storage_health, 0)
        health_checker.register_health_check("rate_limiter", rate_limiter_health, 0)
        health_checker.register_health_check("error_tracker", error_tracker_health, 0)

        results = await health_checker.run_health_checks()

        print("\n🔍 Component Health Status:")
        all_healthy = True
        for component, result in results.items():
            if result:
                status = result.get("status", "unknown")
                if status == "healthy" or status == "ok":
                    print(f"  ✅ {component}: {status}")
                else:
                    print(f"  ❌ {component}: {status}")
                    if "error" in result:
                        print(f"     Error: {result['error']}")
                    all_healthy = False
                if "details" in result:
                    details = result["details"]
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if key != "status":
                                print(f"     {key}: {value}")
            else:
                print(f"  ❓ {component}: no data")
                all_healthy = False

        error_tracker = await get_error_tracker()
        error_stats = await error_tracker.get_error_stats(24)

        total_errors = error_stats.get("total_errors", 0)
        if total_errors > 0:
            print(f"\n⚠️  {total_errors} errors in the last 24 hours")
            severity_counts = error_stats.get("severity_counts", {})
            for severity, count in severity_counts.items():
                print(f"     {severity}: {count}")
            critical_errors = error_stats.get("critical_errors", [])
            if critical_errors:
                print("\n🚨 Recent critical errors:")
                for error in critical_errors[:3]:
                    print(
                        f"     {error['timestamp']}: {error['component']} - {error['error_message']}"
                    )
        else:
            print("\n✅ No errors in the last 24 hours")

        if all_healthy and total_errors == 0:
            print("\n🎉 All systems healthy!")
            return 0
        else:
            print("\n⚠️  Some issues detected")
            return 1

    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1
