#requires -Version 7.2
[CmdletBinding()]
param([Parameter(Mandatory)][string]$PythonExe)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$secret = $null
try {
    if (-not $IsWindows -or -not [IO.Path]::IsPathFullyQualified($PythonExe) -or
        -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Invalid interpreter' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase AfterStart
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot '02_provision_users.ps1') -PythonExe $PythonExe -Mode CheckDependencies
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
    if ([Console]::IsInputRedirected) { throw 'Real interactive terminal required' }
    . (Join-Path $PSScriptRoot 'credential_pipe.ps1')
    $secret = Read-Host 'Demo administrator password' -AsSecureString
    $result = Invoke-CredentialChild -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'authenticate_pipe.py') -Mode authenticate -Secret $secret
    Write-Output $result.Result
    exit $result.ExitCode
}
catch { Write-Output 'AUTHENTICATION FAIL: INPUT_OR_PREREQUISITE_FAILURE'; exit 1 }
finally { if ($null -ne $secret) { $secret.Dispose() } }
