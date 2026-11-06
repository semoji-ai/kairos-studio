# Codex CLI · Claude Code CLI 자동 업데이트 (Windows 작업 스케줄러에서 하루 한 번 실행).
#
# 카이로스 스튜디오는 모델 이름을 앱에 박지 않는다 — Codex는 자기 기본 모델을, Claude는
# 별칭 "opus"(최신 Opus)를 쓴다. 그래서 CLI만 최신으로 두면 새 모델이 나와도 앱을 다시
# 빌드하지 않고 따라간다. 이 스크립트가 그 CLI를 최신으로 유지한다.
#
# 등록: powershell -ExecutionPolicy Bypass -File scripts\update-ai-clis.ps1 -Register
# 수동 실행: powershell -ExecutionPolicy Bypass -File scripts\update-ai-clis.ps1
# 기록: %LOCALAPPDATA%\KairosStudio\cli-update.log
#
# Git Bash에서 돌리면 Codex 설치 스크립트가 Git의 tar를 잡아 C: 경로를 못 읽는다 —
# 반드시 PowerShell로 실행한다.
param([switch]$Register)

$TaskName = "KairosStudio AI CLI Update"
$LogDir = Join-Path $env:LOCALAPPDATA "KairosStudio"
$Log = Join-Path $LogDir "cli-update.log"

if ($Register) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    $triggers = @(
        (New-ScheduledTaskTrigger -Daily -At "07:30"),
        (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
    )
    # 꺼져 있어 놓친 날은 켜지는 대로, 배터리여도 실행
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Description "카이로스 스튜디오: Codex·Claude CLI를 최신으로 유지" -Force | Out-Null
    Write-Host "등록됨: $TaskName (매일 07:30, 로그온 시)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
function Write-Log([string]$msg) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg | Out-File -Append -Encoding utf8 $Log
}
function Get-Ver([string]$cmd) {
    try { (& $cmd --version 2>$null | Select-Object -First 1) } catch { "없음" }
}

Write-Log "---- 업데이트 시작"

# Codex — 독립 설치본(앱이 쓰는 것)
if (Get-Command codex -ErrorAction SilentlyContinue) {
    $before = Get-Ver codex
    $env:CODEX_NON_INTERACTIVE = "1"
    $out = (& codex update 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE  # --version 이 덮어쓰기 전에
    $after = Get-Ver codex
    Write-Log "codex: $before -> $after"
    if ($code -ne 0) { Write-Log "codex update 실패 (앱이 쓰는 중이면 다음 실행에 다시 시도): $out" }
} else {
    Write-Log "codex: 설치되어 있지 않음 — 건너뜀"
}

# Claude Code
if (Get-Command claude -ErrorAction SilentlyContinue) {
    $before = Get-Ver claude
    $out = (& claude update 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
    $after = Get-Ver claude
    Write-Log "claude: $before -> $after"
    if ($code -ne 0) { Write-Log "claude update 실패: $out" }
} else {
    Write-Log "claude: 설치되어 있지 않음 — 건너뜀"
}

Write-Log "---- 끝"
