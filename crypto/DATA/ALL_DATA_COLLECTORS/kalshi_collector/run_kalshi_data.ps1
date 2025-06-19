# Kalshi Data Collector PowerShell Script
# This script handles Ctrl+C gracefully and exits cleanly

Write-Host "Kalshi Data Collector" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop gracefully" -ForegroundColor Yellow
Write-Host ""

# Set up Ctrl+C handler
$null = Register-EngineEvent PowerShell.Exiting -Action {
    Write-Host "`nReceived shutdown signal - cleaning up..." -ForegroundColor Yellow
    exit 0
}

$loopCount = 0
do {
    $loopCount++
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp] Starting Kalshi data collector (attempt $loopCount)..." -ForegroundColor Cyan
    
    try {
        # Run the Python script
        python kalshi_data.py
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -eq 0) {
            Write-Host "[$timestamp] Collector exited normally" -ForegroundColor Green
            break
        } elseif ($exitCode -eq 99) {
            Write-Host "[$timestamp] Stale data detected - restarting in 15 seconds..." -ForegroundColor Yellow
            Write-Host "Press Ctrl+C to stop the collector" -ForegroundColor Yellow
            Start-Sleep -Seconds 15
        } else {
            Write-Host "[$timestamp] Collector crashed with code $exitCode - restarting in 15 seconds..." -ForegroundColor Red
            Write-Host "Press Ctrl+C to stop the collector" -ForegroundColor Yellow
            Start-Sleep -Seconds 15
        }
    }
    catch {
        Write-Host "[$timestamp] Error running collector: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Restarting in 15 seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds 15
    }
} while ($true)

Write-Host "`nCollector stopped." -ForegroundColor Green
Read-Host "Press Enter to exit" 