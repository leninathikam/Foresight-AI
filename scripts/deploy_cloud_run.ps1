# Foresight-AI: Google Cloud Run Automated Deployment Script
# Berkeley x DeepMind Hackathon Submission

param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "us-central1",
    [string]$GeminiApiKey = $env:GEMINI_API_KEY
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Foresight-AI: Google Cloud Run Deployment Pipeline        " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Check gcloud CLI
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] gcloud CLI not found in PATH." -ForegroundColor Red
    Write-Host "Please install Google Cloud SDK or complete the administrator installation prompt." -ForegroundColor Yellow
    Write-Host "Download: https://cloud.google.com/sdk/docs/install" -ForegroundColor Yellow
    exit 1
}

# 2. Validate GCP Project
if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
}

if (-not $ProjectId -or $ProjectId -eq "(unset)") {
    Write-Host "[WARNING] No Google Cloud Project configured." -ForegroundColor Yellow
    $ProjectId = Read-Host "Please enter your GCP Project ID"
}

if (-not $ProjectId) {
    Write-Host "[ERROR] Project ID is required for Cloud Run deployment." -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Using GCP Project: $ProjectId" -ForegroundColor Green
Write-Host "[INFO] Deployment Region: $Region" -ForegroundColor Green
gcloud config set project $ProjectId --quiet

# 3. Read GEMINI_API_KEY from .env if not passed
if (-not $GeminiApiKey -and (Test-Path ".env")) {
    $match = (Get-Content .env | Select-String "^GEMINI_API_KEY=(.*)")
    if ($match) {
        $GeminiApiKey = $match.Matches[0].Groups[1].Value.Trim()
    }
}

# 4. Enable Google Cloud APIs
Write-Host "[INFO] Enabling required Cloud Run and Cloud Build APIs..." -ForegroundColor Cyan
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project $ProjectId

# 5. Build & Deploy Backend (FastAPI + Twin ODE + ML Engine)
Write-Host "[INFO] Deploying Backend Service (foresight-api) to Cloud Run..." -ForegroundColor Cyan
$BackendEnvVars = "FORESIGHT_LLM_PROVIDER=gemini,FORESIGHT_GEMINI_MODEL=gemini-2.5-flash"
if ($GeminiApiKey) {
    $BackendEnvVars += ",GEMINI_API_KEY=$GeminiApiKey"
}

$BackendDeploy = gcloud run deploy foresight-api `
    --source . `
    --platform managed `
    --region $Region `
    --allow-unauthenticated `
    --set-env-vars $BackendEnvVars `
    --format "value(status.url)" `
    --project $ProjectId

$ApiUrl = $BackendDeploy.Trim()
Write-Host "[SUCCESS] Backend deployed at: $ApiUrl" -ForegroundColor Green

# 6. Build & Deploy Frontend (Next.js 16 Web UI)
Write-Host "[INFO] Deploying Frontend Service (foresight-web) to Cloud Run..." -ForegroundColor Cyan
Set-Location "apps/web"

$FrontendDeploy = gcloud run deploy foresight-web `
    --source . `
    --platform managed `
    --region $Region `
    --allow-unauthenticated `
    --set-env-vars "NEXT_PUBLIC_API_BASE_URL=$ApiUrl" `
    --format "value(status.url)" `
    --project $ProjectId

Set-Location "../.."
$WebUrl = $FrontendDeploy.Trim()
Write-Host "[SUCCESS] Frontend deployed at: $WebUrl" -ForegroundColor Green

# 7. Update Backend CORS Origins to accept Frontend Cloud Run URL
Write-Host "[INFO] Updating Backend CORS configuration..." -ForegroundColor Cyan
gcloud run services update foresight-api `
    --update-env-vars "FORESIGHT_CORS_ORIGINS=http://localhost:3000,$WebUrl" `
    --region $Region `
    --project $ProjectId `
    --quiet

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Foresight-AI: Cloud Run Deployment Complete!             " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Public Web App:       $WebUrl" -ForegroundColor Yellow
Write-Host "Public API Health:    $ApiUrl/api/health" -ForegroundColor Yellow
Write-Host "Future Arena:         $WebUrl/arena" -ForegroundColor Yellow
Write-Host "Safety Challenge:     $WebUrl/safety-challenge" -ForegroundColor Yellow
Write-Host "Decision Receipts:    $WebUrl/receipts" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
