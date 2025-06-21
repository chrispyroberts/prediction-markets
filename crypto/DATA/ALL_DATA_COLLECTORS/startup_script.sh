#!/bin/bash
# =================================================================
#  Database Startup Script
# =================================================================
#  Run this after starting the Docker container to restore
#  cron jobs and verify everything is working.

echo "🚀 Starting database setup..."

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
sleep 5

# Test database connection
if docker exec -it timescaledb psql -U postgres -d chris_db -c "SELECT 'Database is ready!' as status;" > /dev/null 2>&1; then
    echo "✅ Database connection successful"
else
    echo "❌ Database connection failed"
    exit 1
fi

# Restore cron job for backups
echo "📅 Restoring backup cron job..."
docker exec -it timescaledb bash -c "echo '0 2 * * * /tmp/backup_script.sh >> /var/log/backup.log 2>&1' | crontab -"

# Verify cron job was added
if docker exec -it timescaledb bash -c "crontab -l" | grep -q "backup_script.sh"; then
    echo "✅ Backup cron job restored"
else
    echo "❌ Failed to restore cron job"
fi

# Check compression policies
echo "📊 Checking compression policies..."
docker exec -it timescaledb psql -U postgres -d chris_db -c "SELECT hypertable_name, config->>'compress_after' as compress_after_ms FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression' ORDER BY hypertable_name;"

# Check database size
echo "💾 Current database size:"
docker exec -it timescaledb psql -U postgres -d chris_db -c "SELECT pg_size_pretty(pg_database_size('chris_db'));"

echo "✅ Database startup complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Start your data collectors"
echo "   2. Monitor compression and backups"
echo "   3. Check logs: docker exec -it timescaledb cat /var/log/backup.log" 