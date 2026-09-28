$ErrorActionPreference = "Stop"
$RepositoryRoot = "https://raw.githubusercontent.com/cyberythem/kuGPT/main"
$InstallDirectory = Join-Path $env:LOCALAPPDATA "kuGPT"
$SourceDirectory = Join-Path $env:TEMP ("kugpt-install-" + [Guid]::NewGuid().ToString("N"))
$Compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path -LiteralPath $Compiler)) {
    $Compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path -LiteralPath $Compiler)) {
    throw "kuGPT needs the built-in Windows .NET Framework compiler, but it was not found."
}

try {
    New-Item -ItemType Directory -Force -Path $SourceDirectory, $InstallDirectory | Out-Null
    $Files = @("Program.cs", "TextEngine.cs", "KeyboardDaemon.cs")
    foreach ($File in $Files) {
        Invoke-WebRequest -UseBasicParsing -Uri "$RepositoryRoot/src/$File" -OutFile (Join-Path $SourceDirectory $File)
    }

    $Sources = $Files | ForEach-Object { Join-Path $SourceDirectory $_ }
    & $Compiler /nologo /optimize+ /target:exe /platform:anycpu /reference:System.Drawing.dll /out:"$InstallDirectory\kugpt.exe" $Sources
    if ($LASTEXITCODE -ne 0) { throw "kuGPT compilation failed." }

    $BinDirectory = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    if (-not (Test-Path -LiteralPath $BinDirectory)) {
        $BinDirectory = Join-Path $InstallDirectory "bin"
        New-Item -ItemType Directory -Force -Path $BinDirectory | Out-Null
        $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if (($UserPath -split ';') -notcontains $BinDirectory) {
            [Environment]::SetEnvironmentVariable("Path", (($UserPath.TrimEnd(';') + ';' + $BinDirectory).TrimStart(';')), "User")
        }
    }

    $Shim = "@echo off`r`n`"$InstallDirectory\kugpt.exe`" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $BinDirectory "kugpt.cmd"), $Shim)
    & "$InstallDirectory\kugpt.exe" install

    Write-Host ""
    Write-Host "kuGPT is installed and running. Open a new terminal and run: kugpt status" -ForegroundColor Green
    Write-Host "Undo a correction with Ctrl+Alt+Backspace."
}
finally {
    if (Test-Path -LiteralPath $SourceDirectory) {
        Remove-Item -LiteralPath $SourceDirectory -Recurse -Force
    }
}

