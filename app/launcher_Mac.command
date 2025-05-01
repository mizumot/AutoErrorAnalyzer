#!/bin/bash

# 色付きの出力用の関数
print_info() {
    echo -e "\033[0;34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m[SUCCESS]\033[0m $1"
}

print_error() {
    echo -e "\033[0;31m[ERROR]\033[0m $1"
}

# エラーハンドリング関数
handle_error() {
    print_error "$1"
    if [ -n "$VIRTUAL_ENV" ]; then
        deactivate
    fi
    exit 1
}

echo "==================================="
echo "Python Application Setup and Launch"
echo "==================================="

# アプリケーションディレクトリに移動
cd "$(dirname "$0")" || handle_error "Failed to change directory"

# Python3のバージョン確認
if ! command -v python3 &> /dev/null; then
    handle_error "Python3 is not installed. Please install Python3 manually."
else
    PYTHON_VERSION=$(python3 --version)
    print_success "$PYTHON_VERSION is installed"
fi

# pip3の確認
if ! command -v pip3 &> /dev/null; then
    handle_error "pip3 is not installed. Please install pip3 manually."
fi

# 仮想環境のセットアップを確認
if [ ! -d "venv" ]; then
    print_info "Creating a new virtual environment..."
    python3 -m venv venv || handle_error "Failed to create virtual environment"
    print_success "Virtual environment created successfully"
else
    print_info "Virtual environment 'venv' already exists"
fi

# 仮想環境を有効化
source venv/bin/activate || handle_error "Failed to activate virtual environment"
print_success "Virtual environment activated"

# pipのアップグレード
print_info "Upgrading pip..."
pip install --upgrade pip || handle_error "Failed to upgrade pip"

# 必要なモジュールを確認・インストール
if [ ! -f requirements.txt ]; then
    handle_error "requirements.txt not found"
fi

print_info "Checking required packages..."
NEEDS_INSTALL=0
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -z "$line" ]] || [[ "$line" =~ ^[[:space:]]*# ]]; then
        continue
    fi
    PKG=$(echo "$line" | cut -d'=' -f1)
    PKG=$(echo "$PKG" | tr -d ' ')
    if ! pip show "$PKG" &> /dev/null; then
        NEEDS_INSTALL=1
        break
    fi
done < requirements.txt

if [ $NEEDS_INSTALL -eq 1 ]; then
    print_info "Installing required packages..."
    pip install -r requirements.txt || handle_error "Failed to install requirements"
    print_success "All packages installed successfully"
else
    print_success "All required packages are already installed"
fi

# spaCy のモデルを確認・インストール
print_info "Checking spaCy model 'en_core_web_md'..."
if ! python3 -c "import spacy; spacy.load('en_core_web_md')" &> /dev/null; then
    print_info "Downloading spaCy model..."
    python3 -m spacy download en_core_web_md || handle_error "Failed to download spaCy model"
    print_success "spaCy model installed successfully"
else
    print_success "spaCy model is already installed"
fi

# APIキーファイルの確認
if [ ! -f "API.txt" ]; then
    handle_error "API.txt file not found. Please create API.txt with your API key"
fi

# アプリケーションの起動
print_info "Starting the application..."
python3 app.py

# 終了コードの確認
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    handle_error "The application exited with code $EXIT_CODE"
fi

# 仮想環境の無効化
deactivate
print_success "Application has been closed successfully"

echo "==================================="
read -n 1 -s -r -p "Press any key to exit..."