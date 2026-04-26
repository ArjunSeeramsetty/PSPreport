param(
    [datetime]$StartDate = [datetime]"2023-04-01",
    [datetime]$EndDate = [datetime]"2025-07-10",
    [string]$OutputDir = "downloads/SRLDC_PSP",
    [int]$MaxAttempts = 3
)

$ErrorActionPreference = "Continue"
$months = @{
    1 = "Jan"; 2 = "Feb"; 3 = "Mar"; 4 = "Apr"; 5 = "May"; 6 = "Jun";
    7 = "Jul"; 8 = "Aug"; 9 = "Sep"; 10 = "Oct"; 11 = "Nov"; 12 = "Dec"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$daysScanned = 0
$alreadyPresent = 0
$downloaded = 0
$failed = 0
$remaining = New-Object System.Collections.Generic.List[string]

for ($day = $StartDate; $day -le $EndDate; $day = $day.AddDays(1)) {
    $daysScanned += 1
    $fileName = $day.ToString("dd-MM-yyyy") + "-psp.pdf"
    $destination = Join-Path $OutputDir $fileName

    if (Test-Path $destination) {
        $alreadyPresent += 1
        continue
    }

    $monthFolder = $months[[int]$day.Month] + $day.ToString("yy")
    $url = "https://srldc.in/var/ftp/reports/psp/$($day.Year)/$monthFolder/$fileName"
    $success = $false

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $destination -UseBasicParsing -TimeoutSec 60
            if ((Test-Path $destination) -and ((Get-Item $destination).Length -gt 0)) {
                $downloaded += 1
                $success = $true
                break
            }
        }
        catch {
            $delay = [Math]::Min(12, [Math]::Pow(2, $attempt))
            Start-Sleep -Seconds $delay
        }
    }

    if (-not $success) {
        if (Test-Path $destination) {
            Remove-Item -LiteralPath $destination -Force
        }
        $failed += 1
        $remaining.Add($day.ToString("yyyy-MM-dd"))
    }
}

$manifest = Join-Path (Split-Path $OutputDir -Parent) "missing_srldc_dates.txt"
$remaining | Set-Content -Path $manifest -Encoding UTF8

[pscustomobject]@{
    days_scanned = $daysScanned
    already_present = $alreadyPresent
    downloaded = $downloaded
    failed = $failed
    missing_after = $remaining.Count
    manifest = $manifest
}
