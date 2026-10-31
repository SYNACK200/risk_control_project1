# DA-01 独立 MySQL 8.4 Demo

DA-01已真实通过，证据da01-live-20261030-205612-2a743751dc004d60b7a8b6bbaf7cff1f.json。本批无需再运行07。DA-02/03/04/07下一入口为08_core_schema.ps1，默认Plan只读，Apply到0001必须明确批准、-Apply、审核DDL的SHA-256及本机确认短语；Verify复用安全输入，不执行0002或down。影响范围和依赖安装审批见../core/model_review.md。

当前统一验收入口为`07_accept_da01.ps1`：管理员一次、三个运行账号各一次安全输入，自动完成只读元数据/精确空角色权限/默认绑定/登录核验。1045不自动重试或改账号，继续汇总其余账号。新建脱敏JSON回执；全部通过才更新acceptance.md及DA-01状态。本阶段不再次Initialize、不建表、不自动安装依赖。后续写入审批与恢复边界见../next_batch.md。

固定目标：D:\RiskControlDemo\mysql84、127.0.0.1:3307、RiskControlMySQL84。禁止操作MySQL80或3306。维护人员已确认新实例运行且06安全输入入口真实认证通过；本轮未执行三库三角色初始化。下方安装命令仅供历史参考，不要重复初始化或注册服务。交付状态见 ../acceptance.md，运维与集成见 ../operations.md。

## 文件及入口

| 文件 | 用途 | 操作性质 |
| --- | --- | --- |
| my.ini.example | 仓库外conf/my.ini的运行配置模板 | 不执行 |
| preflight.ps1 | 版本、配置、路径、服务、进程链及监听核验 | 只读 |
| 01_databases_roles.sql | 三个utf8mb4库及三个空角色 | 写入，仅由02调用 |
| 02_provision_users.ps1 | 安全交互入口：依赖/盘点/管理与运行验收/初始化 | 仅Initialize -Apply写入 |
| credential_pipe.ps1 | Read-Host安全输入、匿名stdin帧、白名单结果与进程清理 | 仅内存与子进程 |
| provision_core.py | 身份、已有权限、三库三角色及密码校验 | 仅Initialize且完成确认后写入 |
| 06_authenticate_secure.ps1、authenticate_pipe.py | 已经真实验证的独立认证入口 | 只读 |
| 03_verify_admin.sql | 空库初始化阶段管理验收 | 只读；建表后空库断言不再适用 |
| 04_verify_runtime.sql | 运行账号身份核对 | 只读 |
| down.sql | 撤销前盘点，不删除账号/数据 | 只读 |
| connection.example.env | 无密码连接示例，不自动加载 | 不执行 |
| tests/ | 预检及认证依赖准入测试 | 不连接、不修改系统 |

账号初始化入口必须为02脚本，不直接重定向01 SQL。它先通过OS门禁、Python3.11/3.12及认证依赖准入、服务端版本/端口/datadir检查，再提示确认短语和缺少账号的新密码；不重设既有密码，不接受额外既有权限。建表后拒绝重跑空库初始化，不能为了重跑删库。

## 四阶段门禁

```powershell
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Inventory -Phase BeforeInitialize
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Ready -Phase BeforeInitialize
```

需要PowerShell7.2+。Inventory退出0仅表示盘点结束，允许缺程序，不代表部署就绪。Ready关键条件不满足退出1。维护用户运行；沙箱无访问权时不得放宽ACL。

| Phase | data预期 | 服务/3307预期 |
| --- | --- | --- |
| BeforeInitialize | 完全为空 | 服务不存在、端口空闲 |
| BeforeRegister | mysql、auto.cnf、mysql.ibd存在 | 服务不存在、端口空闲 |
| BeforeStart | 已初始化 | 专用虚拟账号、Manual、Stopped/PID0、端口空闲 |
| AfterStart | 已初始化 | Running，服务进程/直接工作子进程身份匹配，3307仅回环 |

服务身份为NT SERVICE\RiskControlMySQL84，不提前向共享LocalService授权。未注册时不能假设服务SID可解析。监听PID可为服务PID或其直接工作子进程；两者均须匹配新程序和唯一配置。读取失败、未知父子关系、额外启动参数均拒绝。严格命令行白名单仍需真实启动验收，不能为通过而放宽。

## 当前部署前状态

8.4.13 ZIP已解压到server；mysqld/mysql/mysqladmin版本已核对。server/conf/data/logs独立。运行配置为3307、127.0.0.1、mysqlx关闭、utf8mb4、+08:00、通用/慢查询日志关闭、local-infile关闭。

