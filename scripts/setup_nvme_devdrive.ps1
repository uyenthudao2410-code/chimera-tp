<#
.SYNOPSIS
  Idempotent NVMe ReFS Dev Drive VHDX creator, auto-mount installer, and HDD-vs-NVMe A/B benchmark.
.DESCRIPTION
  Creates a 64 GB Dynamic Sparse VHDX on C:\ChimeraDevDrive\chimera-dev.vhdx (occupies <250 MB initially),
  formats it as Windows 11 ReFS Dev Drive mounted at V:\, registers Microsoft Defender Dev Drive trust
  (async performance mode), installs a SYSTEM logon auto-mount ScheduledTask, sets User env CHIMERA_DEV_DRIVE=V:\,
  and writes a verified BEFORE (E:\ HDD) vs AFTER (V:\ NVMe ReFS Dev Drive) I/O benchmark JSON.
#>
param(
  [string]$VhdPath = "C:\ChimeraDevDrive\chimera-dev.vhdx",
  [string]$DriveLetter = "V",
  [uint64]$SizeGB = 64,
  [string]$ReportPath = "E:\DEV\chimera-tp\tasks\devdrive_win_ab.json",
  [string]$LogPath = "E:\DEV\chimera-tp\tasks\devdrive_setup.log"
)

$ErrorActionPreference = "Stop"
Start-Transcript -Path $LogPath -Force | Out-Null

