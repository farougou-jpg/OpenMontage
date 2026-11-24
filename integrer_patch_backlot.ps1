[CmdletBinding()]
param(
    [string]$ProjectRoot = "C:\OpenMontage",
    [string]$PatchRoot = "$env:USERPROFILE\Downloads\openmontage_patch_out"
)

$ErrorActionPreference = "Stop"

$targetState = Join-Path $ProjectRoot "backlot\state.py"
$sourceState = Join-Path $PatchRoot "backlot\state.py"
$sourceTest = Join-Path $PatchRoot "tests\backlot\test_legacy_studio_project_state.py"
$testDir = Join-Path $ProjectRoot "tests\backlot"
$targetTest = Join-Path $testDir "test_legacy_studio_project_state.py"

if (-not (Test-Path $ProjectRoot -PathType Container)) {
    throw "Dossier projet introuvable : $ProjectRoot"
}
if (-not (Test-Path $sourceState -PathType Leaf)) {
    throw "Patch introuvable : $sourceState. Décompressez l'archive et vérifiez PatchRoot."
}
if (-not (Test-Path $sourceTest -PathType Leaf)) {
    throw "Test de régression introuvable : $sourceTest"
}
if (-not (Test-Path $targetState -PathType Leaf)) {
    throw "Fichier cible introuvable : $targetState. Arrêt sans modification."
}
if (Test-Path $targetTest) {
    throw "Le test cible existe déjà : $targetTest. Vérifiez son contenu avant de continuer."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $ProjectRoot "_integration_backups\backlot-legacy-compat-$stamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item $targetState (Join-Path $backupDir "state.py.before") -Force

$testWasCopied = $false
$stateWasReplaced = $false

try {
    Copy-Item $sourceState $targetState -Force
    $stateWasReplaced = $true

    New-Item -ItemType Directory -Path $testDir -Force | Out-Null
    Copy-Item $sourceTest $targetTest
    $testWasCopied = $true

    Push-Location $ProjectRoot
    try {
        Write-Host "`n=== Vérification syntaxique ===" -ForegroundColor Cyan
        python -m py_compile $targetState
        if ($LASTEXITCODE -ne 0) { throw "Échec de py_compile." }

        Write-Host "`n=== Tests de régression et d'intégration ===" -ForegroundColor Cyan
        pytest tests/backlot/test_legacy_studio_project_state.py tests/backlot/test_state.py tests/backlot/test_server.py tests/backlot/test_gate_scenarios.py tests/backlot/test_parallel_generation.py tests/studio/test_pilot_preserved.py tests/studio/test_studio_pipeline.py tests/studio/test_budget_guard.py tests/studio/test_studio_capabilities.py tests/test_project_metadata.py tests/test_studio_reader.py tests/test_studio_patch_regressions.py -q
        if ($LASTEXITCODE -ne 0) { throw "Les tests ont échoué (code $LASTEXITCODE)." }

        Write-Host "`nPatch intégré. Sauvegarde : $backupDir" -ForegroundColor Green
        Write-Host "Aucun fichier de projects\pilote-gestion-temps n'a été copié ou modifié."
    }
    finally {
        Pop-Location
    }
}
catch {
    Write-Warning "Échec de l'intégration ou des tests : $($_.Exception.Message)"
    if ($stateWasReplaced) {
        Copy-Item (Join-Path $backupDir "state.py.before") $targetState -Force
        Write-Host "backlot\state.py restauré depuis la sauvegarde." -ForegroundColor Yellow
    }
    if ($testWasCopied -and (Test-Path $targetTest)) {
        Remove-Item $targetTest -Force
        Write-Host "Test ajouté par ce script retiré." -ForegroundColor Yellow
    }
    throw
}
