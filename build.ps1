param(
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $Compiler)) {
    $Compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
}
if (-not (Test-Path -LiteralPath $Compiler)) {
    throw "The built-in Windows C# compiler was not found."
}

$Dist = Join-Path $ProjectRoot "dist"
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
$Sources = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "src") -Filter "*.cs" | ForEach-Object FullName

& $Compiler /nologo /optimize+ /target:exe /platform:anycpu /reference:System.Drawing.dll /out:"$Dist\kugpt.exe" $Sources
if ($LASTEXITCODE -ne 0) { throw "kuGPT compilation failed." }
Write-Host "Built $Dist\kugpt.exe"

if ($Test) {
    & $Compiler /nologo /optimize+ /target:exe /main:KuGPT.Tests.EngineTests /reference:System.Drawing.dll /out:"$Dist\engine-tests.exe" (Join-Path $ProjectRoot "src\TextEngine.cs") (Join-Path $ProjectRoot "tests\EngineTests.cs")
    if ($LASTEXITCODE -ne 0) { throw "Test compilation failed." }
    & "$Dist\engine-tests.exe"
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
}

