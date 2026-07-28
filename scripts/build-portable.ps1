param(
    [string]$Python = "python",
    [switch]$UseSystemFfmpeg,
    [string]$FfmpegSourceDir,
    [switch]$SkipArchive
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$CacheRoot = Join-Path $ProjectRoot ".build-cache"
$BuildVenv = Join-Path $CacheRoot "build-venv"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$DistRoot = Join-Path $ProjectRoot "dist"
$PortableDistRoot = if ($SkipArchive) {
    Join-Path $DistRoot "TrackJudge-Windows-x64"
}
else {
    Join-Path $CacheRoot "portable-dist"
}
$PyInstallerWorkRoot = Join-Path $CacheRoot "pyinstaller-work"
$PortableRoot = Join-Path $PortableDistRoot "TrackJudge"
$ToolsRoot = Join-Path $PortableRoot "tools"
$LicensesRoot = Join-Path $PortableRoot "licenses"
$AssetsRoot = Join-Path $PortableRoot "assets"

$YtDlpVersion = "2026.07.04"
$YtDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/download/$YtDlpVersion/yt-dlp.exe"
$YtDlpChecksumsUrl = "https://github.com/yt-dlp/yt-dlp/releases/download/$YtDlpVersion/SHA2-256SUMS"

$FfmpegVersion = "8.1.2"
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-$FfmpegVersion-essentials_build.zip"
$FfmpegSha256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
$FfmpegSize = 109728040

function Get-RemoteFile {
    param(
        [string]$Url,
        [string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Destination)) {
        Write-Host "Downloading $Url"
        if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
            & curl.exe --location --fail --retry 5 --retry-all-errors --output $Destination $Url
            if ($LASTEXITCODE -ne 0) {
                throw "Download failed: $Url"
            }
        }
        else {
            Invoke-WebRequest -Uri $Url -OutFile $Destination
        }
    }
}

function Complete-RemoteFile {
    param(
        [string]$Url,
        [string]$Destination,
        [long]$ExpectedSize
    )
    if (-not (Get-Command "curl.exe" -ErrorAction SilentlyContinue)) {
        return
    }
    while ((Get-Item -LiteralPath $Destination).Length -lt $ExpectedSize) {
        $Before = (Get-Item -LiteralPath $Destination).Length
        Write-Host "Resuming $Destination from byte $Before"
        & curl.exe --location --fail --retry 5 --retry-all-errors --continue-at - --output $Destination $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to resume download: $Url"
        }
        $After = (Get-Item -LiteralPath $Destination).Length
        if ($After -le $Before) {
            throw "Download made no progress: $Url"
        }
    }
    if ((Get-Item -LiteralPath $Destination).Length -ne $ExpectedSize) {
        throw "Unexpected file size for $Destination."
    }
}

function Assert-Sha256 {
    param(
        [string]$Path,
        [string]$Expected
    )
    $Actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $Actual."
    }
}

function Get-FfmpegNoticeFiles {
    param(
        [string]$Root
    )

    $Files = Get-ChildItem -LiteralPath $Root -Recurse -File
    $LicenseFile = $Files |
        Where-Object { $_.Name -eq "LICENSE" } |
        Select-Object -First 1
    $ReadmeFile = $Files |
        Where-Object { $_.Name -eq "README.txt" } |
        Select-Object -First 1

    if (-not $LicenseFile -or -not $ReadmeFile) {
        throw "FFmpeg LICENSE and README.txt are required for distributable builds."
    }

    $LicenseText = Get-Content -LiteralPath $LicenseFile.FullName -Raw
    $ReadmeText = Get-Content -LiteralPath $ReadmeFile.FullName -Raw
    if (
        $LicenseText -notmatch "GNU GENERAL PUBLIC LICENSE" -or
        $LicenseText -notmatch "Version 3" -or
        $ReadmeText -notmatch "FFmpeg"
    ) {
        throw "The supplied FFmpeg notice files do not describe the expected GPLv3 build."
    }

    return @($LicenseFile, $ReadmeFile)
}

function Invoke-WindowsApp {
    param(
        [string]$Path,
        [string[]]$Arguments
    )
    $QuotedArguments = $Arguments | ForEach-Object {
        '"' + $_.Replace('"', '\"') + '"'
    }
    $Process = Start-Process `
        -FilePath $Path `
        -ArgumentList ($QuotedArguments -join " ") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    return $Process.ExitCode
}

New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $BuildPython)) {
    Write-Host "Creating an isolated build environment"
    & $Python -m venv $BuildVenv
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the build environment."
    }
}

Write-Host "Installing portable build dependencies in the isolated environment"
& $BuildPython -m pip install --disable-pip-version-check "$ProjectRoot[build]"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install build dependencies."
}