真实ACL在核对347项所有者、继承、无重解析点及父目录范围后逐项验证并收紧。维护用户、SYSTEM、Administrators保留管理权限，未授予服务身份。受保护备份在C:\ProgramData\RiskControlDemoAclBackup，根目录不新增备份文件夹。原备份UTF-16LE，无BOM，不能删除NUL替代解码。

原生icacls恢复未通过实际权限验证；已验证的替代回退仅适用于“全部继承、无显式ACE、继承源不变”的原基线：人工核对精确对象清单后父先子后逐对象启用继承/reset，不执行无界递归，不自动回退。原始现场SDDL与父继承源另有备份。新增conf/my-init.ini后对象为348，恢复时须显式纳入该已知新增对象；未知增减即停止。

my-init.ini仅保留basedir、datadir、log-error，日志为logs/initialize.err；原my.ini未修改。备份目录与初始化日志不提交Git。

## 下一阶段人工命令（本轮不执行）

### 初始化：维护用户，须另行授权

再次确认空data、新配置/程序、无重解析点、日志ACL后执行。defaults-file必须是第一个选项：

```powershell
$demoServer = 'D:\RiskControlDemo\mysql84\server\bin\mysqld.exe'
$demoInit = 'D:\RiskControlDemo\mysql84\conf\my-init.ini'
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Ready -Phase BeforeInitialize
if ($LASTEXITCODE -ne 0) { throw '停止：初始化前预检失败' }
& $demoServer "--defaults-file=$demoInit" --initialize
if ($LASTEXITCODE -ne 0) { throw '停止：保留现场，不清理或重试' }
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Ready -Phase BeforeRegister
if ($LASTEXITCODE -ne 0) { throw '停止：初始化后检查失败' }
```

只用initialize，不用initialize-insecure或console。临时root密码可能在受保护的initialize.err；维护人员在本机安全查看并存入批准的密码管理器，不复制到聊天、录屏、命令参数、Git或项目日志。初始化完成应退出，不长期监听。非空目录或非零退出即停止，不删除重来。

### 注册、服务权限与首次启动：Windows管理员，须另行授权

初始化后确认服务名不存在。以下命令只注册手动服务，默认系统身份期间绝不启动：

```powershell
& 'D:\RiskControlDemo\mysql84\server\bin\mysqld.exe' --install-manual RiskControlMySQL84 '--defaults-file=D:\RiskControlDemo\mysql84\conf\my.ini'
if ($LASTEXITCODE -ne 0) { throw '停止：注册失败，不覆盖已有服务' }
# PowerShell原样参数；虚拟账号不使用真实密码。
sc.exe --% config RiskControlMySQL84 obj= "NT SERVICE\RiskControlMySQL84" password= ""
if ($LASTEXITCODE -ne 0) { throw '停止：服务身份设置失败' }
```

注册后核对SID可解析和真实StartName，再生成精确逐目录授权命令，人工审核后执行：父目录遍历、根/server/conf读取执行、data/logs修改；不授权备份、旧MySQL目录，不赋予conf写权限，不使用无界/T授权。专用账号的登录权、临时目录访问也须检查。当前不预填不存在的SID或提前授权。

```powershell
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Ready -Phase BeforeStart
if ($LASTEXITCODE -ne 0) { throw '停止：不允许启动' }
# 仅获得首次启动授权且服务权限核查通过后：
Start-Service -Name RiskControlMySQL84
pwsh -NoProfile -File data/bootstrap/preflight.ps1 -Mode Ready -Phase AfterStart
if ($LASTEXITCODE -ne 0) { throw '停止：禁止连接和建库' }
```

同时确认旧MySQL80及3306归属未变。失败不自动删除服务、改旧实例或清理数据。

### 认证依赖和账号初始化：分开授权

需要独立Python3.11/3.12及../requirements.txt依赖；脚本不自动安装，不能用当前Python3.7代替。首次root过期密码由维护人员本机安全修改，不将密码放入命令行。

```powershell
pwsh -NoProfile -File data/bootstrap/02_provision_users.ps1 -PythonExe '<Python3.11/3.12完整路径>' -Mode CheckDependencies
pwsh -NoProfile -File data/bootstrap/02_provision_users.ps1 -PythonExe '<Python3.11/3.12完整路径>' -Mode VerifyAdmin
# 仅获得建库/账号授权后，交互输入确认及密码：
pwsh -NoProfile -File data/bootstrap/02_provision_users.ps1 -PythonExe '<Python3.11/3.12完整路径>' -Mode Initialize -Apply
```

