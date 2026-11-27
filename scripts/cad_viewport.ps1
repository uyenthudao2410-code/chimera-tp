param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$ProgId,
    [Parameter(Mandatory)][int]$OwnerPid,
    [Parameter(Mandatory)][int]$Arms,
    [Parameter(Mandatory)][double]$Seconds
)
$ErrorActionPreference = 'Stop'
$runRoot = (Resolve-Path -LiteralPath $RunDirectory).Path
$drawing = (Resolve-Path -LiteralPath (Join-Path $runRoot 'scene.dwg')).Path
if ($ProgId -notmatch '^AutoCAD\.Application(\.\d+(\.\d+)?)?$') { throw 'Expected an AutoCAD COM ProgID' }
$utf8 = New-Object System.Text.UTF8Encoding($false)

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CadProbeWindow {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int command);
}
'@

function Write-Marker([string]$Name, $Object) {
    $destination = Join-Path $runRoot $Name
    $tmp = $destination + '.tmp'
    [IO.File]::WriteAllText($tmp, ($Object | ConvertTo-Json -Compress -Depth 4), $utf8)
    [IO.File]::Move($tmp, $destination)
}

function Assert-Owner {
    if ((Test-Path -LiteralPath (Join-Path $runRoot 'stop')) -or
        $null -eq (Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue)) {
        throw 'Coordinator stopped'
    }
}

function Wait-Signal([string]$Name) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (!(Test-Path -LiteralPath (Join-Path $runRoot $Name))) {
        Assert-Owner
        if ($timer.Elapsed.TotalSeconds -gt 160) { throw "Timed out awaiting $Name" }
        Start-Sleep -Milliseconds 25
    }
}

function Qpc-Ms {
    return [Diagnostics.Stopwatch]::GetTimestamp() * 1000.0 / [Diagnostics.Stopwatch]::Frequency
}

function Invoke-Camera([double]$Phase) {
    $angle = [Math]::PI * 2 * $Phase
    $scale = 0.45 + 0.16 * [Math]::Cos(2 * $angle)
    $cx = $script:middleX + 0.16 * $script:width * [Math]::Sin($angle)
    $cy = $script:middleY + 0.13 * $script:height * [Math]::Cos($angle)
    $dx = $script:width * $scale / 2
    $dy = $script:height * $scale / 2
    [double[]]$lo = @(($cx - $dx), ($cy - $dy), $script:viewZ)
    [double[]]$hi = @(($cx + $dx), ($cy + $dy), $script:viewZ)
    $script:acad.ZoomWindow($lo, $hi)
}

function Invoke-Sweep([double]$Duration) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $changes = 0
    $foregroundMisses = 0
    $missStart = $null
    $elapsedObscured = 0.0
    $started = Qpc-Ms
    while ($clock.Elapsed.TotalSeconds -lt $Duration) {
        $t = $clock.Elapsed.TotalSeconds
        $foreground = [CadProbeWindow]::GetForegroundWindow()
        if ($foreground -ne $script:window -or [CadProbeWindow]::IsIconic($script:window)) {
            $foregroundMisses++
            if ($null -eq $missStart) { $missStart = $t }
        } elseif ($null -ne $missStart) {
            $elapsedObscured += $t - $missStart
            $missStart = $null
        }
        Invoke-Camera ($t / 6.0)
        $changes++
        if (($changes % 15) -eq 0) { Assert-Owner }
        $next = ([Math]::Floor($t * 60) + 1) / 60.0
        $waitMs = [int]([Math]::Floor(($next - $clock.Elapsed.TotalSeconds) * 1000))
        if ($waitMs -gt 0) { Start-Sleep -Milliseconds $waitMs }
    }
    if ($null -ne $missStart) { $elapsedObscured += $clock.Elapsed.TotalSeconds - $missStart }
    return @{from_qpc_ms=$started; until_qpc_ms=(Qpc-Ms); zoom_calls=$changes;
             foreground_misses=$foregroundMisses; obscured_s=$elapsedObscured}
}

$before = @(Get-Process -Name acad -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$owned = $false
$doc = $null
$exitCode = 0
try {
    $script:acad = New-Object -ComObject $ProgId
    $script:window = [IntPtr]([long]$script:acad.HWND)
    [uint32]$cadProcess = 0
    [void][CadProbeWindow]::GetWindowThreadProcessId($script:window, [ref]$cadProcess)
    $process = Get-Process -Id $cadProcess -ErrorAction Stop
    if ($script:window -eq [IntPtr]::Zero -or $before -contains $cadProcess -or $process.ProcessName -ne 'acad') {
        throw 'AutoCAD did not return a new, isolated instance'
    }
    $owned = $true
    $script:acad.Visible = $true
    $doc = $script:acad.Documents.Open($drawing, $true)
    if ([IO.Path]::GetFullPath($doc.FullName) -ne $drawing) { throw 'Unexpected active drawing' }
    $doc.Activate()
    [void][CadProbeWindow]::ShowWindow($script:window, 3)
    [void][CadProbeWindow]::SetForegroundWindow($script:window)
    $doc.ActiveSpace = 1
    $script:acad.ZoomExtents()
    $min = $doc.GetVariable('EXTMIN')
    $max = $doc.GetVariable('EXTMAX')
    $script:width = [double]$max[0] - [double]$min[0]
    $script:height = [double]$max[1] - [double]$min[1]
    if ($script:width -le 0 -or $script:height -le 0 -or
        [Math]::Max($script:width, $script:height) -gt 1.0e15) { throw 'Invalid model-space extents' }
    $script:middleX = [double]$min[0] + $script:width / 2
    $script:middleY = [double]$min[1] + $script:height / 2
    $script:viewZ = [double]$min[2]
    $warm = Invoke-Sweep 2.0
    Write-Marker 'ready.json' @{pid=$cadProcess; drawing=$doc.FullName; version=$script:acad.Version;
                                width=$script:width; height=$script:height; warmup=$warm}
    for ($i=0; $i -lt $Arms; $i++) {
        Wait-Signal "arm-$i.go"
        if ($script:acad.ActiveDocument.FullName -ne $drawing) { throw 'The active document changed' }
        $run = Invoke-Sweep $Seconds
        Write-Marker "arm-$i.done.json" $run
    }
    Wait-Signal 'finish'
} catch {
    Write-Marker 'error.json' @{message=$_.Exception.Message; line=$_.InvocationInfo.ScriptLineNumber}
    $exitCode = 1
} finally {
    if ($owned) {
        if ($null -ne $doc) { try { $doc.Close($false) } catch { } }
        # Quit our instance only while it contains exclusively unmodified, untitled startup drawings.
        try {
            $other = @($script:acad.Documents | Where-Object {
                -not [string]::IsNullOrEmpty($_.Path) -or [int]$_.GetVariable('DBMOD') -ne 0
            })
            if ($other.Count -eq 0) { $script:acad.Quit() }
        } catch { }
    }
}
exit $exitCode
