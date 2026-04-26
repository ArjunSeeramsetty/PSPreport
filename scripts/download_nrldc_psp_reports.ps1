param(
    [datetime]$StartDate = [datetime]"2023-04-01",
    [datetime]$EndDate = [datetime]"2026-05-29",
    [string]$OutputDir = "downloads/NRLDC_PSP",
    [int]$PageSize = 100,
    [int]$MaxAttempts = 3,
    [datetime]$LegacyEndDate = [datetime]"2024-03-31",
    [int]$LegacyTimeoutSec = 12,
    [switch]$TryLegacyPaths
)

$ErrorActionPreference = "Continue"
$baseUrl = "https://www.nrldc.in"
$pageUrl = "$baseUrl/daily/daily-psp-report"
$apiBase = "$baseUrl/get-documents-list/111"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Get-ReportDateFromRow {
    param($Row)

    $candidate = [string]$Row.file_name + " " + [string]$Row.title
    $match = [regex]::Match($candidate, "daily(\d{2})(\d{2})(\d{4})", "IgnoreCase")
    if ($match.Success) {
        try {
            return [datetime]::ParseExact(
                "$($match.Groups[1].Value)-$($match.Groups[2].Value)-$($match.Groups[3].Value)",
                "dd-MM-yyyy",
                $null
            ).Date
        }
        catch {}
    }

    $match = [regex]::Match($candidate, "daily(\d{2})(\d{2})(\d{2})(?!\d)", "IgnoreCase")
    if ($match.Success) {
        try {
            return [datetime]::ParseExact(
                "$($match.Groups[1].Value)-$($match.Groups[2].Value)-20$($match.Groups[3].Value)",
                "dd-MM-yyyy",
                $null
            ).Date
        }
        catch {}
    }

    if ($Row.file_date_sort) {
        try {
            return ([datetime]$Row.file_date_sort).Date
        }
        catch {}
    }

    return $null
}

function Get-DownloadUrlFromRow {
    param($Row)

    $html = [string]$Row.download
    $match = [regex]::Match($html, "href='([^']+)'")
    if (-not $match.Success) {
        return $null
    }

    $href = $match.Groups[1].Value.Replace("&amp;", "&")
    if ($href.StartsWith("/")) {
        return "$baseUrl$href"
    }
    return $href
}

function Invoke-DownloadWithRetry {
    param(
        [string]$Url,
        [string]$Destination
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            Invoke-WebRequest `
                -Uri $Url `
                -OutFile $Destination `
                -Headers @{ "Referer" = $pageUrl } `
                -UseBasicParsing `
                -TimeoutSec 90

            if ((Test-Path $Destination) -and ((Get-Item $Destination).Length -gt 0)) {
                return $true
            }
        }
        catch {
            $delay = [Math]::Min(12, [Math]::Pow(2, $attempt))
            Start-Sleep -Seconds $delay
        }
    }

    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    return $false
}

function Test-PdfFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $false
    }

    $file = Get-Item $Path
    if ($file.Length -lt 1024) {
        return $false
    }

    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $buffer = New-Object byte[] 4
            $bytesRead = $stream.Read($buffer, 0, 4)
            if ($bytesRead -ne 4) {
                return $false
            }
            $signature = [System.Text.Encoding]::ASCII.GetString($buffer)
            return $signature -eq "%PDF"
        }
        finally {
            $stream.Close()
        }
    }
    catch {
        return $false
    }
}

function Get-LegacyUrlsForDate {
    param([datetime]$ReportDate)

    $legacyFileName = "daily" + $ReportDate.ToString("ddMMyy") + ".pdf"
    $legacyHosts = @(
        "https://www.nrldc.in",
        "https://nrldc.in"
    )
    $legacyPaths = @(
        "/Websitedata/DoReport/pdf/$legacyFileName"
    )

    foreach ($legacyHost in $legacyHosts) {
        foreach ($legacyPath in $legacyPaths) {
            "$legacyHost$legacyPath"
        }
    }
}

function Invoke-LegacyDownloadWithRetry {
    param(
        [datetime]$ReportDate,
        [string]$OutputDir
    )

    $fileName = "nrldc-legacy-" + $ReportDate.ToString("yyyy-MM-dd") + "-daily" + $ReportDate.ToString("ddMMyy") + ".pdf"
    $destination = Join-Path $OutputDir $fileName

    if (Test-PdfFile -Path $destination) {
        return $true
    }

    foreach ($url in (Get-LegacyUrlsForDate -ReportDate $ReportDate)) {
        try {
            $preflight = Invoke-WebRequest `
                -Uri $url `
                -Method Head `
                -UseBasicParsing `
                -TimeoutSec $LegacyTimeoutSec `
                -ErrorAction Stop

            if ([int]$preflight.StatusCode -ge 400) {
                continue
            }
        }
        catch {
            continue
        }

        for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
            try {
                Invoke-WebRequest `
                    -Uri $url `
                    -OutFile $destination `
                    -Headers @{ "Referer" = "https://nrldc.in/reports/daily-reports/daily-regional-power-supply-position/" } `
                    -UseBasicParsing `
                    -TimeoutSec $LegacyTimeoutSec `
                    -ErrorAction Stop

                if (Test-PdfFile -Path $destination) {
                    return $true
                }
            }
            catch {
                $delay = [Math]::Min(12, [Math]::Pow(2, $attempt))
                Start-Sleep -Seconds $delay
            }
            finally {
                if ((Test-Path $destination) -and -not (Test-PdfFile -Path $destination)) {
                    Remove-Item -LiteralPath $destination -Force
                }
            }
        }
    }

    return $false
}

