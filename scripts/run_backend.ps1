Write-Host "Running FastAPI Backend..."
cd ..\backend
if (!(Test-Path -Path "venv\Scripts\activate.ps1")) {
    Write-Error "Virtual environment not found. Please run setup_backend.ps1 first."
    exit
}
.\venv\Scripts\activate
uvicorn app.main:app --reload
