@echo off
setlocal enabledelayedexpansion

:: スクリプトのディレクトリに移動
cd /d "%~dp0"

echo ===================================
echo Python Environment Setup
echo ===================================

:: Pythonのインストール確認
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed. Installing Python...
    
    :: Pythonインストーラーのダウンロード
    echo Downloading Python installer...
    powershell -Command "(New-Object Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe', 'python_installer.exe')"
    if exist python_installer.exe (
        echo Installing Python...
        start /wait python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
        del python_installer.exe
        
        :: PATHを更新
        echo Refreshing PATH environment...
        for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH') do set "PATH=%%b"
        for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v PATH') do set "PATH=%%b;!PATH!"
        
        echo Waiting for installation to complete...
        timeout /t 10 /nobreak >nul
    ) else (
        echo Failed to download Python installer.
        pause
        exit /b 1
    )
) else (
    echo Python is already installed.
)

:: 仮想環境の確認と作成
if exist "venv\Scripts\activate.bat" (
    echo Found existing virtual environment.
) else (
    echo Creating new virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        echo Please try running this script as administrator.
        pause
        exit /b 1
    )
    if errorlevel 0 (
        echo Updating pip, setuptools, and wheel...
        call venv\Scripts\activate.bat
        python -m pip install --upgrade pip
        pip install --upgrade setuptools wheel
        call venv\Scripts\deactivate.bat
    )
)

:: 仮想環境の有効化
echo Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

:: requirements.txtのスマートインストール
if exist requirements.txt (
    :: 必要なパッケージをチェック
    set NEEDS_INSTALL=0
    for /f "tokens=1" %%a in (requirements.txt) do (
        set "PKG=%%a"
        pip show !PKG! >nul 2>&1
        if errorlevel 1 (
            set NEEDS_INSTALL=1
            goto install_requirements
        )
    )

    :install_requirements
    if !NEEDS_INSTALL!==1 (
        echo Installing missing requirements...
        pip install -r requirements.txt
        if errorlevel 1 (
            echo Failed to install requirements.
            pause
            exit /b 1
        )
    ) else (
        echo All requirements are already installed.
    )
)

:: spaCyモデルのチェックとインストール
python -c "import spacy; spacy.load('en_core_web_md')" >nul 2>&1
if errorlevel 1 (
    pip show spacy >nul 2>&1
    if not errorlevel 1 (
        echo Installing spaCy language model...
        python -m spacy download en_core_web_md
    )
) else (
    echo spaCy model is already installed.
)

:: アプリケーションの起動
echo Starting the application...
python app.py
if errorlevel 1 (
    echo Application exited with an error.
    pause
    exit /b 1
)

:: 仮想環境の無効化
call venv\Scripts\deactivate.bat

echo ===================================
echo Press any key to exit...
pause
exit /b 0