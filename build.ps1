Write-Host "=== File Server 建置腳本 ===" -ForegroundColor Cyan
Write-Host ""

# 確保 dist 目錄存在
if (-not (Test-Path -LiteralPath "dist")) {
    New-Item -ItemType Directory -Path "dist" | Out-Null
}

Write-Host "[1/3] 建置 Docker 映像 (這可能需要 5-10 分鐘)..." -ForegroundColor Yellow
docker build -t file-server-builder .
if ($LASTEXITCODE -ne 0) {
    Write-Host "建置失敗！" -ForegroundColor Red
    exit 1
}

Write-Host "[2/3] 提取 file_server.exe..." -ForegroundColor Yellow
Remove-Item -LiteralPath "dist/file_server.exe" -Force -ErrorAction SilentlyContinue
$id = docker create file-server-builder
docker cp "${id}:/src/dist/file_server.exe" "dist/"
docker rm $id
if ($LASTEXITCODE -ne 0) {
    Write-Host "提取失敗！" -ForegroundColor Red
    exit 1
}

Write-Host "[3/3] 清理..." -ForegroundColor Yellow
docker rmi file-server-builder -f

Write-Host ""
Write-Host "=== 建置完成！===" -ForegroundColor Green
Write-Host "執行檔位置: $((Get-Item 'dist/file_server.exe').FullName)" -ForegroundColor Green
Write-Host ""
Write-Host "使用方法:" -ForegroundColor White
Write-Host "  1. 執行 dist\file_server.exe" -ForegroundColor White
Write-Host "  2. 修改 config.json 設定共享目錄" -ForegroundColor White
Write-Host "  3. 在 iPhone 捷徑輸入顯示的 IP 和配對碼" -ForegroundColor White
