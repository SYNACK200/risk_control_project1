#requires -Version 7.2
[CmdletBinding()]
param([string]$PythonExe = 'D:\RiskControlDemo\python312-venv\Scripts\python.exe')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    if (-not $IsWindows -or -not [IO.Path]::IsPathFullyQualified($PythonExe) -or
        -not (Test-Path -LiteralPath $PythonExe -PathType Leaf) -or [Console]::IsInputRedirected) {
        throw 'Interactive Windows terminal and interpreter required'
    }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase AfterStart
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot '02_provision_users.ps1') -PythonExe $PythonExe -Mode CheckDependencies
    if ($LASTEXITCODE -ne 0) { throw 'Dependencies failed' }
    . (Join-Path $PSScriptRoot 'credential_pipe.ps1')
    $result = Invoke-ProvisionDialogue -PythonExe $PythonExe -Script (Join-Path $PSScriptRoot 'provision_core.py') -Mode AcceptDA01
    Write-Output $result.Result
    $dataRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $stamp = [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss')
    $name = 'da01-live-' + $stamp + '-' + [Guid]::NewGuid().ToString('N') + '.json'
    $path = Join-Path $dataRoot "evidence\$name"
    $checks = if ($null -ne $result.PSObject.Properties['Checks']) { $result.Checks } else { @() }
    $accounts = if ($null -ne $result.PSObject.Properties['Accounts']) { $result.Accounts } else { @() }
    if ($result.ExitCode -eq 0 -and ($checks.Count -ne 5 -or @($checks | Where-Object { -not $_.ok }).Count -ne 0)) {
        throw 'Incomplete acceptance cannot mark task complete'
    }
    $receipt = @{format=1; source='live_mysql'; endpoint='127.0.0.1:3307';
        recorded_at=[DateTimeOffset]::Now.ToString('o'); passed=($result.ExitCode -eq 0);
        checks=$checks; runtime_accounts=$accounts; result=$result.Result; database_writes=$false}
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 6))
    $file = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $file.Write($bytes, 0, $bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
    Write-Output "Evidence: $path"
    if ($result.ExitCode -eq 0) {
        $note = "`n## DA-01 live acceptance $stamp`n`nPASS: three empty schemas, six local identities, exact empty roles/default bindings, authentication plugins and three runtime logins. Evidence: evidence/$name. Read-only; DA-02 table/view privileges are not covered.`n"
        [IO.File]::AppendAllText((Join-Path $dataRoot 'acceptance.md'), $note, [Text.UTF8Encoding]::new($false))
        $tasksPath = Join-Path $dataRoot 'tasks.md'
        $tasks = [IO.File]::ReadAllText($tasksPath)
        $tasks = $tasks.Replace('| [ ] | DA-01 |', '| [x] | DA-01 |')
        [IO.File]::WriteAllText($tasksPath, $tasks, [Text.UTF8Encoding]::new($false))
        'DA-01 live acceptance recorded; no DA-02 database writes performed.'
    }
    exit $result.ExitCode
}
catch { Write-Output 'STOP: acceptance or evidence recording failed; preserve state; no database writes performed'; exit 1 }
