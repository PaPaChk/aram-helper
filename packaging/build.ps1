# 打包：PyInstaller 生成程式目錄 → GUI 自檢 → Inno Setup 安裝版 + 便攜版 ZIP + SHA256SUMS.txt。
# 用法（PowerShell 7）：pwsh -NoProfile -File packaging/build.ps1 [-PythonExe <python>] [-InnoCompiler <ISCC.exe>]
# 輸出：build/release/AramHexTW-Setup-<版本>.exe、AramHexTW-Portable-<版本>.zip、SHA256SUMS.txt
param([string]$PythonExe, [string]$InnoCompiler)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'  # 控制檯不是 UTF-8 時（如 GitHub 的 Windows 構建機）輸出中文也不能崩
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = if ($PythonExe) { (Get-Command $PythonExe).Source } else { Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path $py)) { throw "缺少 Python：先執行 python -m venv .venv 並安裝 requirements-build.txt" }
& $py -m PyInstaller --version
if ($LASTEXITCODE) { throw '缺少 PyInstaller：pip install -r requirements-build.txt' }

$version = (& $py -c "import lolhex; print(lolhex.__version__)").Trim()
Write-Host "版本 $version"
if (-not (Test-Path (Join-Path $root 'lolhex\data\bundled\latest.json'))) {
    throw '缺少內建統計資料：先執行 python scripts/update_data.py'
}
& $py -c "from lolhex.data.public import Dataset, BUNDLED_DIR; d = Dataset(BUNDLED_DIR, 'bundled'); print('內建資料', d.patch, d.snapshot_at)"
if ($LASTEXITCODE) { throw '內建統計資料校驗失敗' }

$originalPath = $env:PATH
$originalPythonPath = $env:PYTHONPATH
$originalPyinstallerConfig = $env:PYINSTALLER_CONFIG_DIR
try {
    $basePython = (& $py -c 'import sys; print(sys.base_prefix)').Trim()
    $env:PATH = @((Split-Path $py), $basePython, (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    $env:PYTHONPATH = $null
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $root 'build\pyinstaller-cache'
    Push-Location packaging
    try {
        & $py -m PyInstaller lolhex.spec --clean --noconfirm --distpath ..\build\dist --workpath ..\build\work
        $code = $LASTEXITCODE
    } finally { Pop-Location }
} finally {
    $env:PATH = $originalPath
    $env:PYTHONPATH = $originalPythonPath
    $env:PYINSTALLER_CONFIG_DIR = $originalPyinstallerConfig
}
if ($code) { throw 'PyInstaller 打包失敗' }
$dist = Join-Path $root 'build\dist\AramHexTW'

# 真實 Windows 視窗外掛下跑一遍 Qt（QtCore/Gui/Widgets/Network），再跑一遍 OpenCV 和文字識別
$report = Join-Path $root 'build\gui-smoke.json'
if (Test-Path -LiteralPath $report) { Remove-Item -LiteralPath $report }
$smoke = Start-Process -FilePath (Join-Path $dist 'AramHexTW.exe') -ArgumentList @('--self-test-gui', ('"' + $report + '"')) -WindowStyle Hidden -PassThru
if (-not $smoke.WaitForExit(180000)) { $smoke.Kill(); throw '自檢超時' }
if ($smoke.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) { throw 'Qt GUI 自檢失敗，不生成安裝包' }
$gui = Get-Content -Raw -Encoding UTF8 -LiteralPath $report | ConvertFrom-Json
if (-not $gui.success -or $gui.version -ne $version -or $gui.platform -ne 'windows' -or -not $gui.ocr_ok) { throw "自檢結果不對（介面或文字識別）：$($gui | ConvertTo-Json -Compress)" }
Write-Host "自檢透過：Qt $($gui.qt)，文字識別讀到「$($gui.ocr_text)」"

$iscc = @($InnoCompiler, (Join-Path $root '.tools\inno\ISCC.exe'), "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw '缺少 Inno Setup 6：winget install --id JRSoftware.InnoSetup -e' }
& $iscc "/DAppVersion=$version" packaging\LolHex.iss
if ($LASTEXITCODE) { throw 'Inno Setup 編譯失敗' }

$out = Join-Path $root 'build\release'
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Path $out | Out-Null
$setup = "AramHexTW-Setup-$version.exe"
Copy-Item (Join-Path $root "build\installer\$setup") (Join-Path $out $setup)

# 便攜版：同一份程式目錄 + portable.txt（有它時配置、日誌、資料都放在程式目錄的 userdata 下）
$stage = Join-Path $root "build\portable\AramHexTW-$version"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -Recurse (Join-Path $dist '*') $stage
Set-Content -LiteralPath (Join-Path $stage 'portable.txt') -Encoding utf8 -Value @'
這是便攜版：配置、日誌和下載的資料都放在本目錄的 userdata 資料夾裡，不寫系統目錄。
刪除整個資料夾即可解除安裝。有新版本時助手會提示，請到 GitHub 下載新的便攜版替換。
https://github.com/PaPaChk/aram-helper/releases
'@
Copy-Item (Join-Path $root 'LICENSE') $stage
$zip = "AramHexTW-Portable-$version.zip"
Compress-Archive -Path $stage -DestinationPath (Join-Path $out $zip) -CompressionLevel Optimal

$sums = foreach ($name in @($setup, $zip)) {
    '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $out $name)).Hash.ToLowerInvariant(), $name
}
Set-Content -LiteralPath (Join-Path $out 'SHA256SUMS.txt') -Encoding ascii -Value $sums
Get-ChildItem $out | ForEach-Object { '{0}  {1:N1} MB' -f $_.Name, ($_.Length / 1MB) }
