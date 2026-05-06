#!/bin/bash

# Oracle Forge Setup Script
# This script sets up the complete environment for a newcomer

set -e  # Exit on any error

echo "=========================================="
echo "Oracle Forge - Complete Setup Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_step() {
    echo -e "${BLUE}Step $1: $2${NC}"
}

print_success() {
    echo -e "${GREEN}SUCCESS: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}WARNING: $1${NC}"
}

print_error() {
    echo -e "${RED}ERROR: $1${NC}"
}

check_command() {
    if command -v $1 &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Step 1: Check Prerequisites
print_step "1" "Checking Prerequisites"

echo "Checking required software..."

if ! check_command python3; then
    print_error "Python 3 is required but not installed"
    echo "Please install Python 3.10+ from https://python.org"
    exit 1
fi

if ! check_command docker; then
    print_error "Docker is required but not installed"
    echo "Please install Docker from https://docker.com"
    exit 1
fi

if ! check_command git; then
    print_error "Git is required but not installed"
    echo "Please install Git from https://git-scm.com"
    exit 1
fi

print_success "All prerequisites installed"

# Step 2: Install uv
print_step "2" "Installing uv (Python Package Manager)"

if ! check_command uv; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    
    # Add to shell profile
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
    echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.zshrc 2>/dev/null || true
    
    print_success "uv installed"
else
    print_success "uv already installed"
fi

# Step 3: Install Python Dependencies
print_step "3" "Installing Python Dependencies"

echo "Installing project dependencies..."
uv sync

print_success "Dependencies installed"

# Step 4: Set Up Environment
print_step "4" "Setting Up Environment"

if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    print_success ".env file created"
else
    print_warning ".env file already exists"
fi

echo ""
echo "IMPORTANT: You must edit .env and add your LLM API key!"
echo "Choose ONE of the following options:"
echo "1. OpenRouter: Get key from https://openrouter.ai/keys"
echo "2. Anthropic: Get key from https://console.anthropic.com/"
echo ""
echo "Edit .env now and add your API key before continuing!"

read -p "Press Enter after you've added your API key (or Ctrl+C to exit)..."

# Step 5: Start Docker Services
print_step "5" "Starting Docker Services"

echo "Starting PostgreSQL container..."
if ! docker ps | grep -q team-dab-postgres; then
    docker run -d --name team-dab-postgres \
        -e POSTGRES_DB=bookreview_db \
        -e POSTGRES_USER=postgres \
        -e POSTGRES_PASSWORD=teampalm \
        -p 5432:5432 \
        postgres:15
    print_success "PostgreSQL container started"
else
    print_success "PostgreSQL container already running"
fi

echo "Starting MongoDB container..."
if ! docker ps | grep -q team-dab-mongo; then
    docker run -d --name team-dab-mongo \
        -p 27017:27017 \
        mongo:6.0
    print_success "MongoDB container started"
else
    print_success "MongoDB container already running"
fi

# Step 6: Start MCP Servers
print_step "6" "Starting MCP Servers"

echo "Starting Google Toolbox MCP Server..."
if ! pgrep -f "toolbox/mcp_server.py" > /dev/null; then
    uv run python toolbox/mcp_server.py > toolbox_server.log 2>&1 &
    sleep 2
    print_success "Google Toolbox MCP Server started"
else
    print_success "Google Toolbox MCP Server already running"
fi

echo "Starting DuckDB MCP Server..."
if ! pgrep -f "duckdb_mcp_server.py" > /dev/null; then
    uv run python agent/duckdb_mcp_server.py > duckdb_server.log 2>&1 &
    sleep 2
    print_success "DuckDB MCP Server started"
else
    print_success "DuckDB MCP Server already running"
fi

# Step 7: Verify Setup
print_step "7" "Verifying Setup"

echo "Testing database connections..."

# Test PostgreSQL
if curl -s http://127.0.0.1:5000/mcp -X POST -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' > /dev/null; then
    print_success "Google Toolbox MCP Server responding"
else
    print_error "Google Toolbox MCP Server not responding"
fi

# Test MongoDB
if docker exec team-dab-mongo mongosh --eval "db.adminCommand('ping')" > /dev/null 2>&1; then
    print_success "MongoDB container responding"
else
    print_error "MongoDB container not responding"
fi

# Test PostgreSQL
if docker exec team-dab-postgres pg_isready > /dev/null 2>&1; then
    print_success "PostgreSQL container responding"
else
    print_error "PostgreSQL container not responding"
fi

# Step 8: Run Test Query
print_step "8" "Running Test Query"

echo "Testing Oracle Forge with a simple query..."
echo "This may take a minute..."

if uv run python run_agent.py \
    --dataset bookreview \
    --query query_bookreview_benchmark/query1/query.json \
    --iterations 5 \
    --root_name setup_test > setup_test.log 2>&1; then
    print_success "Test query completed successfully"
else
    print_warning "Test query had issues (check setup_test.log)"
fi

# Step 9: Show Results
print_step "9" "Setup Complete!"

echo ""
echo "=========================================="
echo "Oracle Forge Setup Complete!"
echo "=========================================="
echo ""
echo "What's next:"
echo "1. Read README.md for detailed usage instructions"
echo "2. Run more queries: uv run python run_agent.py --help"
echo "3. Evaluate performance: uv run python eval/run_evaluation.py --help"
echo "4. Check logs: tail -f setup_test.log"
echo ""
echo "Useful commands:"
echo "- Check Docker: docker ps"
echo "- Check MCP servers: ps aux | grep mcp"
echo "- View results: ls results/"
echo "- Score performance: uv run python eval/run_evaluation.py --progress"
echo ""
echo "If you encounter issues:"
echo "1. Check .env file for correct API key"
echo "2. Verify Docker containers are running"
echo "3. Review setup_test.log for errors"
echo "4. See README.md troubleshooting section"
echo ""
print_success "Welcome to Oracle Forge!"
