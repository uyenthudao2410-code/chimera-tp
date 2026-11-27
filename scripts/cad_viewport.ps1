param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$ProgId,
    [Parameter(Mandatory)][int]$OwnerPid,
    [Parameter(Mandatory)][int]$Arms,
    [Parameter(Mandatory)][double]$Seconds,
    [string]$SecondaryDisplay
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

$script:secondary = $null
if ($SecondaryDisplay) {
    Add-Type -Path (Join-Path $PSScriptRoot 'CadSecondaryDisplay.cs') -ReferencedAssemblies System.Drawing,System.Windows.Forms
    $script:secondary = New-Object CadSecondaryDisplay($SecondaryDisplay)
}

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

function Invoke-CadWhenReady([scriptblock]$Call) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        try { return (& $Call) } catch {
            $hr = $_.Exception.GetBaseException().HResult
            if ($hr -notin @(-2147418111, -2147417846) -or $clock.Elapsed.TotalSeconds -ge 35) { throw }
            Assert-Owner
            Start-Sleep -Milliseconds 160
        }
    }
}

function Wait-Signal([string]$Name) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (!(Test-Path -LiteralPath (Join-Path $runRoot $Name))) {
        Assert-Owner
        if ($Name -like 'arm-*.go' -and (Test-Path -LiteralPath (Join-Path $runRoot 'finish'))) { return $false }
        if ($timer.Elapsed.TotalSeconds -gt 160) { throw "Timed out awaiting $Name" }
        Start-Sleep -Milliseconds 25
    }
    return $true
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
    Invoke-CadWhenReady { $script:acad.ZoomWindow($lo, $hi) }
}

