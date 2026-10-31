@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/4] 读取 .env ...
if exist .env (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" set "%%a=%%b"
  )
) else (
  echo 未找到 .env，将使用系统环境变量；可先复制 .env.example 为 .env
)
if "%APP_PORT%"=="" set APP_PORT=8000

echo [2/4] 准备 Python 环境 ...
if not exist .venv (
  python -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat
python -m pip install -q -U pip
python -m pip install -q -r backend\requirements.txt || goto :err

echo [3/4] 检查前端构建产物 ...
if not exist frontend\dist\index.html (
  echo   构建借款侧前端（需要 Node.js）...
  pushd frontend && call npm ci && call npm run build:app || goto :err
  popd
)
if not exist frontend-admin\dist\index.html (
  echo   构建银行侧前端（需要 Node.js）...
  pushd frontend-admin && call npm ci && call npm run build:bank || goto :err
  popd
)

echo [4/4] 启动服务：http://127.0.0.1:%APP_PORT%/ （借款侧） /bank/（银行侧）
start "" http://127.0.0.1:%APP_PORT%/bank/
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port %APP_PORT%
goto :eof

:err
echo 启动失败，请检查上一步的错误信息。
exit /b 1

