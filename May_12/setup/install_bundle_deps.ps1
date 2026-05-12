param(
    [ValidateSet("client", "server")]
    [string]$Target
)

$ErrorActionPreference = "Stop"

$SetupRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$May12Root = Split-Path -Parent $SetupRoot
$TargetRoot = Join-Path $May12Root $Target
$Requirements = Join-Path $TargetRoot "requirements.txt"
$VenvDir = Join-Path $TargetRoot ".venv"
$Wheelhouse = Join-Path $SetupRoot "wheelhouse"

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

function Resolve-Python {
    $candidates = @(
        @("py", "-3.13"),
        @("py", "-3"),
        @("python")
    )
    foreach ($candidate in $candidates) {
        try {
            $args = @()
            if ($candidate.Count -gt 1) {
                $args = $candidate[1..($candidate.Count - 1)]
            }
            $version = & $candidate[0] @args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
            if ($LASTEXITCODE -eq 0 -and $version) {
                Write-Host ("Using Python {0} via {1}" -f $version, ($candidate -join " "))
                return $candidate
            }
        } catch {
            continue
        }
    }
    throw "Python was not found. Install Python first, or run the bundled installer from setup\installers."
}

if (-not (Test-Path $TargetRoot)) {
    throw "Target folder not found: $TargetRoot"
}
if (-not (Test-Path $Requirements)) {
    throw "Requirements file not found: $Requirements"
}

$python = Resolve-Python
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    Run-Step ($python + @("-m", "venv", $VenvDir))
}

$venvPython = Join-Path $VenvDir "Scripts\python.exe"
$pipArgs = @($venvPython, "-m", "pip", "install")
$wheels = @()
if (Test-Path $Wheelhouse) {
    $wheels = Get-ChildItem -Path $Wheelhouse -Filter "*.whl" -ErrorAction SilentlyContinue
}
if ($wheels.Count -gt 0) {
    $pipArgs += @("--no-index", "--find-links", $Wheelhouse)
} else {
    Write-Warning "Wheelhouse is missing or empty; pip will use configured package indexes."
}
$pipArgs += @("-r", $Requirements)

Run-Step $pipArgs
Run-Step @($venvPython, "-m", "pip", "check")

Write-Host ""
Write-Host ("{0} dependencies are ready in {1}" -f $Target, $VenvDir) -ForegroundColor Green
