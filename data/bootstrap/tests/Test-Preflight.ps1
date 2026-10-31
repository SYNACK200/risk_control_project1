#requires -Version 7.2
# Read-only tests: extract pure functions, do not invoke OS collector/main or MySQL.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
$source=Join-Path $PSScriptRoot '..\preflight.ps1'
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $source).Path,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Preflight parse error' }
foreach ($name in @('ConvertTo-DemoPath','Test-DemoCommandLine','Test-DemoSnapshot')) {
    $definition=$ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    },$true) | Where-Object Name -EQ $name
    if (@($definition).Count -ne 1) { throw "Missing pure function: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
function New-TestSnapshot {
    return @{
        Server84=$true; Client84=$true; AdminClient84=$true; ConfigValid=$true
        DirectoriesPresent=$true; PathsNotReparse=$true
        DataEmpty=$true; DataInitialized=$false
        Service=$null; Process=$null; Workers=@(); Listeners=@(); ReadErrors=@()
    }
}
function Add-TestRunningIdentity {
    param($Snapshot)
    $command='"D:\RiskControlDemo\mysql84\server\bin\mysqld.exe" --defaults-file="D:\RiskControlDemo\mysql84\conf\my.ini" RiskControlMySQL84'
    $Snapshot.DataEmpty=$false; $Snapshot.DataInitialized=$true
    $Snapshot.Service=[pscustomobject]@{
        State='Running'; ProcessId=7001; StartMode='Manual'
        StartName='NT SERVICE\RiskControlMySQL84'; PathName=$command
    }
    $Snapshot.Process=[pscustomobject]@{
        ProcessId=7001; ExecutablePath='D:\RiskControlDemo\mysql84\server\bin\mysqld.exe'
        CommandLine=$command
    }
    $Snapshot.Listeners=@([pscustomobject]@{OwningProcess=7001;LocalAddress='127.0.0.1'})
}
$passed=0
function Assert-TestResult {
    param($Snapshot,[string]$Phase,[bool]$ExpectedPass,[string]$Name)
    $issues=@(Test-DemoSnapshot -Snapshot $Snapshot -Phase $Phase)
    if (($issues.Count -eq 0) -ne $ExpectedPass) { throw "FAIL: $Name" }
    Write-Output "PASS: $Name"
    $script:passed++
}
$s=New-TestSnapshot
Assert-TestResult $s BeforeInitialize $true 'fresh deployment prerequisites'
$s.Server84=$false
Assert-TestResult $s BeforeInitialize $false 'missing 8.4 blocks readiness'
$s=New-TestSnapshot; $s.DataEmpty=$false
Assert-TestResult $s BeforeInitialize $false 'nonempty data blocks initialization'
$s=New-TestSnapshot; $s.DataInitialized=$true; $s.DataEmpty=$false
Assert-TestResult $s BeforeRegister $true 'initialized directory before registration'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Service.State='Stopped'; $s.Service.ProcessId=0; $s.Process=$null; $s.Listeners=@()
Assert-TestResult $s BeforeStart $true 'registered stopped identity'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
Assert-TestResult $s AfterStart $true 'matching service process and listener'
$s.Listeners[0].OwningProcess=8002
Assert-TestResult $s AfterStart $false 'unrelated listener PID rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Process.ExecutablePath='C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe'
Assert-TestResult $s AfterStart $false 'old executable rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Service.PathName=$s.Service.PathName.Replace('conf\my.ini','conf\other.ini')
Assert-TestResult $s AfterStart $false 'wrong service config rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Process.CommandLine=$s.Process.CommandLine + ' --port=3306'
Assert-TestResult $s AfterStart $false 'unexpected process options rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Listeners[0].LocalAddress='0.0.0.0'
Assert-TestResult $s AfterStart $false 'non-loopback binding rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.ReadErrors=@('CIM access denied')
Assert-TestResult $s AfterStart $false 'unreadable identity fails closed'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.PathsNotReparse=$false
Assert-TestResult $s AfterStart $false 'reparse path rejected'
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Service.StartName='LocalSystem'
Assert-TestResult $s AfterStart $false 'unexpected service account rejected'
"Pure preflight tests: $passed PASS, no OS/database mutation"
$s=New-TestSnapshot; Add-TestRunningIdentity $s
$s.Workers=@([pscustomobject]@{ProcessId=7002;ParentProcessId=7001;ExecutablePath=$s.Process.ExecutablePath;CommandLine=$s.Process.CommandLine})
$s.Listeners[0].OwningProcess=7002
Assert-TestResult $s AfterStart $true 'verified direct worker child accepted'
$s.Workers[0].ParentProcessId=9999
Assert-TestResult $s AfterStart $false 'unrelated worker parent rejected'
$s.Workers[0].ParentProcessId=7001
$s.Workers[0].CommandLine += ' --port=3306'
Assert-TestResult $s AfterStart $false 'worker configuration override rejected'
"Final pure preflight tests: $passed PASS, no OS/database mutation"
