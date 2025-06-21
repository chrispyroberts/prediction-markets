#!/bin/bash
# =================================================================
#  Daily Database Backup Script for TimescaleDB (Docker)
# =================================================================
#  This script runs inside the Docker container and creates
#  daily backups of the chris_db database.

# Configuration
BACKUP_DIR="/var/lib/postgresql/backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="chris_db_backup_${TIMESTAMP}.sql"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Starting database backup..."
echo "Backup file: $BACKUP_FILE"
echo "Timestamp: $TIMESTAMP"

# Start timing
START_TIME=$(date +%s)

# Create the backup
if pg_dump -U postgres -d chris_db > "$BACKUP_DIR/$BACKUP_FILE"; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    
    # Get backup file size
    FILE_SIZE=$(stat -c%s "$BACKUP_DIR/$BACKUP_FILE")
    FILE_SIZE_MB=$(echo "scale=2; $FILE_SIZE / 1048576" | bc)
    
    echo "✅ Backup completed successfully!"
    echo "   Duration: ${DURATION} seconds"
    echo "   File size: ${FILE_SIZE_MB} MB"
    echo "   File: $BACKUP_FILE"
else
    echo "❌ Backup failed!"
    exit 1
fi

# Clean up old backups (keep only last N days)
echo "Cleaning up old backups (keeping last $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -name "chris_db_backup_*.sql" -type f -mtime +$RETENTION_DAYS -delete -print | while read file; do
    echo "   Deleted old backup: $(basename "$file")"
done

# Show backup summary
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "chris_db_backup_*.sql" | wc -l)
TOTAL_SIZE=$(find "$BACKUP_DIR" -name "chris_db_backup_*.sql" -exec stat -c%s {} \; | awk '{sum+=$1} END {print sum}')
TOTAL_SIZE_MB=$(echo "scale=2; $TOTAL_SIZE / 1048576" | bc)

echo "📊 Backup Summary:"
echo "   Total backups: $TOTAL_BACKUPS"
echo "   Total size: ${TOTAL_SIZE_MB} MB"
echo "   Retention: $RETENTION_DAYS days"

echo "✅ Daily backup process completed!" 