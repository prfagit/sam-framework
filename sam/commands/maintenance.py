"""Maintenance and health commands for SAM CLI."""

from ..config.settings import Settings


async def run_maintenance() -> int:
    """Run database cleanup and maintenance tasks."""
    print("🔧 SAM Framework Maintenance")
    print("Running database cleanup and maintenance tasks...")

    try:
        from ..core.memory import MemoryManager
        from ..utils.error_handling import get_error_tracker

        memory = MemoryManager(Settings.SAM_DB_PATH)
        await memory.initialize()

        error_tracker = await get_error_tracker()

        print("\n📊 Current database stats:")
        stats = await memory.get_session_stats()
        size_info = await memory.get_database_size()
        print(f"  Sessions: {stats.get('sessions', 0)}")
        print(f"  Preferences: {stats.get('preferences', 0)}")
        print(f"  Trades: {stats.get('trades', 0)}")
        print(f"  Secure data: {stats.get('secure_data', 0)}")
        print(f"  Database size: {size_info.get('size_mb', 0)} MB")

        print("\n🧹 Cleaning up old sessions...")
        deleted_sessions = await memory.cleanup_old_sessions(30)
        print(f"  Deleted {deleted_sessions} old sessions")

        print("\n🧹 Cleaning up old trades...")
        deleted_trades = await memory.cleanup_old_trades(90)
        print(f"  Deleted {deleted_trades} old trades")

        print("\n🧹 Cleaning up old errors...")
        deleted_errors = await error_tracker.cleanup_old_errors(30)
        print(f"  Deleted {deleted_errors} old error records")

        print("\n🔧 Vacuuming database...")
        vacuum_success = await memory.vacuum_database()
        if vacuum_success:
            print("  Database vacuum completed successfully")
        else:
            print("  Database vacuum failed")

        print("\n📊 Post-maintenance stats:")
        final_stats = await memory.get_session_stats()
        final_size = await memory.get_database_size()
        print(f"  Sessions: {final_stats.get('sessions', 0)}")
        print(f"  Database size: {final_size.get('size_mb', 0)} MB")

        size_saved = size_info.get("size_mb", 0) - final_size.get("size_mb", 0)
        if size_saved > 0:
            print(f"  Space saved: {size_saved:.2f} MB")

        print("\n✅ Maintenance completed successfully")
        return 0

    except Exception as e:
        print(f"❌ Maintenance failed: {e}")
        return 1
