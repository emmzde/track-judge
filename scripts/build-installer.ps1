param(
    [string]$IsccPath,
    [string]$PortableSourceDir
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$CacheRoot = Join-Path $ProjectRoot ".build-cache"
$DistRoot = Join-Path $ProjectRoot "dist"
$InstallerScript = Join-Path $ProjectRoot "packaging\trackjudge-installer.iss"
$InstallerOutput = Join-Path $DistRoot "TrackJudge-Setup-Windows-x64.exe"

$InnoVersion = "7.0.2"
$InnoBootstrapUrl = (
    "https://github.com/jrsoftware/issrc/releases/download/" +
    "is-7_0_2/innosetup-7.0.2-x64.exe"
)
$InnoBootstrap = Join-Path $CacheRoot "innosetup-$InnoVersion-x64.exe"
$InnoRoot = Join-Path $CacheRoot "inno-setup-$InnoVersion"

function Resolve-PortableSource {
    param([string]$ConfiguredPath)

    if ($ConfiguredPath) {
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }
    $Candidates = @(
        (Join-Path $CacheRoot "portable-dist\TrackJudge"),
        (Join-Path $DistRoot "TrackJudge-Windows-x64\TrackJudge")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath (Join-Path $Candidate "TrackJudge.exe")) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "Portable TrackJudge folder was not found. Build it before the installer."
}

function Resolve-Iscc {
    param([string]$ConfiguredPath)

    if ($ConfiguredPath) {
        return (Resolve-Path -LiteralPath $ConfiguredPath).Path
    }
    $Candidates = @(
        (Join-Path $InnoRoot "ISCC.exe"),
        (Join-Path ${env:ProgramFiles} "Inno Setup 7\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate)) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }

    New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $InnoBootstrap)) {
        Write-Host "Downloading the official Inno Setup $InnoVersion compiler"
        & curl.exe `
            --location `
            --fail `
            --retry 5 `
            --retry-all-errors `
            --output $InnoBootstrap `
            $InnoBootstrapUrl
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to download Inno Setup."
        }
    }

    $Signature = Get-AuthenticodeSignature -LiteralPath $InnoBootstrap
    if (
        $Signature.Status -ne "Valid" -or
        $Signature.SignerCertificate.Subject -notlike "*Pyrsys B.V.*"
    ) {
        throw "The Inno Setup bootstrap signature is not valid."
    }

    Write-Host "Installing the compiler into the project build cache"
    $CompilerInstall = Start-Process `
        -FilePath $InnoBootstrap `
        -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CURRENTUSER",
            "/NOICONS",
            "/DIR=`"$InnoRoot`""
        ) `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($CompilerInstall.ExitCode -ne 0) {
        throw "Inno Setup compiler installation failed."
    }
    $Compiler = Join-Path $InnoRoot "ISCC.exe"
    if (-not (Test-Path -LiteralPath $Compiler)) {
        throw "ISCC.exe was not installed."
    }
    return (Resolve-Path -LiteralPath $Compiler).Path
}

$PortableRoot = Resolve-PortableSource -ConfiguredPath $PortableSourceDir
$CompilerPath = Resolve-Iscc -ConfiguredPath $IsccPath
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null

$RequiredNoticeFiles = @(
    (Join-Path $PortableRoot "licenses\ffmpeg-LICENSE"),
    (Join-Path $PortableRoot "licenses\ffmpeg-README.txt")
)
foreach ($NoticeFile in $RequiredNoticeFiles) {
    if (-not (Test-Path -LiteralPath $NoticeFile -PathType Leaf)) {
        throw "Required FFmpeg notice is missing from the portable build: $NoticeFile"
    }
}

Write-Host "Building the TrackJudge installer"
& $CompilerPath `
    "/DProjectRoot=$ProjectRoot" `
    "/DPortableRoot=$PortableRoot" `
    "/DOutputRoot=$DistRoot" `
    $InstallerScript
if ($LASTEXITCODE -ne 0) {
    throw "Installer compilation failed."
}
if (-not (Test-Path -LiteralPath $InstallerOutput)) {
    throw "The installer was not created."
}

$InstallerHash = (
    Get-FileHash -LiteralPath $InstallerOutput -Algorithm SHA256
).Hash.ToLowerInvariant()
"$InstallerHash *$(Split-Path -Leaf $InstallerOutput)" |
    Set-Content -LiteralPath "$InstallerOutput.sha256" -Encoding ASCII

Write-Host ""
Write-Host "Installer ready:"
Write-Host "  $InstallerOutput"
Write-Host "  $InstallerOutput.sha256"
