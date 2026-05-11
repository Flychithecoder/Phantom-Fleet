$paths = @(
    "$env:APPDATA\discord",
    "$env:APPDATA\discordcanary",
    "$env:APPDATA\discordptb",
    "$env:LOCALAPPDATA\Discord",
    "$env:LOCALAPPDATA\DiscordCanary",
    "$env:LOCALAPPDATA\DiscordPTB",
    "$env:APPDATA\BetterDiscord",
    "$env:LOCALAPPDATA\Programs\DiscordChatExporter",
    "$env:LOCALAPPDATA\Programs\DiscordChatExporter.CLI"
)

Write-Host "===== Discord install paths ====="
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "FOUND: $p"
    }
}

Write-Host ""
Write-Host "===== Discord leveldb (user token + cache) ====="
$leveldb = "$env:APPDATA\discord\Local Storage\leveldb"
if (Test-Path $leveldb) {
    Get-ChildItem $leveldb -File -Force | Select-Object -First 10 | ForEach-Object {
        Write-Host "  $($_.Length) bytes - $($_.Name)"
    }
}

Write-Host ""
Write-Host "===== Discord currently running? ====="
$procs = Get-Process 'discord*' -ErrorAction SilentlyContinue
if ($procs) {
    $procs | ForEach-Object { Write-Host "  PID $($_.Id) - $($_.Name)" }
} else {
    Write-Host "  (not running)"
}

Write-Host ""
Write-Host "===== Recent Discord cache write ====="
$cache = "$env:APPDATA\discord\Cache"
if (Test-Path $cache) {
    $recent = Get-ChildItem $cache -File -Recurse -Force -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3
    foreach ($r in $recent) {
        Write-Host "  $($r.LastWriteTime) - $($r.Name)"
    }
}

Write-Host ""
Write-Host "===== Looking for existing export tools ====="
$tools = @(
    "$env:USERPROFILE\Desktop",
    "$env:USERPROFILE\Downloads",
    "$env:LOCALAPPDATA\Programs",
    "$env:USERPROFILE\Documents"
)
foreach ($t in $tools) {
    if (Test-Path $t) {
        $matches = Get-ChildItem $t -Recurse -Force -Depth 3 -ErrorAction SilentlyContinue -Filter "DiscordChatExporter*" | Select-Object -First 3
        foreach ($m in $matches) {
            Write-Host "  FOUND: $($m.FullName)"
        }
    }
}

Write-Host ""
Write-Host "===== dotnet available? (needed for DCE) ====="
$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if ($dotnet) {
    Write-Host "  dotnet: $($dotnet.Source)"
    & dotnet --version 2>&1 | ForEach-Object { Write-Host "  version: $_" }
} else {
    Write-Host "  dotnet: NOT INSTALLED"
}