$YtDlpPath = Join-Path $CacheRoot "yt-dlp-$YtDlpVersion.exe"
$YtDlpChecksumsPath = Join-Path $CacheRoot "yt-dlp-$YtDlpVersion-SHA2-256SUMS"
Get-RemoteFile -Url $YtDlpUrl -Destination $YtDlpPath
Get-RemoteFile -Url $YtDlpChecksumsUrl -Destination $YtDlpChecksumsPath
$YtDlpChecksumLine = Get-Content -LiteralPath $YtDlpChecksumsPath |
    Where-Object { $_ -match '\s\*?yt-dlp\.exe$' } |
    Select-Object -First 1
if (-not $YtDlpChecksumLine) {
    throw "yt-dlp.exe checksum was not found."
}
$YtDlpSha256 = ($YtDlpChecksumLine -split '\s+')[0]
Assert-Sha256 -Path $YtDlpPath -Expected $YtDlpSha256

if ($FfmpegSourceDir) {
    $ResolvedFfmpegSource = (Resolve-Path -LiteralPath $FfmpegSourceDir).Path
    Write-Host "Using supplied FFmpeg directory for this local rebuild"
    $FfmpegPath = Get-ChildItem -LiteralPath $ResolvedFfmpegSource -Recurse -Filter "ffmpeg.exe" |
        Select-Object -First 1 -ExpandProperty FullName
    $FfprobePath = Get-ChildItem -LiteralPath $ResolvedFfmpegSource -Recurse -Filter "ffprobe.exe" |
        Select-Object -First 1 -ExpandProperty FullName
    $FfmpegLicenseFiles = Get-FfmpegNoticeFiles -Root $ResolvedFfmpegSource
}
elseif ($UseSystemFfmpeg) {
    if (-not $SkipArchive) {
        throw "-UseSystemFfmpeg is only supported together with -SkipArchive."
    }
    Write-Host "Using locally installed FFmpeg for this verification build"
    $FfmpegPath = (Get-Command "ffmpeg.exe" -ErrorAction Stop).Source
    $FfprobePath = (Get-Command "ffprobe.exe" -ErrorAction Stop).Source
    $FfmpegLicenseFiles = @()
}
else {
    $FfmpegArchive = Join-Path $CacheRoot "ffmpeg-$FfmpegVersion-essentials_build.zip"
    $FfmpegExtracted = Join-Path $CacheRoot "ffmpeg-$FfmpegVersion"
    Get-RemoteFile -Url $FfmpegUrl -Destination $FfmpegArchive
    Complete-RemoteFile -Url $FfmpegUrl -Destination $FfmpegArchive -ExpectedSize $FfmpegSize
    Assert-Sha256 -Path $FfmpegArchive -Expected $FfmpegSha256
    if (-not (Test-Path -LiteralPath $FfmpegExtracted)) {
        Expand-Archive -LiteralPath $FfmpegArchive -DestinationPath $FfmpegExtracted
    }

    $FfmpegPath = Get-ChildItem -LiteralPath $FfmpegExtracted -Recurse -Filter "ffmpeg.exe" |
        Select-Object -First 1 -ExpandProperty FullName
    $FfprobePath = Get-ChildItem -LiteralPath $FfmpegExtracted -Recurse -Filter "ffprobe.exe" |
        Select-Object -First 1 -ExpandProperty FullName
    $FfmpegLicenseFiles = Get-FfmpegNoticeFiles -Root $FfmpegExtracted
}
if (-not $FfmpegPath -or -not $FfprobePath) {
    throw "FFmpeg executables were not found in the downloaded archive."
}

Write-Host "Building TrackJudge"
Push-Location $ProjectRoot
try {
    & $BuildPython -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $PortableDistRoot `
        --workpath $PyInstallerWorkRoot `
        "trackjudge.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LicensesRoot -Force | Out-Null
New-Item -ItemType Directory -Path $AssetsRoot -Force | Out-Null
Copy-Item -LiteralPath $YtDlpPath -Destination (Join-Path $ToolsRoot "yt-dlp.exe") -Force
Copy-Item -LiteralPath $FfmpegPath -Destination (Join-Path $ToolsRoot "ffmpeg.exe") -Force
Copy-Item -LiteralPath $FfprobePath -Destination (Join-Path $ToolsRoot "ffprobe.exe") -Force

foreach ($LicenseFile in $FfmpegLicenseFiles) {
    Copy-Item -LiteralPath $LicenseFile.FullName -Destination (
        Join-Path $LicensesRoot ("ffmpeg-" + $LicenseFile.Name)
    ) -Force
}
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination $PortableRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $PortableRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.md") -Destination $PortableRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\trackjudge-gui.png") -Destination $AssetsRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "assets\trackjudge-icon-v2.png") -Destination $AssetsRoot -Force

