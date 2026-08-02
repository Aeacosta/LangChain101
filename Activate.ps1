# PowerShell Script to Activate Python Environment

# Set working directory
$CurrentDirectory = $PSScriptRoot

# Create a virtual environment if it doesn't exist
Write-Host "Creating virtual environment..."
python -m venv .venv

# Activate the virtual environment
Write-Host "Activating virtual environment..."
.venv\Scripts\activate

# Install dependencies from requirements.txt
Write-Host "Installing dependencies..."
pip install --upgrade -r "$CurrentDirectory\requirements.txt"

# Set up environment variables for the script to work with
Set-Item -Path Env:BASE_URL -Value "http://localhost:11434"
