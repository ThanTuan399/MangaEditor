param(
    [ValidateRange(1, 65535)][int]$Port = 8080,
    [string]$Model = "tencent/Hy-MT2-1.8B-GGUF:Q4_K_M"
)

$ErrorActionPreference = "Stop"

function Find-LlamaServer {
    $command = Get-Command llama-server -ErrorAction SilentlyContinue
    if ($command -and $command.Source -and (Test-Path -LiteralPath $command.Source)) {
        return $command.Source
    }

    # WinGet portable ZIP installs can miss the command alias / PATH entry.
    $roots = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:ProgramFiles\WinGet\Packages"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $packages = Get-ChildItem -LiteralPath $root -Directory -Filter "ggml.llamacpp_*" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
        foreach ($package in $packages) {
            $server = Get-ChildItem -LiteralPath $package.FullName -Recurse -File -Filter "llama-server.exe" -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($server) { return $server.FullName }
        }
    }
    return $null
}

$serverPath = Find-LlamaServer
if (-not $serverPath) {
    Write-Error "llama-server.exe not found. Install it with: winget install llama.cpp"
    exit 1
}

Write-Host "Hy-MT2 local model: $Model"
Write-Host "Server URL: http://127.0.0.1:$Port"
Write-Host "Keep this window open while MangaEditor translates. Stop with Ctrl+C."
& $serverPath -hf $Model --port $Port
exit $LASTEXITCODE
