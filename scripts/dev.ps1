param(
  [int]$ApiPort = 8000,
  [int]$FrontendPort = 5173,
  [string]$FrontendPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $FrontendPath) {
  $FrontendPath = Join-Path $Root "..\lifeops-front"
}
$FrontendRoot = Resolve-Path $FrontendPath

Write-Host "LifeOps local dev"
Write-Host "API:      http://localhost:$ApiPort"
Write-Host "Frontend: http://localhost:$FrontendPort"
Write-Host ""

$apiArgs = @("-m", "uvicorn", "api:app", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort")
$frontArgs = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort")

$api = Start-Process -FilePath "python" -ArgumentList $apiArgs -WorkingDirectory $Root -PassThru
$front = Start-Process -FilePath "npm" -ArgumentList $frontArgs -WorkingDirectory $FrontendRoot -PassThru

try {
  Write-Host "Started. Close this window or press Ctrl+C to stop both processes."
  while (-not $api.HasExited -and -not $front.HasExited) {
    Start-Sleep -Seconds 1
  }
}
finally {
  foreach ($process in @($api, $front)) {
    if ($process -and -not $process.HasExited) {
      Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
  }
}
