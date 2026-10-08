# Resident daily trigger for the SEO blog engine.
# Startup runs this hidden process at sign-in; it starts the job at/after 9:00 AM local,
# then checks every 15 minutes. daily-run.ps1 enforces the once-per-day state and lock.

$jobScript = Join-Path $PSScriptRoot 'daily-run.ps1'
$pollSeconds = 900
$runAfter = [TimeSpan]::FromHours(9)

while ($true) {
    if ((Get-Date).TimeOfDay -ge $runAfter) {
        & $jobScript
    }
    Start-Sleep -Seconds $pollSeconds
}
