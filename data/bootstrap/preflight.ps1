#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Inventory','Ready')]
    [string]$Mode = 'Inventory',
    [ValidateSet('BeforeInitialize','BeforeRegister','BeforeStart','AfterStart')]
    [string]$Phase = 'BeforeInitialize'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-DemoPath {
    param([string]$Value)
    if (-not $Value) { return '' }
    return $Value.Replace('/','\').TrimEnd('\').ToLowerInvariant()
}

function Test-DemoCommandLine {
    param([string]$CommandLine)
    # Fail closed on extra options, missing explicit defaults-file, or another service.
    $pattern = '^"?(?<exe>[^"]+?\.exe)"?\s+--defaults-file=(?:"(?<config>[^"]+)"|(?<config>\S+))\s+RiskControlMySQL84$'
    if ($CommandLine -notmatch $pattern) { return $false }
    return (ConvertTo-DemoPath $Matches.exe) -eq 'd:\riskcontroldemo\mysql84\server\bin\mysqld.exe' -and
        (ConvertTo-DemoPath $Matches.config) -eq 'd:\riskcontroldemo\mysql84\conf\my.ini'
}

function Test-DemoSnapshot {
    param([System.Collections.IDictionary]$Snapshot, [string]$Phase)
    $problems = [System.Collections.Generic.List[string]]::new()
    foreach ($errorCode in $Snapshot.ReadErrors) { $problems.Add($errorCode) }
    foreach ($flag in @('Server84','Client84','AdminClient84','ConfigValid','DirectoriesPresent','PathsNotReparse')) {
        if (-not $Snapshot[$flag]) { $problems.Add("Missing or invalid prerequisite: $flag") }
    }
    if ($Phase -eq 'BeforeInitialize') {
        if (-not $Snapshot.DataEmpty) { $problems.Add('Data directory must be empty before initialization') }
    } elseif (-not $Snapshot.DataInitialized) {
        $problems.Add('Expected initialized new data directory markers')
    }
    if ($Phase -in @('BeforeInitialize','BeforeRegister')) {
        if ($Snapshot.Service) { $problems.Add('Demo service must not exist at this phase') }
        if (@($Snapshot.Listeners).Count) { $problems.Add('3307 must be unoccupied at this phase') }
    } else {
        $service = $Snapshot.Service
        if (-not $service) {
            $problems.Add('Demo service missing')
        } else {
            if (-not (Test-DemoCommandLine $service.PathName)) { $problems.Add('Service executable/configuration command mismatch') }
            if ($service.StartMode -ne 'Manual') { $problems.Add('Demo service must use manual startup') }
            if ($service.StartName -ne 'NT SERVICE\RiskControlMySQL84') { $problems.Add('Demo service must use its dedicated virtual account') }
            if ($Phase -eq 'BeforeStart') {
                if ($service.State -ne 'Stopped' -or $service.ProcessId -ne 0) { $problems.Add('Registered service must be stopped before start') }
                if (@($Snapshot.Listeners).Count) { $problems.Add('3307 must be unoccupied before start') }
            } else {
                if ($service.State -ne 'Running' -or $service.ProcessId -le 0) { $problems.Add('Demo service not running with a valid PID') }
                if (-not $Snapshot.Process) {
                    $problems.Add('Demo process identity unreadable')
                } else {
                    if ($Snapshot.Process.ProcessId -ne $service.ProcessId) { $problems.Add('Service/process PID mismatch') }
                    if ((ConvertTo-DemoPath $Snapshot.Process.ExecutablePath) -ne 'd:\riskcontroldemo\mysql84\server\bin\mysqld.exe') { $problems.Add('Process executable mismatch') }
                    if (-not (Test-DemoCommandLine $Snapshot.Process.CommandLine)) { $problems.Add('Process configuration command mismatch') }
                }
                if (@($Snapshot.Listeners).Count -eq 0) { $problems.Add('3307 listener missing') }
                foreach ($listener in $Snapshot.Listeners) {
                    if ($listener.OwningProcess -ne $service.ProcessId) {
                        $workers = @($Snapshot.Workers | Where-Object ProcessId -EQ $listener.OwningProcess)
                        if ($workers.Count -ne 1) {
                            $problems.Add('3307 listener worker identity unreadable')
                        } else {
                            $worker = $workers[0]
                            if ($worker.ParentProcessId -ne $service.ProcessId -or
                                (ConvertTo-DemoPath $worker.ExecutablePath) -ne 'd:\riskcontroldemo\mysql84\server\bin\mysqld.exe' -or
                                -not (Test-DemoCommandLine $worker.CommandLine)) {
                                $problems.Add('3307 worker parent/executable/configuration mismatch')
                            }
                        }
                    }
                    if ($listener.LocalAddress -ne '127.0.0.1') { $problems.Add('3307 must bind only to 127.0.0.1') }
                }
            }
        }
    }
    return $problems.ToArray()
}

function Get-DemoSnapshot {
    $root = 'D:\RiskControlDemo\mysql84'
    $state = @{
        Server84=$false; Client84=$false; AdminClient84=$false; ConfigValid=$false
        DirectoriesPresent=$false; PathsNotReparse=$false
        DataEmpty=$false; DataInitialized=$false
        Service=$null; Process=$null; Workers=@(); Listeners=@(); ReadErrors=@()
    }
    try {
        foreach ($pair in @(@('Server84','mysqld.exe'),@('Client84','mysql.exe'),@('AdminClient84','mysqladmin.exe'))) {
            $exe = Join-Path $root ('server\bin\' + $pair[1])
            if (Test-Path -LiteralPath $exe -PathType Leaf) {
                # Only --version, never initialize/start/connect.
                $version = & $exe --no-defaults --version
                $state[$pair[0]] = $LASTEXITCODE -eq 0 -and "$version" -match 'Ver 8\.4\.'
            }
        }
        $dirs = @('server','conf','data','logs')
        $state.DirectoriesPresent = @($dirs | Where-Object {
            -not (Test-Path -LiteralPath (Join-Path $root $_) -PathType Container)
        }).Count -eq 0
        $safe = $true
        foreach ($target in @($root,(Join-Path $root 'server\bin\mysqld.exe'),(Join-Path $root 'server\bin\mysql.exe'),(Join-Path $root 'server\bin\mysqladmin.exe'),(Join-Path $root 'conf\my.ini'),(Join-Path $root 'data'),(Join-Path $root 'logs'))) {
            $walk = $target
            while ($walk) {
                if (Test-Path -LiteralPath $walk) {
                    if ((Get-Item -LiteralPath $walk -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $safe = $false }
                }
                $walk = Split-Path -Path $walk -Parent
            }
        }
        $state.PathsNotReparse = $safe
        $data = Join-Path $root 'data'
        if (Test-Path -LiteralPath $data -PathType Container) {
            $state.DataEmpty = @(Get-ChildItem -LiteralPath $data -Force).Count -eq 0
            $state.DataInitialized = (Test-Path -LiteralPath (Join-Path $data 'mysql') -PathType Container) -and
                (Test-Path -LiteralPath (Join-Path $data 'auto.cnf') -PathType Leaf) -and
                (Test-Path -LiteralPath (Join-Path $data 'mysql.ibd') -PathType Leaf)
        }
        $expected = @{
            'mysqld.basedir'='d:/riskcontroldemo/mysql84/server'
            'mysqld.datadir'='d:/riskcontroldemo/mysql84/data'
            'mysqld.port'='3307'; 'mysqld.bind-address'='127.0.0.1'
            'mysqld.mysqlx'='0'; 'mysqld.character-set-server'='utf8mb4'
            'mysqld.collation-server'='utf8mb4_0900_ai_ci'
            'mysqld.default-time-zone'='+08:00'
            'mysqld.log-error'='d:/riskcontroldemo/mysql84/logs/mysql84.err'
            'mysqld.general-log'='off'; 'mysqld.slow-query-log'='off'
            'mysqld.local-infile'='off'
            'client.host'='127.0.0.1'; 'client.port'='3307'
            'client.protocol'='tcp'; 'client.default-character-set'='utf8mb4'
        }
        $config = Join-Path $root 'conf\my.ini'
        if (Test-Path -LiteralPath $config -PathType Leaf) {
            $actual = @{}; $section=''; $valid=$true
            foreach ($line in Get-Content -LiteralPath $config -Encoding UTF8) {
                if ($line -match '^\s*(#.*|;.*)?$') { continue }
                if ($line -match '^\[([a-z]+)\]$') { $section=$Matches[1]; continue }
                if ($line -notmatch '^([a-z-]+)=(.+)$') { $valid=$false; continue }
                $key = $section + '.' + $Matches[1]
                if ($actual.ContainsKey($key)) { $valid=$false }
                $actual[$key] = $Matches[2].Replace('\','/').ToLowerInvariant()
            }
            if ($actual.Count -ne $expected.Count) { $valid=$false }
            foreach ($key in $expected.Keys) {
                if (-not $actual.ContainsKey($key) -or $actual[$key] -ne $expected[$key]) { $valid=$false }
            }
            $state.ConfigValid=$valid
        }
    } catch { $state.ReadErrors += 'Cannot safely inspect programs/configuration/directories' }
    try {
        $state.Listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -EQ 3307)
    } catch { $state.ReadErrors += 'Cannot inspect listener PID/address' }
    try {
        $services = @(Get-Service -ErrorAction Stop)
        $old = @($services | Where-Object Name -EQ MySQL80)
        if ($old.Count) { Write-Host "MySQL80 status: $($old[0].Status) (read only)" }
        if (@($services | Where-Object Name -EQ RiskControlMySQL84).Count) {
            $rows = @(Get-CimInstance Win32_Service -Filter "Name='RiskControlMySQL84'" -ErrorAction Stop)
            if ($rows.Count -ne 1) { throw 'Unknown service identity' }
            $state.Service=$rows[0]
            if ($state.Service.ProcessId -gt 0) {
                $processes = @(Get-CimInstance Win32_Process -Filter "ProcessId=$($state.Service.ProcessId)" -ErrorAction Stop)
                if ($processes.Count -ne 1) { throw 'Unknown process identity' }
                $state.Process=$processes[0]
                foreach ($listener in $state.Listeners) {
                    if ($listener.OwningProcess -ne $state.Service.ProcessId) {
                        $state.Workers += @(Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction Stop)
                    }
                }
            }
        }
    } catch { $state.ReadErrors += 'Cannot inspect service/process identity' }
    return $state
}

try {
    $repositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
    $branch = git --no-optional-locks -C $repositoryRoot branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'feat/data-bootstrap') { throw 'Expected feat/data-bootstrap' }
    $snapshot = Get-DemoSnapshot
    $issues = @(Test-DemoSnapshot -Snapshot $snapshot -Phase $Phase)
    foreach ($issue in $issues) { Write-Output "PREREQUISITE: $issue" }
    if ($Mode -eq 'Inventory') {
        Write-Output "INVENTORY ONLY: phase=$Phase issues=$($issues.Count). Exit 0 means inspection completed, NOT deployment readiness."
        exit 0
    }
    if ($issues.Count) { throw "READY FAIL: phase=$Phase issues=$($issues.Count)" }
    Write-Output "READY PASS: phase=$Phase. OS identity only; authenticated server checks remain mandatory."
    exit 0
} catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
