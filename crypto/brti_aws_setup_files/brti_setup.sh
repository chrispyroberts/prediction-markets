#!/bin/bash

set -e
echo "🚀 Starting BRTI tracker environment setup..."

# 1. Update and install system packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv

# 2. Optional: create virtualenv
python3 -m venv brti-env
source brti-env/bin/activate

# 3. Install Python dependencies
pip install --upgrade pip
pip install playwright numpy psutil pytz dotenv psycopg2-binary

# 4. Install Chromium for Playwright
playwright install-deps  
playwright install chromium

echo "✅ Setup complete!"