管理员不交给后端。迁移账号另行配置三库DDL、视图及指定角色授权，不使用全局SUPER、FILE或GRANT ALL；当前脚本不自动创建迁移身份。先按operations.md在空Demo演练迁移，再加载模拟数据。

## 官方依据与边界

[MySQL8.4初始化](https://dev.mysql.com/doc/refman/8.4/en/data-directory-initialization.html)、[Windows服务](https://dev.mysql.com/doc/refman/8.4/en/windows-start-service.html)。下载、安装、注册、首次启动、真实建库与凭据处理须单独授权。MySQL DDL可能部分提交，失败保留现场。撤销文件不自动删除任何账号、库或业务数据。

## 1045 无写入诊断

在本机未开启转录/录屏的交互终端运行02脚本的`-Mode AuthenticateOnly`。保留AfterStart门禁，仅认证并执行目标身份SELECT，不运行初始化；仅报告成功或安全错误码。优先手动输入，控制字符将拒绝，不自动修剪或转换密码。

CMD对照使用`mysql.exe --no-defaults --no-login-paths --protocol=TCP --host=127.0.0.1 --port=3307 --user=root --password`，由提示安全输入密码。成功后仅执行`SELECT VERSION(), @@port, CURRENT_USER();`。仅认证失败时不要重试Initialize。

非ASCII密码须注意客户端编码差异：PyMySQL默认将字符串密码编码为latin1；当前脚本显式传入UTF-8字节，不改变服务端密码。真实服务端兼容性须通过仅认证模式验证。不要提供密码、摘要或原始异常全文。

### 当前 Windows 密码输入机制

**以下CONIN$方案已停用，仅保留历史说明；所有当前模式均使用PowerShell原生安全输入与匿名管道。**

Python连接进程通过windows_console.py直接打开CONIN$/CONOUT$，以ReadConsoleW读取Unicode。密码提示期间关闭回显、行输入历史、处理输入和VT输入，不通过stdin管道或PowerShell传递密码，不降级为可回显输入。提示前清除遗留输入，提示出现后再输入或单行粘贴；不要提前输入或一次粘贴多个密码。

只移除Enter结束符，不修剪空格或归一化Unicode。控制字符拒绝；Ctrl+C取消，Ctrl+Z视为EOF。finally清理遗留输入、恢复原控制台模式并关闭句柄。不使用剪贴板API，不记录输入内容、长度或摘要。仍须关闭转录/录屏；Python字符串不保证物理内存擦除。

AuthenticateOnly成功仅报告AUTHENTICATION PASS，失败只报告固定安全类别；操作系统预检仍保留。InspectObjects仅查询目标库及身份，未取得该查询结果前不得声称目标对象不存在。新机制的实际终端粘贴、输入法和非ASCII密码认证仍需本机验证，离线测试不代表1045已根治。

### PowerShell原生安全输入：当前独立只读入口

运行`06_authenticate_secure.ps1 -PythonExe <独立Python绝对路径>`。保留AfterStart及认证依赖门禁，必须使用真实本机交互终端且关闭转录/录屏。Read-Host -AsSecureString负责隐藏输入；不再调用windows_console.py。02的AuthenticateOnly也转到此入口。仅认证并SELECT检查版本、3307、固定datadir及root@localhost，不执行初始化。

传输为ProcessStartInfo定向的本地匿名stdin管道：4字节小端帧长加UTF-8 JSON，EOF结束。帧长仅用于内存协议，不输出到终端或日志。密码从SecureString短暂转换为BSTR/托管字符串/UTF-8字节，随后发送到本次创建的Python子进程；参数中只有代码路径和模式。禁止将凭据放入环境变量、磁盘文件或PowerShell输出管道。脚本仅转发白名单结果，丢弃子进程原始stderr；异常/超时只报告安全类别。

finally清零BSTR及可变字节数组、释放SecureString、关闭管道和进程对象；Python清零接收缓冲并释放字符串引用。托管字符串、Python字符串及系统管道缓冲无法保证物理内存立即擦除；同用户恶意进程、管理员/调试器、内存转储不在此进程间隔离的保护范围内。此方案不是端到端加密，也不能防止键盘记录或录屏。

维护人员已在本机PowerShell7.6.9验证06入口真实root认证通过。02的Initialize、InspectObjects、VerifyAdmin、VerifyRuntime、InspectDown现使用同一Read-Host与匿名管道机制：Python只发送无凭据的请求，PowerShell逐项隐藏输入并发送UTF-8帧。独立06入口以EOF结束单帧；02为多轮帧协议，每帧有明确长度，直到结果/取消才关闭。没有getpass或windows_console调用。

Initialize必须同时满足-Apply及人工输入精确确认短语；Python在同一连接内检查已有账号/权限。只收集缺失账号的密码，每项非空、无控制字符、至少16字符并两次确认；本次新建账号之间必须使用不同密码。所有缺失账号均确认后才运行01 SQL。已有账号不重设密码；跨已有账号的密码差异无法在不取回密码的前提下验证。中途取消关闭管道并终止本次Python子进程；不自动删除已创建对象。故障发生在SQL阶段时可能部分提交，禁止盲目重试。

新多轮链路已通过真实交互终端的合成管理员密码、确认短语及三个不同账号密码两次确认，SQL仅由内存替身接收。它没有替代真实MySQL的初始化及权限验收；DA-01仍未完成。InspectObjects输出目标库和目标身份计数（非密码长度），真实对象状态以该只读结果为准。

### 当前正式执行顺序

在项目根目录、未开启转录/录屏的管理员PowerShell7中，设置独立Python路径后依次执行；每步非零即停止，保留现场。以下命令本轮未执行真实初始化。

```powershell
$py = 'D:\RiskControlDemo\python312-venv\Scripts\python.exe'
$runner = Join-Path (Get-Location) 'data/bootstrap/02_provision_users.ps1'
pwsh -NoProfile -File $runner -PythonExe $py -Mode InspectObjects
if ($LASTEXITCODE -ne 0) { throw '停止：只读盘点失败' }
# 若存在目标对象，先人工核对，不删库或重设密码。
pwsh -NoProfile -File $runner -PythonExe $py -Mode Initialize -Apply
if ($LASTEXITCODE -ne 0) { throw '停止：保留部分状态，不自动回退' }
pwsh -NoProfile -File $runner -PythonExe $py -Mode VerifyAdmin
if ($LASTEXITCODE -ne 0) { throw '停止：管理验收失败' }
pwsh -NoProfile -File $runner -PythonExe $py -Mode VerifyRuntime
if ($LASTEXITCODE -ne 0) { throw '停止：运行账号验收失败' }
```

管理验收针对DA-01空库状态；运行验收只验证登录和默认角色，不声称已验证DA-02之后的表/视图权限。

### 初始化后运行账号1045：只读定位，不重跑Initialize

维护人员已确认Initialize退出0及VerifyAdmin通过；本地没有再次执行初始化。账号创建为localhost、caching_sha2_password，密码按账号名取出并以字符串参数传入CREATE USER；登录仍是同一用户名、127.0.0.1:3307及UTF-8字节，没有自动修剪/归一化或二次编码。真实PyMySQL离线测试覆盖普通字符、引号、反斜杠、Unicode和尾随空格，在两种SQL转义模式下均与握手密码字节一致；这不证明实际输入正确或实际服务端认证成功。

先运行02的InspectObjects：用管理员安全输入，仅SELECT目标库/身份及三个运行账号的host、锁定状态、认证插件、默认角色，不读取authentication_string。然后运行`-Mode AuthenticateRuntime -RuntimeUser rc_demo_app`：仅输入该运行账号密码，只验证认证与实例/匹配账号身份，不要求默认角色匹配；与完整VerifyRuntime区分。

若单账号认证仍1045，用本机CMD客户端独立对照：

```cmd
"D:\RiskControlDemo\mysql84\server\bin\mysql.exe" --no-defaults --no-login-paths --protocol=TCP --host=127.0.0.1 --port=3307 --user=rc_demo_app --password
```

密码仅在客户端提示中输入；成功后只执行`SELECT VERSION(), @@port, CURRENT_USER(), CURRENT_ROLE();`。两种客户端均拒绝不能单独证明密码错误，仍须结合host/锁定/插件元数据；CMD成功而新模式失败才进一步定位客户端编码或认证路径，不能自行重置密码/更改插件。单账号认证通过后再运行VerifyRuntime。新错误类别区分AUTHENTICATION_REJECTED与ROLE_MISMATCH，阶段含账号名；不输出原始异常、密码长度或摘要。

### 密码收集中途退出

失败信息仅包含固定阶段、错误类别、数值错误码及writes_started标志，不输出异常原文或密码。新密码先检查非空、控制字符和16字符最小长度，再读取确认。所有缺失账号的密码均确认后才开始01 SQL；收集中途失败会清空收集字典引用，不保证Python字符串物理内存擦除。终端须关闭转录/录屏。

只读对象核查使用02脚本`-Mode InspectObjects`，由本机隐藏提示输入管理员密码。模式仅执行目标身份检查和目标schema/mysql.user名称、host、锁定状态SELECT，不读取认证摘要；两组结果均为空才说明当前无目标对象。若发现已有对象，先审核部分状态，不删除或自动清理。
