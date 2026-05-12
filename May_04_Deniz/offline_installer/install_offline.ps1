$ErrorActionPreference = "Stop"

$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $BundleRoot
$Wheelhouse = Join-Path $BundleRoot "wheelhouse"
$Requirements = Join-Path $BundleRoot "requirements-offline.txt"
$FfmpegBin = Join-Path $BundleRoot "ffmpeg\bin"
$ManifestPath = Join-Path $BundleRoot "manifest.sha256"
$InstallRoot = Join-Path $env:ProgramData "May_04_Deniz"
$AppInstallRoot = Join-Path $InstallRoot "app"
$SharedVenv = Join-Path $InstallRoot "python_env"
$InstallFfmpegBin = Join-Path $InstallRoot "ffmpeg\bin"
$LauncherDir = Join-Path $InstallRoot "launchers"
$LogDir = Join-Path $BundleRoot "install_logs"
$PreferredPythonVersion = "3.14.5"
$FallbackPythonVersion = "3.13.5"

function Get-MajorMinor([string]$Version) {
    $parts = $Version.Split(".")
    if ($parts.Count -lt 2) {
        return $Version
    }
    return "$($parts[0]).$($parts[1])"
}

function Get-BundledPythonVersion {
    $preferred = Join-Path $BundleRoot "installers\python-$PreferredPythonVersion-amd64.exe"
    if (Test-Path $preferred) {
        return $PreferredPythonVersion
    }
    $fallback = Join-Path $BundleRoot "installers\python-$FallbackPythonVersion-amd64.exe"
    if (Test-Path $fallback) {
        return $FallbackPythonVersion
    }
    return $PreferredPythonVersion
}

$TargetPythonVersion = Get-BundledPythonVersion
$TargetPythonMajorMinor = Get-MajorMinor $TargetPythonVersion
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ("install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Write-Step([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message
    Write-Host $line
    Add-Content -Path $LogPath -Value $line
}