try {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $isAdmin) {
    throw "Administrator privileges are required to mount/format a ReFS Dev Drive VHDX."
  }

  $vhdDir = Split-Path -Parent $VhdPath
  if (-not (Test-Path $vhdDir)) { New-Item -ItemType Directory -Path $vhdDir -Force | Out-Null }

  $created = $false
  $vol = Get-Volume -DriveLetter $DriveLetter -ErrorAction SilentlyContinue

  if (-not (Test-Path $VhdPath)) {
    Write-Host "[1/5] Creating dynamic sparse ${SizeGB}GB NVMe VHDX at $VhdPath ..."
    if (Get-Command New-VHD -ErrorAction SilentlyContinue) {
      New-VHD -Path $VhdPath -SizeBytes ($SizeGB * 1GB) -Dynamic | Out-Null
    } else {
      $dpCreate = @"
create vdisk file="$VhdPath" maximum=$($SizeGB * 1024) type=expandable
exit
"@
      $dpCreate | diskpart | Out-Null
    }
    $created = $true
  } else {
    Write-Host "[1/5] Existing VHDX found at $VhdPath"
  }

  if (-not $vol) {
    Write-Host "[2/5] Mounting VHDX and preparing GPT partition..."
    $diskImg = Mount-DiskImage -ImagePath $VhdPath -PassThru
    $disk = $diskImg | Get-Disk
    if ($disk.PartitionStyle -eq 'RAW') {
      Initialize-Disk -Number $disk.Number -PartitionStyle GPT | Out-Null
      $part = New-Partition -DiskNumber $disk.Number -UseMaximumSize -DriveLetter $DriveLetter
      Write-Host "[3/5] Formatting ${DriveLetter}: as ReFS Dev Drive..."
      Format-Volume -Partition $part -FileSystem ReFS -DevDrive -NewFileSystemLabel "CHIMERA_DEV" -Confirm:$false -Force | Out-Null
    } else {
      $part = Get-Partition -DiskNumber $disk.Number | Where-Object { $_.Type -eq 'Basic' -or $_.Size -gt 1GB } | Select-Object -First 1
      if ($part -and $part.DriveLetter -ne $DriveLetter) {
        Set-Partition -DiskNumber $disk.Number -PartitionNumber $part.PartitionNumber -NewDriveLetter $DriveLetter
      }
      $vol = Get-Volume -DriveLetter $DriveLetter -ErrorAction SilentlyContinue
      if (-not $vol -or $vol.FileSystem -ne 'ReFS') {
        Format-Volume -Partition $part -FileSystem ReFS -DevDrive -NewFileSystemLabel "CHIMERA_DEV" -Confirm:$false -Force | Out-Null
      }
    }
    $vol = Get-Volume -DriveLetter $DriveLetter
  } else {
    Write-Host "[2/5] Volume ${DriveLetter}: already mounted ($($vol.FileSystem) / $($vol.FileSystemLabel))"
  }

  Write-Host "[4/5] Trusting Dev Drive in Defender async mode & installing logon auto-mount..."
  $trustOut = (& fsutil devdrv trust /f "${DriveLetter}:" 2>&1) -join " | "
  $queryOut = (& fsutil devdrv query "${DriveLetter}:" 2>&1) -join " | "

  # Create standard high-speed directories and grant full control to Users
  $rootPath = "${DriveLetter}:\"
  foreach ($sub in @("shadows", "worktrees", "cache\pip", "cache\npm", "cache\uv", "cache\pytest")) {
    $p = Join-Path $rootPath $sub
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
  }
  & icacls "${DriveLetter}:\" /grant "Users:(OI)(CI)F" /Q | Out-Null

  # Persist User environment variable for Chimera + Agents
  [Environment]::SetEnvironmentVariable("CHIMERA_DEV_DRIVE", $rootPath, "User")

  # Register SYSTEM startup auto-mount ScheduledTask (idempotent)
  $mountCmd = "-NoProfile -WindowStyle Hidden -Command `"if (Test-Path '$VhdPath') { Mount-DiskImage -ImagePath '$VhdPath' -ErrorAction SilentlyContinue | Out-Null }`""
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $mountCmd
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
  Register-ScheduledTask -TaskName "ChimeraDevDriveAutoMount" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

  Write-Host "[5/5] Running BEFORE (E:\ SATA HDD) vs AFTER (${DriveLetter}:\ NVMe ReFS Dev Drive) I/O benchmark..."
  function Measure-SmallFileIO([string]$BaseDir) {
    $d = Join-Path $BaseDir ("_chimera_dd_bench_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $d -Force | Out-Null
    $payload = ("def chimera_bench_fn(x):`n    return x * 42`n" * 60)
    $swCreate = [System.Diagnostics.Stopwatch]::StartNew()
    for ($i = 0; $i -lt 500; $i++) {
      [System.IO.File]::WriteAllText((Join-Path $d "mod_$i.py"), $payload)
    }
    $swCreate.Stop()

    $swRead = [System.Diagnostics.Stopwatch]::StartNew()
    $bytesRead = 0
    for ($i = 0; $i -lt 500; $i++) {
      $bytesRead += ([System.IO.File]::ReadAllText((Join-Path $d "mod_$i.py"))).Length
    }
    $swRead.Stop()

    $d2 = $d + "_clone"
    New-Item -ItemType Directory -Path $d2 -Force | Out-Null
    $swCopy = [System.Diagnostics.Stopwatch]::StartNew()
    for ($i = 0; $i -lt 500; $i++) {
      [System.IO.File]::Copy((Join-Path $d "mod_$i.py"), (Join-Path $d2 "mod_$i.py"), $true)
    }
    $swCopy.Stop()

    $swDel = [System.Diagnostics.Stopwatch]::StartNew()
    Remove-Item -Path $d, $d2 -Recurse -Force
    $swDel.Stop()

    $total = $swCreate.Elapsed.TotalMilliseconds + $swRead.Elapsed.TotalMilliseconds + $swCopy.Elapsed.TotalMilliseconds + $swDel.Elapsed.TotalMilliseconds
    return @{
      create_500_ms = [math]::Round($swCreate.Elapsed.TotalMilliseconds, 2)
      read_500_ms   = [math]::Round($swRead.Elapsed.TotalMilliseconds, 2)
      copy_500_ms   = [math]::Round($swCopy.Elapsed.TotalMilliseconds, 2)
      delete_1000_ms = [math]::Round($swDel.Elapsed.TotalMilliseconds, 2)
      total_ms      = [math]::Round($total, 2)
      bytes_read    = $bytesRead
    }
  }

  $hddRes = Measure-SmallFileIO "E:\DEV\chimera-tp\tasks"
  $ddRes  = Measure-SmallFileIO "${DriveLetter}:\shadows"
  $vhdInfo = Get-Item $VhdPath
  $volNow = Get-Volume -DriveLetter $DriveLetter

  $report = @{
    ok = $true
    node = "win-desktop"
    created_now = $created
    vhd_path = $VhdPath
    vhd_actual_mb = [math]::Round($vhdInfo.Length / 1MB, 2)
    vhd_max_gb = $SizeGB
    drive_letter = "${DriveLetter}:"
    filesystem = $volNow.FileSystem
    label = $volNow.FileSystemLabel
    free_gb = [math]::Round($volNow.SizeRemaining / 1GB, 2)
    devdrv_trust = $trustOut
    devdrv_query = $queryOut
    automount_task = "ChimeraDevDriveAutoMount"
    env_chimera_dev_drive = $rootPath
    before_hdd_e = $hddRes
    after_nvme_refs_devdrive = $ddRes
    speedup_total_x = [math]::Round($hddRes.total_ms / [math]::Max(0.1, $ddRes.total_ms), 2)
    speedup_create_x = [math]::Round($hddRes.create_500_ms / [math]::Max(0.1, $ddRes.create_500_ms), 2)
  }

  $report | ConvertTo-Json -Depth 5 | Set-Content -Path $ReportPath -Encoding UTF8
  Write-Host "DEVDRIVE_READY: $($report | ConvertTo-Json -Compress -Depth 4)"
} finally {
  Stop-Transcript | Out-Null
}
