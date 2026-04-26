param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputFile,

    [string]$Format = "json",
    [string]$TargetPages = ""
)

$ErrorActionPreference = "Stop"
$env:TESSDATA_PREFIX = "C:\Program Files\Tesseract-OCR\tessdata"

$argsList = @("parse", $InputFile, "--format", $Format, "-o", $OutputFile)
if ($TargetPages -ne "") {
    $argsList += @("--target-pages", $TargetPages)
}

$npxCmd = "npx"
if (Test-Path "C:\Program Files\nodejs\npx.cmd") {
    $npxCmd = "C:\Program Files\nodejs\npx.cmd"
} elseif (Get-Command npx.cmd -ErrorAction SilentlyContinue) {
    $npxCmd = (Get-Command npx.cmd).Source
}

& $npxCmd -y @llamaindex/liteparse @argsList
