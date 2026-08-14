Write-Host "Setting up Python virtual environment..."
cd ..\backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
Write-Host "Backend setup complete!"