$page = Invoke-WebRequest -Uri $pageUrl -UseBasicParsing -TimeoutSec 45
$tokenMatch = [regex]::Match($page.Content, 'meta name="csrf_token" content="([^"]+)"')
if (-not $tokenMatch.Success) {
    throw "Could not find NRLDC CSRF token on $pageUrl"
}
$token = $tokenMatch.Groups[1].Value

$headers = @{
    "X-Requested-With" = "XMLHttpRequest"
    "X-CSRF-TOKEN" = $token
    "Referer" = $pageUrl
    "Accept" = "application/json, text/javascript, */*; q=0.01"
}

$rowsSeen = 0
$downloaded = 0
$alreadyPresent = 0
$skippedOutsideRange = 0
$failed = 0
$legacyAttempted = 0
$legacyDownloaded = 0
$legacyFailed = 0
$availableDates = New-Object System.Collections.Generic.HashSet[string]
$start = 0
$recordsTotal = $null

while ($true) {
    $apiUrl = "${apiBase}?draw=1&start=$start&length=$PageSize"
    $response = Invoke-WebRequest -Uri $apiUrl -Headers $headers -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop
    $payload = $response.Content | ConvertFrom-Json

    if ($null -eq $recordsTotal) {
        $recordsTotal = [int]$payload.recordsTotal
    }
    if ($null -eq $payload.data -or $payload.data.Count -eq 0) {
        break
    }

    foreach ($row in $payload.data) {
        $rowsSeen += 1
        $reportDate = Get-ReportDateFromRow -Row $row
        if ($null -eq $reportDate) {
            continue
        }
        if ($reportDate -lt $StartDate.Date -or $reportDate -gt $EndDate.Date) {
            $skippedOutsideRange += 1
            continue
        }

        $availableDates.Add($reportDate.ToString("yyyy-MM-dd")) | Out-Null
        $url = Get-DownloadUrlFromRow -Row $row
        if ($null -eq $url) {
            $failed += 1
            continue
        }

        $fileName = [string]$row.file_name
        if ([string]::IsNullOrWhiteSpace($fileName)) {
            $fileName = "nrldc-" + $reportDate.ToString("dd-MM-yyyy") + "-psp.pdf"
        }
        if (-not $fileName.ToLower().EndsWith(".pdf")) {
            $fileName = "$fileName.pdf"
        }

        $destination = Join-Path $OutputDir $fileName
        if (Test-Path $destination) {
            $alreadyPresent += 1
            continue
        }

        if (Invoke-DownloadWithRetry -Url $url -Destination $destination) {
            $downloaded += 1
        }
        else {
            $failed += 1
        }
    }

    $start += $PageSize
    if ($start -ge $recordsTotal) {
        break
    }
}

$missing = New-Object System.Collections.Generic.List[string]
for ($day = $StartDate.Date; $day -le $EndDate.Date; $day = $day.AddDays(1)) {
    $key = $day.ToString("yyyy-MM-dd")
    if (-not $availableDates.Contains($key)) {
        $missing.Add($key)
    }
}

if ($TryLegacyPaths) {
    $legacyMissing = @($missing)
    foreach ($missingDate in $legacyMissing) {
        $reportDate = [datetime]::ParseExact($missingDate, "yyyy-MM-dd", $null)
        if ($reportDate -gt $LegacyEndDate.Date) {
            continue
        }

        $legacyAttempted += 1
        if (Invoke-LegacyDownloadWithRetry -ReportDate $reportDate -OutputDir $OutputDir) {
            $legacyDownloaded += 1
            $availableDates.Add($missingDate) | Out-Null
        }
        else {
            $legacyFailed += 1
        }
    }

    $missing = New-Object System.Collections.Generic.List[string]
    for ($day = $StartDate.Date; $day -le $EndDate.Date; $day = $day.AddDays(1)) {
        $key = $day.ToString("yyyy-MM-dd")
        if (-not $availableDates.Contains($key)) {
            $missing.Add($key)
        }
    }
}

$manifest = Join-Path (Split-Path $OutputDir -Parent) "missing_nrldc_dates.txt"
$missing | Set-Content -Path $manifest -Encoding UTF8

[pscustomobject]@{
    records_total = $recordsTotal
    rows_seen = $rowsSeen
    already_present = $alreadyPresent
    downloaded = $downloaded
    skipped_outside_range = $skippedOutsideRange
    failed = $failed
    legacy_attempted = $legacyAttempted
    legacy_downloaded = $legacyDownloaded
    legacy_failed = $legacyFailed
    available_dates_in_range = $availableDates.Count
    missing_after = $missing.Count
    manifest = $manifest
}
