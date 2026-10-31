#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Verify','Serve')][string]$Mode='Verify',
    [string]$PythonExe='D:\RiskControlDemo\python312-venv\Scripts\python.exe',
    [string]$V2Root='C:\Users\姜佳庆\AppData\Local\Temp\risk_control_project1-v2-e9baadf'
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$proc=$null
$secret=$null
try {
    if (-not $IsWindows -or [Console]::IsInputRedirected) { throw 'Interactive Windows terminal required' }
    if (-not [IO.Path]::IsPathFullyQualified($PythonExe) -or -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Invalid interpreter' }
    if (-not (Test-Path -LiteralPath (Join-Path $V2Root 'backend/db/models.py'))) { throw 'V2 source missing' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase AfterStart
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
    . (Join-Path $PSScriptRoot 'credential_pipe.ps1')
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$PythonExe
    $info.UseShellExecute=$false
    $info.RedirectStandardInput=$true
    $info.RedirectStandardError=$true
    foreach ($argument in @('-B',(Join-Path $PSScriptRoot '../v2/web_demo.py'),'--mode',$Mode,'--v2-root',$V2Root)) { $info.ArgumentList.Add($argument) }
    $secret=Read-Host 'rc_demo_app password (login)' -AsSecureString
    $proc=[Diagnostics.Process]::new()
    $proc.StartInfo=$info
    if (-not $proc.Start()) { throw 'Child unavailable' }
    $discardedErrors=$proc.StandardError.ReadToEndAsync()
    Send-SecureCredentialFrame -Stream $proc.StandardInput.BaseStream -Secret $secret
    $secret.Dispose(); $secret=$null
    $proc.StandardInput.Close()
    $proc.WaitForExit()
    $null=$discardedErrors.GetAwaiter().GetResult()
    exit $proc.ExitCode
}
catch { Write-Output 'STOP: web Demo prerequisite/input failure'; exit 1 }
finally {
    if ($null -ne $secret) { $secret.Dispose() }
    if ($null -ne $proc) {
        if (-not $proc.HasExited) { $proc.Kill() }
        $proc.Dispose()
    }
}
