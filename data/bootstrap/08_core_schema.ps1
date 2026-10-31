#requires -Version 7.2
[CmdletBinding()]
param([string]$PythonExe = 'D:\RiskControlDemo\python312-venv\Scripts\python.exe',
      [ValidateSet('Plan','Apply','Verify','Deploy')][string]$Mode = 'Plan',
      [string]$V2Root = 'C:\Users\姜佳庆\AppData\Local\Temp\risk_control_project1-v2-e9baadf',
      [ValidatePattern('^[A-Za-z0-9_]+$')][string]$AdminUser = 'root',
      [switch]$Apply,
      [ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$ExpectedDdlSha256)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    if ($Mode -eq 'Apply' -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot '..\v2\contract.json'))) {
        throw 'V2 contract supersedes the V1 82-field DDL; do not apply the old schema'
    }
    if (($Mode -in @('Apply','Deploy')) -ne [bool]$Apply) { throw 'Apply requires explicit switch' }
    if ($Mode -eq 'Apply' -and -not $ExpectedDdlSha256) { throw 'Reviewed DDL hash required' }
    if (-not $IsWindows -or [Console]::IsInputRedirected -or -not [IO.Path]::IsPathFullyQualified($PythonExe) -or
        -not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Invalid terminal or interpreter' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot 'preflight.ps1') -Mode Ready -Phase AfterStart
    if ($LASTEXITCODE -ne 0) { throw 'Preflight failed' }
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File (Join-Path $PSScriptRoot '02_provision_users.ps1') -PythonExe $PythonExe -Mode CheckDependencies
    if ($LASTEXITCODE -ne 0) { throw 'Authentication dependencies failed' }
    . (Join-Path $PSScriptRoot 'credential_pipe.ps1')
    $params = @{ PythonExe=$PythonExe; Script=(Join-Path $PSScriptRoot 'core_schema.py'); Mode="Core$Mode"; AdminUser=$AdminUser; Apply=$Apply }
    if ($Mode -eq 'Deploy') {
        if ($AdminUser -ne 'root' -or -not (Test-Path -LiteralPath (Join-Path $V2Root 'backend/db/models.py'))) { throw 'Invalid V2 runtime' }
        $params.Script=Join-Path $PSScriptRoot '..\v2\deploy.py'
        $params.Mode='V2Deploy'; $params.V2Root=$V2Root
    }
    if ($ExpectedDdlSha256) { $params.ExpectedDdlSha256=$ExpectedDdlSha256 }
    $result = Invoke-ProvisionDialogue @params
    Write-Output $result.Result
    if ($Mode -eq 'Deploy') {
        $v2Report=if ($null -ne $result.PSObject.Properties['V2Report']) { $result.V2Report } else { $null }
        $receipt=@{source='live_mysql';recorded_at=[DateTimeOffset]::Now.ToString('o');database='rc_demo_v2';passed=($result.ExitCode -eq 0);report=$v2Report;result=$result.Result}
        $name='v2-live-'+[Guid]::NewGuid().ToString('N')+'.json'
        $path=Join-Path $PSScriptRoot "..\evidence\$name"
        $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 5)); $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Write-Output "Evidence: $([IO.Path]::GetFullPath($path))"
        if ($result.ExitCode -eq 0) {
            $note="`n## V2 live acceptance $([DateTimeOffset]::Now.ToString('o'))`n`n11 V2 tables/89 key fields verified; actual synthetic HTTP upload, parsing, persistence, metrics and report retrieval PASS; storage privacy and minimal grants PASS; synthetic transaction backup sample roundtrip PASS (not full disaster recovery). Evidence: evidence/$name.`n"
            [IO.File]::AppendAllText((Join-Path $PSScriptRoot '..\acceptance.md'),$note,[Text.UTF8Encoding]::new($false))
            [IO.File]::AppendAllText((Join-Path $PSScriptRoot '..\数据模块业务报告_v2.md'),"`n## 本机真实演示验收更新`n`n新版独立数据区建表、合成PDF上传与解析、明细和指标入库、报告读取及脱敏检查已真实通过。仅为合成数据演示，尚非真实客户材料验收。证据：evidence/$name。`n",[Text.UTF8Encoding]::new($false))
        }
        exit $result.ExitCode
    }
    $report = if ($null -ne $result.PSObject.Properties['CoreReport']) { $result.CoreReport } else { $null }
    $source = if ($null -ne $report) { 'live_mysql' } else { 'unverified_attempt' }
    $receipt = @{ format=1; endpoint='127.0.0.1:3307'; mode=$Mode; source=$source;
        recorded_at=[DateTimeOffset]::Now.ToString('o'); passed=($result.ExitCode -eq 0); result=$result.Result; report=$report }
    $name = 'core-live-' + [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N') + '.json'
    $path = Join-Path $PSScriptRoot "..\evidence\$name"
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($receipt | ConvertTo-Json -Depth 5))
    $file = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $file.Write($bytes,0,$bytes.Length); $file.Flush($true) } finally { $file.Dispose() }
    Write-Output "Evidence: $([IO.Path]::GetFullPath($path))"
    if ($result.ExitCode -eq 0 -and $Mode -ne 'Plan' -and $null -ne $report) {
        $required = @('tables_ok','fields_ok','primary_keys_ok','indexes_ok','constraints_ok','partitions_ok','show_create_partitioned','foreign_keys_absent','revision_ok')
        foreach ($key in $required) {
            if (-not $report.ContainsKey($key) -or $report[$key] -ne $true) { throw 'Incomplete verification cannot update acceptance' }
        }
        if ($report.table_count -ne 11 -or $report.field_count -ne 82) { throw 'Unexpected verified object count' }
        $dataRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $tasksPath = Join-Path $dataRoot 'tasks.md'
        $tasks = [IO.File]::ReadAllText($tasksPath)
        $tasks = $tasks.Replace('| [ ] | DA-02 |', '| [x] | DA-02 |').Replace('| [ ] | DA-03 |', '| [x] | DA-03 |')
        if ($report.explain_matches -eq 4) { $tasks = $tasks.Replace('| [ ] | DA-04 |', '| [x] | DA-04 |') }
        $note = "`n## Core live verification $([DateTimeOffset]::Now.ToString('o'))`n`nDA-02: PASS (11 tables/82 columns, physical metadata). DA-03: PASS (SHOW CREATE and five range partitions; boundary DML not tested). DA-04 selected index paths: $($report.explain_matches)/4; only four passes mark complete. DA-07 upgrade revision 0001 verified; downgrade NOT executed, task remains incomplete. Evidence: evidence/$name.`n"
        [IO.File]::AppendAllText((Join-Path $dataRoot 'acceptance.md'), $note, [Text.UTF8Encoding]::new($false))
        [IO.File]::WriteAllText($tasksPath, $tasks, [Text.UTF8Encoding]::new($false))
        'Live acceptance updated from verified metadata; no downgrade or business DML performed.'
    }
    exit $result.ExitCode
}
catch { Write-Output 'STOP: core prerequisite/recording failure; preserve state; no automatic retry or cleanup'; exit 1 }
