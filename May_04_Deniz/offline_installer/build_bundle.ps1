$ErrorActionPreference = "Stop"

$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Wheelhouse = Join-Path $BundleRoot "wheelhouse"
$Installers = Join-Path $BundleRoot "installers"
$FfmpegBin = Join-Path $BundleRoot "ffmpeg\bin"
$Requirements = Join-Path $BundleRoot "requirements-offline.txt"
$ManifestPath = Join-Path $BundleRoot "manifest.sha256"
$PythonVersion = "3.14.5"
$PythonMajorMinor = "3.14"
$PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
$PythonInstallerPath = Join-Path $Installers "python-$PythonVersion-amd64.exe"

New-Item -ItemType Directory -Force -Path $Wheelhouse, $Installers, $FfmpegBin | Out-Null

function Run-Step([string[]]$Command) {
    Write-Host ("RUN " + ($Command -join " "))
    $args = @()
    if ($Command.Count -gt 1) {
        $args = $Command[1..($Command.Count - 1)]
    }
    & $Command[0] @args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Write-BundleManifest {
    $manifestRoots = @(
        (Join-Path $BundleRoot "wheelhouse"),
        (Join-Path $BundleRoot "installers"),
        (Join-Path $BundleRoot "ffmpeg")
    )
    $lines = @()
    foreach ($root in $manifestRoots) {
        if (-not (Test-Path $root)) {
            continue
        }
        $files = Get-ChildItem -LiteralPath $root -Recurse -File | Sort-Object FullName
        foreach ($file in $files) {
            $relative = $file.FullName.Substring($BundleRoot.Length + 1).Replace("\", "/")
            $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $lines += ("{0} *{1}" -f $hash, $relative)
        }
    }
    Set-Content -LiteralPath $ManifestPath -Value $lines -Encoding ASCII
    Write-Host ("Wrote SHA-256 manifest: {0}" -f $ManifestPath)
}

Write-Host "Refreshing wheelhouse..."
Get-ChildItem -Path $Wheelhouse -Filter "*.whl" -ErrorAction SilentlyContinue | Remove-Item -Force
Run-Step @(
    "python", "-m", "pip", "download",
    "--only-binary=:all:",
    "--platform", "win_amd64",
    "--implementation", "cp",
    "--python-version", $PythonMajorMinor,
    "--abi", "cp314",
    "--abi", "abi3",
    "--abi", "none",
    "--dest", $Wheelhouse,
    "-r", $Requirements
)

Write-Host "Downloading optional Python installer..."
if (-not (Test-Path $PythonInstallerPath)) {
    Invoke-WebRequest -Uri $PythonInstallerUrl -OutFile $PythonInstallerPath
}

Write-Host "Copying local FFmpeg binaries..."
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    $sourceBin = Split-Path -Parent $ffmpeg.Source
    Copy-Item -Path (Join-Path $sourceBin "*") -Destination $FfmpegBin -Recurse -Force
    Write-Host ("Copied FFmpeg from {0}" -f $sourceBin)
} else {
    Write-Warning "FFmpeg was not found in PATH. Place ffmpeg.exe, ffprobe.exe, and related DLLs in ffmpeg\bin manually."
}

Write-BundleManifest

Write-Host ""
Write-Host "Offline bundle refreshed."
