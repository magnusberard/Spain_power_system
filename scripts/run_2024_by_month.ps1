# Run the 2024 market chain one calendar month at a time.
#
# Each month is a separate Julia process (memory is released in between) with
# its own results folder, results/2024_by_month/<yyyy-mm>/, and its own log
# (run.log there). A month whose summary.csv already exists is skipped, so
# after an interruption just start the script again; -Force re-runs them.
#
# Usage (PowerShell, from the repo root):
#     .\scripts\run_2024_by_month.ps1                                # 2024-01-02 .. 2024-12-29
#     .\scripts\run_2024_by_month.ps1 -From 2024-04-01 -To 2024-04-30
#     .\scripts\run_2024_by_month.ps1 -Force                         # redo finished months
#
# Uses config.toml as it stands, except for the study days (SPAIN_DAYS) and
# the results folder (SPAIN_RESULTS), which this script sets per month.
param(
    [string]$From = "2024-01-02",
    [string]$To = "2024-12-29",
    [switch]$Force
)

$repo = Split-Path -Parent $PSScriptRoot
$outRoot = Join-Path $repo "results\2024_by_month"
New-Item -ItemType Directory -Force $outRoot | Out-Null

$start = [datetime]::ParseExact($From, "yyyy-MM-dd", $null)
$end = [datetime]::ParseExact($To, "yyyy-MM-dd", $null)
$done = @()
$failed = @()

$monthStart = $start
while ($monthStart -le $end) {
    $monthEnd = (Get-Date -Year $monthStart.Year -Month $monthStart.Month -Day 1).AddMonths(1).AddDays(-1).Date
    if ($monthEnd -gt $end) { $monthEnd = $end }
    $tag = $monthStart.ToString("yyyy-MM")
    $dir = Join-Path $outRoot $tag
    $days = "{0}:{1}" -f $monthStart.ToString("yyyy-MM-dd"), $monthEnd.ToString("yyyy-MM-dd")

    if ((Test-Path (Join-Path $dir "summary.csv")) -and -not $Force) {
        Write-Host "[$tag] already done ($dir), skipping"
    }
    else {
        New-Item -ItemType Directory -Force $dir | Out-Null
        $env:SPAIN_DAYS = $days
        $env:SPAIN_RESULTS = $dir
        $t0 = Get-Date
        Write-Host ("[$tag] {0}  running {1} ..." -f $t0.ToString("HH:mm"), $days)
        Push-Location $repo
        & julia --project=. run_market_chain.jl 2>&1 | Tee-Object -FilePath (Join-Path $dir "run.log")
        $code = $LASTEXITCODE
        Pop-Location
        $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
        if ($code -eq 0 -and (Test-Path (Join-Path $dir "summary.csv"))) {
            Write-Host "[$tag] finished in $mins min"
            $done += $tag
        }
        else {
            Write-Host "[$tag] FAILED (exit code $code) after $mins min - see $dir\run.log"
            $failed += $tag
        }
    }
    $monthStart = $monthEnd.AddDays(1)
}

Remove-Item Env:SPAIN_DAYS -ErrorAction SilentlyContinue
Remove-Item Env:SPAIN_RESULTS -ErrorAction SilentlyContinue
Write-Host ""
Write-Host ("Done this run: {0}" -f ($(if ($done) { $done -join ", " } else { "none" })))
if ($failed) { Write-Host ("Failed: {0}" -f ($failed -join ", ")) }