function Run-Logged([string[]]$Command) {
    Write-Step ("RUN " + ($Command -join " "))
    $args = @()
    if ($Command.Count -gt 1) {
        $args = $Command[1..($Command.Count - 1)]
    }
    & $Command[0] @args 2>&1 | Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Administrator {
    if (-not (Test-IsAdministrator)) {
        throw "Administrator rights are required for all-users Python, machine PATH, and ProgramData shared package installation."
    }
}

function Assert-BundleManifest {
    if (-not (Test-Path $ManifestPath)) {
        Write-Step "No manifest.sha256 found; skipping offline bundle integrity verification."
        return
    }

    $checked = 0
    foreach ($line in Get-Content -LiteralPath $ManifestPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch "^([A-Fa-f0-9]{64})\s+\*(.+)$") {
            throw "Invalid manifest line: $trimmed"
        }
        $expected = $Matches[1].ToLowerInvariant()
        $relative = $Matches[2].Replace("/", "\")
        $path = Join-Path $BundleRoot $relative
        if (-not (Test-Path $path)) {
            throw "Manifest file is missing from bundle: $relative"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Manifest hash mismatch for $relative"
        }
        $checked += 1
    }
    Write-Step ("Verified offline bundle integrity for {0} file(s)." -f $checked)
}

function Test-IsMachinePython([string]$Executable) {
    $path = [string]$Executable
    if (-not $path) {
        return $false
    }
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    if ($localAppData -and $path.StartsWith($localAppData, [StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    $programFiles = $env:ProgramFiles
    $programFilesX86 = ${env:ProgramFiles(x86)}
    return ($programFiles -and $path.StartsWith($programFiles, [StringComparison]::OrdinalIgnoreCase)) -or
        ($programFilesX86 -and $path.StartsWith($programFilesX86, [StringComparison]::OrdinalIgnoreCase))
}

function Get-PythonInfoFromCommand([string[]]$Command) {
    try {
        $args = @()
        if ($Command.Count -gt 1) {
            $args = $Command[1..($Command.Count - 1)]
        }
        $output = & $Command[0] @args -c "import sys; print(sys.executable); print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or $output.Count -lt 2) {
            return $null
        }
        $version = [string]$output[1]
        if (-not $version.StartsWith("$TargetPythonMajorMinor.")) {
            Write-Step ("Ignoring Python {0}; this bundle targets Python {1}." -f $version, $TargetPythonMajorMinor)
            return $null
        }
        return @{
            Command = $Command
            Executable = [string]$output[0]
            Version = $version
        }
    } catch {
        return $null
    }
}

function Get-PythonCommand {
    $digits = $TargetPythonMajorMinor.Replace(".", "")
    $machineCandidates = @()
    if ($env:ProgramFiles) {
        $machineCandidates += ,@((Join-Path $env:ProgramFiles "Python$digits\python.exe"))
    }
    if (${env:ProgramFiles(x86)}) {
        $machineCandidates += ,@((Join-Path ${env:ProgramFiles(x86)} "Python$digits\python.exe"))
    }
    foreach ($candidate in $machineCandidates) {
        if (-not (Test-Path $candidate[0])) {
            continue
        }
        $info = Get-PythonInfoFromCommand $candidate
        if ($info -and (Test-IsMachinePython $info.Executable)) {
            return $info
        }
    }

    $candidates = @(
        @("py", "-$TargetPythonMajorMinor"),
        @("python")
    )
    foreach ($candidate in $candidates) {
        $info = Get-PythonInfoFromCommand $candidate
        if (-not $info) {
            continue
        }
        if (-not (Test-IsMachinePython $info.Executable)) {
            Write-Step ("Ignoring per-user Python for all-users setup: {0}" -f $info.Executable)
            continue
        }
        return $info
    }
    return $null
}

function Install-BundledPythonIfNeeded {
    $python = Get-PythonCommand
    if ($python) {
        Write-Step ("Python found: {0} ({1})" -f $python.Executable, $python.Version)
        return $python
    }

    $installer = Get-ChildItem -Path (Join-Path $BundleRoot "installers") -Filter "python-$TargetPythonVersion-amd64.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $installer) {
        $installer = Get-ChildItem -Path (Join-Path $BundleRoot "installers") -Filter "python-$TargetPythonMajorMinor.*-amd64.exe" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    }
    if (-not $installer) {
        throw "Python $TargetPythonMajorMinor was not found, and no installers\python-$TargetPythonVersion-amd64.exe file is bundled."
    }

    Write-Step ("Installing bundled Python: {0}" -f $installer.Name)
    Run-Logged @(
        $installer.FullName,
        "/quiet",
        "InstallAllUsers=1",
        "PrependPath=1",
        "Include_pip=1",
        "Include_launcher=1",
        "InstallLauncherAllUsers=1",
        "AssociateFiles=1",
        "Include_tcltk=1",
        "Include_test=0",
        "Shortcuts=1"
    )

    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $python = Get-PythonCommand
    if (-not $python) {
        throw "Python installer completed but Python $TargetPythonMajorMinor is still not available."
    }
    Write-Step ("Python installed: {0} ({1})" -f $python.Executable, $python.Version)
    return $python
}

function Assert-WheelhouseReady {
    if (-not (Test-Path $Requirements)) {
        throw "Missing requirements file: $Requirements"
    }
    if (-not (Test-Path $Wheelhouse)) {
        throw "Missing wheelhouse directory: $Wheelhouse"
    }
    $wheels = Get-ChildItem -Path $Wheelhouse -Filter "*.whl" -ErrorAction SilentlyContinue
    if (-not $wheels) {
        throw "Wheelhouse is empty. Run build_bundle.bat on an internet-connected machine first."
    }
    Write-Step ("Wheelhouse contains {0} wheel(s)." -f $wheels.Count)
}

function Install-PythonPackages($Python) {
    Assert-WheelhouseReady
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    if (-not (Test-Path (Join-Path $SharedVenv "Scripts\python.exe"))) {
        Run-Logged @($Python.Executable, "-m", "venv", $SharedVenv)
    }
    $venvPython = Join-Path $SharedVenv "Scripts\python.exe"
    $cmd = @(
        $venvPython,
        "-m", "pip", "install",
        "--no-index",
        "--find-links", $Wheelhouse,
        "-r", $Requirements
    )
    Run-Logged $cmd
    Write-Step ("Shared Python environment ready: {0}" -f $SharedVenv)
}

function Install-Ffmpeg {
    if (-not (Test-Path (Join-Path $FfmpegBin "ffmpeg.exe"))) {
        Write-Step "Bundled FFmpeg not found. Skipping FFmpeg install."
        return
    }

    New-Item -ItemType Directory -Force -Path $InstallFfmpegBin | Out-Null
    Copy-Item -Path (Join-Path $FfmpegBin "*") -Destination $InstallFfmpegBin -Recurse -Force
    Write-Step ("FFmpeg copied to {0}" -f $InstallFfmpegBin)

    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    if (($machinePath -split ";") -notcontains $InstallFfmpegBin) {
        [Environment]::SetEnvironmentVariable("Path", ($machinePath.TrimEnd(";") + ";" + $InstallFfmpegBin), "Machine")
        Write-Step "FFmpeg path added to the machine PATH."
    } else {
        Write-Step "FFmpeg path is already present in the machine PATH."
    }
    $env:Path = $InstallFfmpegBin + ";" + $env:Path
    & (Join-Path $InstallFfmpegBin "ffmpeg.exe") -version 2>&1 | Select-Object -First 1 | Tee-Object -FilePath $LogPath -Append
}

function Install-AppFiles {
    New-Item -ItemType Directory -Force -Path $AppInstallRoot | Out-Null

    $dirs = @(
        "auth_util",
        "client",
        "common",
        "launcher_ui",
        "server",
        "ui"
    )
    foreach ($dir in $dirs) {
        $source = Join-Path $ProjectRoot $dir
        if (-not (Test-Path $source)) {
            Write-Step ("Skipping missing app directory: {0}" -f $source)
            continue
        }
        $dest = Join-Path $AppInstallRoot $dir
        if (Test-Path $dest) {
            Remove-Item -LiteralPath $dest -Recurse -Force
        }
        Copy-Item -LiteralPath $source -Destination $dest -Recurse -Force
    }

    $files = @(
        "allowed_users.json",
        "auth_config.json",
        "client_cli.py",
        "client_launcher.py",
        "client_launcher_qt.py",
        "client_launcher_tk.py",
        "requirements.txt",
        "school_service.py",
        "server_cli.py",
        "server_launcher.py",
        "server_launcher_qt.py",
        "server_launcher_tk.py"
    )
    foreach ($file in $files) {
        $source = Join-Path $ProjectRoot $file
        if (Test-Path $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $AppInstallRoot $file) -Force
        }
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $AppInstallRoot "data") | Out-Null
    $serverDataSource = Join-Path $ProjectRoot "data\server"
    $serverDataDest = Join-Path $AppInstallRoot "data\server"
    New-Item -ItemType Directory -Force -Path $serverDataDest | Out-Null
    $serverPolicyFiles = @(
        "exam_policy.json",
        "incident_rules.json",
        "process_blacklist.txt",
        "process_definitions.json"
    )
    foreach ($file in $serverPolicyFiles) {
        $source = Join-Path $serverDataSource $file
        if (Test-Path $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $serverDataDest $file) -Force
        }
    }

    Write-Step ("Application files copied to {0}" -f $AppInstallRoot)
}

