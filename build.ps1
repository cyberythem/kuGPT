param([switch]$Test)

$ErrorActionPreference = "Stop"
$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $Python) { throw "Python is required for development tests. End users get a bundled signed runtime." }

$Dictionary = Join-Path $PSScriptRoot "data\frequency_dictionary_en_82_765.txt"
$DictionarySha256 = "C604E1121E398AE7C7FBF777F11E0A0F2FA66EDA932CB9FBA1321466CF3ACD7B"
if (-not (Test-Path -LiteralPath $Dictionary)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Dictionary -Parent) | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/wolfgarbe/SymSpell/v6.7.3/SymSpell/frequency_dictionary_en_82_765.txt" -OutFile $Dictionary
}
if ((Get-FileHash -LiteralPath $Dictionary -Algorithm SHA256).Hash -ne $DictionarySha256) {
    throw "SymSpell dictionary checksum verification failed."
}

if ($Test) {
    & $Python.Source -m unittest discover -s tests -v
    exit $LASTEXITCODE
}

Write-Host "kuGPT is pure Python; run .\build.ps1 -Test to verify it."

