param(
    [string]$SourcePath,
    [string]$RuntimeZipPath,
    [string]$Destination,
    [switch]$NoStartup
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = "https://raw.githubusercontent.com/cyberythem/kuGPT/2c56e5b0d557f0a15d50257833f5715ed0b32aa4"
$PythonUrl = "https://www.python.org/ftp/python/3.13.7/python-3.13.7-embed-amd64.zip"
$PythonSha256 = "F6CCA216A359BE84797CABB54149CE5E062AFB16CC7567EB7FC51CACB2D86B65"
$DictionaryUrl = "https://raw.githubusercontent.com/wolfgarbe/SymSpell/v6.7.3/SymSpell/frequency_dictionary_en_82_765.txt"
$DictionarySha256 = "C604E1121E398AE7C7FBF777F11E0A0F2FA66EDA932CB9FBA1321466CF3ACD7B"
$InstallDirectory = if ($Destination) { [IO.Path]::GetFullPath($Destination) } else { Join-Path $env:LOCALAPPDATA "kuGPT" }
$StageDirectory = Join-Path $env:TEMP ("kugpt-install-" + [Guid]::NewGuid().ToString("N"))
$RuntimeDirectory = Join-Path $InstallDirectory "runtime"
$LauncherPath = Join-Path $InstallDirectory "kugpt_launcher.py"

function Copy-OrDownload([string]$RelativePath, [string]$Target) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    if ($SourcePath) {
        Copy-Item -LiteralPath (Join-Path $SourcePath $RelativePath) -Destination $Target -Force
    }
    else {
        $WebPath = $RelativePath.Replace('\', '/')
        Invoke-WebRequest -UseBasicParsing -Uri "$RepositoryRoot/$WebPath" -OutFile $Target
    }
}

try {
    New-Item -ItemType Directory -Force -Path $StageDirectory, $InstallDirectory | Out-Null

    $PidFile = Join-Path $InstallDirectory "kugpt.pid"
    if (Test-Path -LiteralPath $PidFile) {
        $RunningPid = 0
        if ([int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$RunningPid)) {
            Stop-Process -Id $RunningPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    $Zip = Join-Path $StageDirectory "python-embed.zip"
    if ($RuntimeZipPath) {
        Copy-Item -LiteralPath $RuntimeZipPath -Destination $Zip
    }
    else {
        Write-Host "Downloading the signed local Python runtime..."
        Invoke-WebRequest -UseBasicParsing -Uri $PythonUrl -OutFile $Zip
    }
    if ((Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash -ne $PythonSha256) {
        throw "Python runtime checksum verification failed. Nothing was installed."
    }

    $StagedRuntime = Join-Path $StageDirectory "runtime"
    Expand-Archive -LiteralPath $Zip -DestinationPath $StagedRuntime -Force
    $Signature = Get-AuthenticodeSignature (Join-Path $StagedRuntime "python.exe")
    if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw "Python runtime signature verification failed. Nothing was installed."
    }

    if (Test-Path -LiteralPath $RuntimeDirectory) {
        Remove-Item -LiteralPath $RuntimeDirectory -Recurse -Force
    }
    Move-Item -LiteralPath $StagedRuntime -Destination $RuntimeDirectory

    # Embedded Python is isolated by default. Add only kuGPT's parent directory
    # to its module path; third-party site packages remain disabled.
    $PathConfig = Get-ChildItem -LiteralPath $RuntimeDirectory -Filter "python*._pth" | Select-Object -First 1
    if (-not $PathConfig) { throw "Embedded Python path configuration is missing." }
    $PathLines = Get-Content -LiteralPath $PathConfig.FullName
    if ($PathLines -notcontains "..") {
        $PathLines += ".."
        [IO.File]::WriteAllLines($PathConfig.FullName, $PathLines)
    }

    Copy-OrDownload "kugpt_launcher.py" $LauncherPath
    foreach ($File in @("__init__.py", "__main__.py", "cli.py", "engine.py", "spelling.py", "windows_hook.py")) {
        Copy-OrDownload "kugpt\$File" (Join-Path $InstallDirectory "kugpt\$File")
    }

    $DictionaryPath = Join-Path $InstallDirectory "data\frequency_dictionary_en_82_765.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path $DictionaryPath -Parent) | Out-Null
    if ($SourcePath) {
        Copy-Item -LiteralPath (Join-Path $SourcePath "data\frequency_dictionary_en_82_765.txt") -Destination $DictionaryPath -Force
    }
    else {
        Write-Host "Downloading the local English SymSpell dictionary..."
        Invoke-WebRequest -UseBasicParsing -Uri $DictionaryUrl -OutFile $DictionaryPath
    }
    if ((Get-FileHash -LiteralPath $DictionaryPath -Algorithm SHA256).Hash -ne $DictionarySha256) {
        throw "SymSpell dictionary checksum verification failed."
    }

    Remove-Item -LiteralPath (Join-Path $InstallDirectory "kugpt.exe") -Force -ErrorAction SilentlyContinue

    $BinDirectory = if ($Destination) { Join-Path $InstallDirectory "bin" } else { Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps" }
    if (-not (Test-Path -LiteralPath $BinDirectory)) {
        $BinDirectory = Join-Path $InstallDirectory "bin"
        New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
        if (-not $Destination) {
            $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
            if (($UserPath -split ';') -notcontains $BinDirectory) {
                [Environment]::SetEnvironmentVariable("Path", (($UserPath.TrimEnd(';') + ';' + $BinDirectory).TrimStart(';')), "User")
            }
        }
    }
    $Python = Join-Path $RuntimeDirectory "python.exe"
    $Shim = "@echo off`r`n`"$Python`" `"$LauncherPath`" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $BinDirectory "kugpt.cmd"), $Shim)

    & $Python $LauncherPath doctor
    if ($LASTEXITCODE -ne 0) { throw "kuGPT diagnostics failed." }
    if (-not $NoStartup) {
        & $Python $LauncherPath install
        if ($LASTEXITCODE -ne 0) { throw "kuGPT could not start." }
    }

    Write-Host ""
    Write-Host "kuGPT 0.3.1 is installed with local SymSpell correction." -ForegroundColor Green
    if (-not $NoStartup) { Write-Host "Open a new terminal and run: kugpt status" }
    Write-Host "Test it: kugpt fix i am nto tehe ncie pesron"
    Write-Host "Undo a live correction with Ctrl+Alt+Backspace."
}
finally {
    if (Test-Path -LiteralPath $StageDirectory) {
        Remove-Item -LiteralPath $StageDirectory -Recurse -Force
    }
}