function Invoke-Sweep([double]$Duration) {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $changes = 0
    $foregroundMisses = 0
    $exposureMisses = 0
    $missStart = $null
    $elapsedObscured = 0.0
    $started = Qpc-Ms
    while ($clock.Elapsed.TotalSeconds -lt $Duration) {
        $t = $clock.Elapsed.TotalSeconds
        $foreground = [CadProbeWindow]::GetForegroundWindow()
        $front = $foreground -eq $script:window
        if (-not $front) { $foregroundMisses++ }
        if ($null -ne $script:secondary) {
            if (-not $script:secondary.Contained($script:window)) { throw 'AutoCAD left the secondary display' }
            $exposed = $script:secondary.Exposed($script:window)
        } else {
            $exposed = $front -and -not [CadProbeWindow]::IsIconic($script:window)
        }
        if (-not $exposed) {
            $exposureMisses++
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
             foreground_misses=$foregroundMisses; exposure_misses=$exposureMisses; obscured_s=$elapsedObscured}
}

$before = @(Get-Process -Name acad -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$owned = $false
$doc = $null
$exitCode = 0
try {
    $script:acad = New-Object -ComObject $ProgId
    # COM can return before the main window exists. PID 0 at this point is Idle.
    $waitForWindow = [Diagnostics.Stopwatch]::StartNew()
    do {
        Assert-Owner
        $script:window = [IntPtr]([long](Invoke-CadWhenReady { $script:acad.HWND }))
        [uint32]$cadProcess = 0
        if ($script:window -ne [IntPtr]::Zero) {
            [void][CadProbeWindow]::GetWindowThreadProcessId($script:window, [ref]$cadProcess)
        }
        if ($cadProcess) {
            $process = Get-Process -Id $cadProcess -ErrorAction SilentlyContinue
            if ($null -ne $process -and $process.ProcessName -eq 'acad') { break }
        }
        Start-Sleep -Milliseconds 150
    } while ($waitForWindow.Elapsed.TotalSeconds -lt 45)
    if ($cadProcess -eq 0 -or $before -contains $cadProcess -or $null -eq $process -or $process.ProcessName -ne 'acad') {
        throw "Expected a new isolated acad.exe, got PID $cadProcess, HWND $($script:window), previous PIDs [$($before -join ',')]"
    }
    $owned = $true
    $startup = @(Invoke-CadWhenReady { $script:acad.Documents | Where-Object { $_.Saved -and [int]$_.GetVariable('DBMOD') -eq 0 } | ForEach-Object { $_.FullName } })
    if ($null -ne $script:secondary) {
        $script:secondary.Place($script:window, $true)
    } else {
        $script:acad.Visible = $true
    }
    # Document.Open may return before the COM document has a FullName. Open once,
    # then bind only to the requested read-only member of this new instance.
    Invoke-CadWhenReady { [void]$script:acad.Documents.Open($drawing, $true) }
    $loading = [Diagnostics.Stopwatch]::StartNew()
    do {
        Assert-Owner
        $active = Invoke-CadWhenReady { $script:acad.ActiveDocument }
        $full = Invoke-CadWhenReady { $active.FullName }
        if ($full -and [IO.Path]::GetFullPath($full) -eq $drawing -and (Invoke-CadWhenReady { $active.ReadOnly })) {
            $doc = $active
            break
        }
        Start-Sleep -Milliseconds 200
    } while ($loading.Elapsed.TotalSeconds -lt 40)
    if ($null -eq $doc) { throw "Dedicated CAD did not finish loading the requested read-only drawing (active: $full)" }
    if ($null -ne $script:secondary) {
        $script:secondary.Place($script:window, $true)
    } else {
        $doc.Activate()
        [void][CadProbeWindow]::ShowWindow($script:window, 3)
        [void][CadProbeWindow]::SetForegroundWindow($script:window)
    }
    Invoke-CadWhenReady { $doc.ActiveSpace = 1 }
    Invoke-CadWhenReady { $script:acad.ZoomExtents() }
    $min = Invoke-CadWhenReady { ,$doc.GetVariable('EXTMIN') }
    $max = Invoke-CadWhenReady { ,$doc.GetVariable('EXTMAX') }
    $script:width = [double]$max[0] - [double]$min[0]
    $script:height = [double]$max[1] - [double]$min[1]
    if ($script:width -le 0 -or $script:height -le 0 -or
        [Math]::Max($script:width, $script:height) -gt 1.0e15) { throw 'Invalid model-space extents' }
    $script:middleX = [double]$min[0] + $script:width / 2
    $script:middleY = [double]$min[1] + $script:height / 2
    $script:viewZ = [double]$min[2]
    $bounds = $null
    if ($null -ne $script:secondary) {
        $bounds = $script:secondary.Bounds
        if (-not $script:secondary.Exposed($script:window)) { throw 'Secondary viewport is not exposed' }
    }
    $warm = Invoke-Sweep 2.0
    Write-Marker 'ready.json' @{pid=$cadProcess; drawing=$doc.FullName; version=$script:acad.Version;
                                width=$script:width; height=$script:height; warmup=$warm; display=$SecondaryDisplay; bounds=$bounds}
    for ($i=0; $i -lt $Arms; $i++) {
        if (!(Wait-Signal "arm-$i.go")) { break }
        if ((Invoke-CadWhenReady { $script:acad.ActiveDocument.FullName }) -ne $drawing) { throw 'The active document changed' }
        $run = Invoke-Sweep $Seconds
        Write-Marker "arm-$i.done.json" $run
    }
    [void](Wait-Signal 'finish')
} catch {
    Write-Marker 'error.json' @{message=$_.Exception.Message; line=$_.InvocationInfo.ScriptLineNumber}
    $exitCode = 1
} finally {
    if ($owned) {
        if ($null -ne $doc) { try { $doc.Close($false); Start-Sleep -Milliseconds 350 } catch { } }
        # Quit our instance only while it contains exclusively unmodified, untitled startup drawings.
        try {
            $other = @($script:acad.Documents | Where-Object {
                $startup -notcontains $_.FullName -or -not $_.Saved -or [int]$_.GetVariable('DBMOD') -ne 0
            })
            if ($other.Count -eq 0) { $script:acad.Quit() }
        } catch { }
    }
}
exit $exitCode