$Executable = Join-Path $PortableRoot "TrackJudge.exe"
$PortableVersionExit = Invoke-WindowsApp -Path $Executable -Arguments @("--headless", "--version")
if ($PortableVersionExit -ne 0) {
    throw "Portable executable smoke test failed."
}
$TrackJudgeVersionLine = (
    & $BuildPython -c "import trackjudge; print(f'trackjudge {trackjudge.__version__}')"
).Trim()
$GuiSmokeExit = Invoke-WindowsApp -Path $Executable -Arguments @("--gui-smoke-test")
if ($GuiSmokeExit -ne 0) {
    throw "Portable GUI smoke test failed."
}
$GuiPasteSmokeExit = Invoke-WindowsApp -Path $Executable -Arguments @("--gui-paste-smoke-test")
if ($GuiPasteSmokeExit -ne 0) {
    throw "Portable Ctrl+V smoke test failed."
}
$YtDlpVersionLine = (& (Join-Path $ToolsRoot "yt-dlp.exe") --version | Out-String).Trim()
$FfmpegVersionLine = (& (Join-Path $ToolsRoot "ffmpeg.exe") -version | Select-Object -First 1)
$PythonVersionLine = (& $BuildPython -c "import platform; print(platform.python_version())").Trim()
$PythonPackageLines = & $BuildPython -c "import importlib.metadata as m; print('\n'.join(f'{name}: {m.version(name)}' for name in ('numpy', 'scipy', 'rich', 'matplotlib', 'pyinstaller')))"
$BuildFlavor = if ($FfmpegSourceDir) {
    "Local rebuild (uses the supplied FFmpeg directory)"
}
elseif ($UseSystemFfmpeg) {
    "Local verification build (uses FFmpeg installed on the build machine)"
}
else {
    "Release build (uses pinned, checksum-verified external tools)"
}
@(
    "TrackJudge portable build"
    "Build type: $BuildFlavor"
    $TrackJudgeVersionLine
    "Python: $PythonVersionLine"
    $PythonPackageLines
    "yt-dlp standalone: $YtDlpVersionLine"
    $FfmpegVersionLine
) | Set-Content -LiteralPath (Join-Path $PortableRoot "BUILD_INFO.txt") -Encoding UTF8

Write-Host $TrackJudgeVersionLine
Write-Host $YtDlpVersionLine
Write-Host $FfmpegVersionLine

$SmokeRoot = Join-Path $CacheRoot "portable-smoke"
if (Test-Path -LiteralPath $SmokeRoot) {
    Remove-Item -LiteralPath $SmokeRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $SmokeRoot | Out-Null
$SmokeFull = Join-Path $SmokeRoot "full-spectrum.wav"
$SmokeLow = Join-Path $SmokeRoot "lowpass.wav"
$SmokeOutput = Join-Path $SmokeRoot "result"
& (Join-Path $ToolsRoot "ffmpeg.exe") `
    -y -v error -f lavfi `
    -i "anoisesrc=d=8:c=pink:r=48000:a=0.12:s=42" `
    -c:a pcm_s16le $SmokeFull
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create the portable smoke-test audio."
}
& (Join-Path $ToolsRoot "ffmpeg.exe") `
    -y -v error -i $SmokeFull `
    -af "lowpass=f=6000" `
    -c:a pcm_s16le $SmokeLow
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create the low-pass smoke-test audio."
}
$AudioSmokeExit = Invoke-WindowsApp -Path $Executable -Arguments @(
    "--headless",
    "--no-color",
    "--pause", "0",
    "--workers", "2",
    "--min-reliable-duration", "5",
    "--spectrogram",
    "--json-report",
    "--output", $SmokeOutput,
    $SmokeLow,
    $SmokeFull
)
if ($AudioSmokeExit -ne 0) {
    throw "Portable end-to-end smoke test failed."
}
if (-not (Test-Path -LiteralPath (Join-Path $SmokeOutput "trackjudge-report.json"))) {
    throw "Portable smoke test did not create trackjudge-report.json."
}
Write-Host "Portable end-to-end smoke test passed"
Remove-Item -LiteralPath $SmokeRoot -Recurse -Force

if ($SkipArchive) {
    Write-Host ""
    Write-Host "Working folder ready (archive was not rebuilt):"
    Write-Host "  $Executable"
}
else {
    $Archive = Join-Path $DistRoot "TrackJudge-Windows-x64.zip"
    Compress-Archive -Path $PortableRoot -DestinationPath $Archive -CompressionLevel Optimal -Force
    $ArchiveChecksum = "$Archive.sha256"
    $ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$ArchiveHash *$(Split-Path -Leaf $Archive)" |
        Set-Content -LiteralPath $ArchiveChecksum -Encoding ASCII
    Write-Host ""
    Write-Host "Portable build ready:"
    Write-Host "  $Executable"
    Write-Host "  $Archive"
    Write-Host "  $ArchiveChecksum"
}
