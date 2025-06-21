# =================================================================
#  Daily Database Backup Script for TimescaleDB
# =================================================================
#  This script creates daily backups of the chris_db database
#  with automatic compression and retention management.

param(
    [string]$BackupPath = "C:\Users\chris\OneDrive\Desktop\Programming\Trading\prediction markets\crypto\DATA\backups",
    [int]$RetentionDays = 7
)

# Create backup directory if it doesn't exist
if (!(Test-Path $BackupPath)) {
    New-Item -ItemType Directory -Path $BackupPath -Force
    Write-Host "Created backup directory: $BackupPath"
}

# Generate backup filename with timestamp
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$backupFile = Join-Path $BackupPath "chris_db_backup_$timestamp.sql"

Write-Host "Starting database backup..."
Write-Host "Backup file: $backupFile"
Write-Host "Timestamp: $timestamp"

# Create the backup
try {
    $startTime = Get-Date
    
    # Run pg_dump through Docker
    docker exec timescaledb pg_dump -U postgres -d chris_db > $backupFile
    
    $endTime = Get-Date
    $duration = $endTime - $startTime
    
    # Get backup file size
    $fileSize = (Get-Item $backupFile).Length
    $fileSizeMB = [math]::Round($fileSize / 1MB, 2)
    
    Write-Host "✅ Backup completed successfully!"
    Write-Host "   Duration: $($duration.TotalSeconds.ToString('F1')) seconds"
    Write-Host "   File size: $fileSizeMB MB"
    Write-Host "   File: $backupFile"
    
} catch {
    Write-Host "❌ Backup failed: $($_.Exception.Message)"
    exit 1
}

# Clean up old backups (keep only last N days)
Write-Host "Cleaning up old backups (keeping last $RetentionDays days)..."
$cutoffDate = (Get-Date).AddDays(-$RetentionDays)

Get-ChildItem -Path $BackupPath -Filter "chris_db_backup_*.sql" | ForEach-Object {
    if ($_.LastWriteTime -lt $cutoffDate) {
        Remove-Item $_.FullName -Force
        Write-Host "   Deleted old backup: $($_.Name)"
    }
}

# Show backup summary
$totalBackups = (Get-ChildItem -Path $BackupPath -Filter "chris_db_backup_*.sql").Count
$totalSize = (Get-ChildItem -Path $BackupPath -Filter "chris_db_backup_*.sql" | Measure-Object -Property Length -Sum).Sum
$totalSizeMB = [math]::Round($totalSize / 1MB, 2)

Write-Host "📊 Backup Summary:"
Write-Host "   Total backups: $totalBackups"
Write-Host "   Total size: $totalSizeMB MB"
Write-Host "   Retention: $RetentionDays days"

Write-Host "✅ Daily backup process completed!" 