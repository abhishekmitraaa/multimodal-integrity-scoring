# OS-level keystroke injection (SendInput) for the keycheck page. SYNTHETIC input, development only.
# Safety: before every event, the foreground window title must start with $TitlePrefix; otherwise abort.
# Plan file: JSON array of {t: ms from start, vk: int, up: bool}.
param([string]$PlanFile, [string]$TitlePrefix = "Coding Practice Study")

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class Inj {
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct INPUTUNION { [FieldOffset(0)] public KEYBDINPUT ki; [FieldOffset(0)] public MOUSEINPUT mi; }
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public INPUTUNION u; }
  [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public static string Title(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  public static bool Key(ushort vk, bool up) {
    var i = new INPUT { type = 1 };
    i.u.ki = new KEYBDINPUT { wVk = vk, wScan = (ushort)MapVirtualKey(vk, 0), dwFlags = up ? 2u : 0u };
    return SendInput(1, new[] { i }, Marshal.SizeOf(typeof(INPUT))) == 1;
  }
  public static bool Focus(IntPtr h) {
    var fg = GetForegroundWindow();
    uint a = GetWindowThreadProcessId(fg, IntPtr.Zero), me = GetCurrentThreadId();
    AttachThreadInput(me, a, true); ShowWindow(h, 9); bool ok = SetForegroundWindow(h); AttachThreadInput(me, a, false);
    return ok;
  }
}
"@

$target = Get-Process | Where-Object { $_.MainWindowTitle -like "$TitlePrefix*" } | Select-Object -First 1
if (-not $target) { Write-Output "ABORT no window titled '$TitlePrefix*'"; exit 3 }
[void][Inj]::Focus($target.MainWindowHandle)
Start-Sleep -Milliseconds 400
$plan = Get-Content -Raw $PlanFile | ConvertFrom-Json
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$sent = 0
foreach ($e in $plan) {
  while ($sw.Elapsed.TotalMilliseconds -lt ($e.t - 2)) { Start-Sleep -Milliseconds 1 }
  while ($sw.Elapsed.TotalMilliseconds -lt $e.t) { }
  $title = [Inj]::Title([Inj]::GetForegroundWindow())
  if (-not $title.StartsWith($TitlePrefix)) {
    # release anything we pressed before stopping
    foreach ($p in $plan) { if (-not $p.up) { [void][Inj]::Key([uint16]$p.vk, $true) } }
    Write-Output "ABORT foreground is '$title' after $sent events"; exit 4
  }
  if (-not [Inj]::Key([uint16]$e.vk, [bool]$e.up)) { Write-Output "ABORT SendInput failed after $sent events"; exit 5 }
  $sent++
}
Write-Output "OK sent $sent events in $([math]::Round($sw.Elapsed.TotalMilliseconds)) ms"