function Write-SharedLaunchers {
    New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
    $venvPython = Join-Path $SharedVenv "Scripts\python.exe"
    $launchers = @{
        "run_server_tk.bat" = @("server_launcher.py", "--ui", "tk")
        "run_server_qt.bat" = @("server_launcher.py", "--ui", "qt")
        "run_client_tk.bat" = @("client_launcher.py", "--ui", "tk")
        "run_client_qt.bat" = @("client_launcher.py", "--ui", "qt")
    }
    foreach ($name in $launchers.Keys) {
        $parts = $launchers[$name]
        $script = $parts[0]
        $args = ($parts[1..($parts.Count - 1)] -join " ")
        $content = @"
@echo off
cd /d "$AppInstallRoot"
"$venvPython" "$AppInstallRoot\$script" $args
pause
"@
        Set-Content -Path (Join-Path $LauncherDir $name) -Value $content -Encoding ASCII
    }
    Write-Step ("Shared launchers written to {0}" -f $LauncherDir)
}

function Set-SharedPermissions {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

    $usersReadExecute = "*S-1-5-32-545:(OI)(CI)RX"
    $usersModify = "*S-1-5-32-545:(OI)(CI)M"
    $readExecutePaths = @(
        $AppInstallRoot,
        $SharedVenv,
        $InstallFfmpegBin,
        $LauncherDir
    )
    foreach ($path in $readExecutePaths) {
        if (Test-Path $path) {
            Run-Logged @("icacls", $path, "/grant", $usersReadExecute, "/T")
        }
    }

    $dataDir = Join-Path $AppInstallRoot "data"
    if (Test-Path $dataDir) {
        Run-Logged @("icacls", $dataDir, "/grant", $usersModify, "/T")
    }
}

try {
    Write-Step "Starting offline setup."
    Write-Step ("Bundle root: {0}" -f $BundleRoot)
    Write-Step ("Project root: {0}" -f $ProjectRoot)
    Assert-Administrator
    Assert-BundleManifest
    $python = Install-BundledPythonIfNeeded
    Install-PythonPackages $python
    Install-Ffmpeg
    Install-AppFiles
    Write-SharedLaunchers
    Set-SharedPermissions
    Write-Step "Offline setup completed successfully."
    Write-Host ""
    Write-Host "Offline setup completed successfully." -ForegroundColor Green
    exit 0
} catch {
    Write-Step ("ERROR: {0}" -f $_.Exception.Message)
    Write-Host ""
    Write-Host ("Offline setup failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host ("Log: {0}" -f $LogPath)
    exit 1
}
