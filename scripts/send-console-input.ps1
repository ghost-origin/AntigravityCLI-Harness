param(
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [string]$Text = '',
    [string]$TextBase64 = '',
    [string]$LogFile = '',
    [int]$EnterCount = 1,
    [int]$CharDelayMs = 0,
    [int]$EnterDelayMs = 180
)

$ErrorActionPreference = 'Continue'

if ($TextBase64) {
    $Text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextBase64))
}
if (-not $Text -and $EnterCount -le 0) {
    Write-Error 'Either -Text, -TextBase64, or -EnterCount > 0 must be provided.'
    exit 1
}

if (-not $LogFile) {
    $LogFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'logs\send_console_input.log'
}

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class ConsoleInject {
    public static int LastStage = 0;
    public static int LastError = 0;

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool AttachConsole(uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateFileW(string lpFileName, uint dwDesiredAccess, uint dwShareMode,
        IntPtr lpSecurityAttributes, uint dwCreationDisposition, uint dwFlagsAndAttributes, IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool WriteConsoleInputW(IntPtr hConsoleInput, INPUT_RECORD[] lpBuffer, uint nLength, out uint lpNumberOfEventsWritten);

    [StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
    public struct INPUT_RECORD {
        [FieldOffset(0)] public ushort EventType;
        [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct KEY_EVENT_RECORD {
        public int bKeyDown;
        public ushort wRepeatCount;
        public ushort wVirtualKeyCode;
        public ushort wVirtualScanCode;
        public char UnicodeChar;
        public uint dwControlKeyState;
    }

    static INPUT_RECORD Make(char c, bool down) {
        INPUT_RECORD r = new INPUT_RECORD();
        r.EventType = 1;
        r.KeyEvent.bKeyDown = down ? 1 : 0;
        r.KeyEvent.wRepeatCount = 1;
        r.KeyEvent.wVirtualKeyCode = (c == '\r') ? (ushort)0x0D : (ushort)0;
        r.KeyEvent.wVirtualScanCode = 0;
        r.KeyEvent.UnicodeChar = c;
        r.KeyEvent.dwControlKeyState = 0;
        return r;
    }

    public static bool Send(uint pid, string text, int enterCount, int charDelayMs, int enterDelayMs) {
        LastStage = 0;
        LastError = 0;
        FreeConsole();
        if (!AttachConsole(pid)) {
            LastStage = 1;
            LastError = Marshal.GetLastWin32Error();
            return false;
        }
        IntPtr handle = CreateFileW("CONIN$", 0xC0000000, 3, IntPtr.Zero, 3, 0, IntPtr.Zero);
        if (handle == IntPtr.Zero || handle == (IntPtr)(-1)) {
            LastStage = 2;
            LastError = Marshal.GetLastWin32Error();
            FreeConsole();
            return false;
        }
        bool ok = true;
        uint written;
        if (charDelayMs <= 0 && enterCount <= 1) {
            List<INPUT_RECORD> records = new List<INPUT_RECORD>();
            foreach (char c in text) {
                records.Add(Make(c, true));
                records.Add(Make(c, false));
            }
            if (enterCount == 1) {
                records.Add(Make('\r', true));
                records.Add(Make('\r', false));
            }
            ok = WriteConsoleInputW(handle, records.ToArray(), (uint)records.Count, out written);
        }
        else {
            foreach (char c in text) {
                INPUT_RECORD[] pair = new INPUT_RECORD[] { Make(c, true), Make(c, false) };
                ok = WriteConsoleInputW(handle, pair, 2, out written);
                if (!ok) break;
                if (charDelayMs > 0) System.Threading.Thread.Sleep(charDelayMs);
            }
            for (int i = 0; ok && i < enterCount; i++) {
                if (enterDelayMs > 0) System.Threading.Thread.Sleep(enterDelayMs);
                INPUT_RECORD[] cr = new INPUT_RECORD[] { Make('\r', true), Make('\r', false) };
                ok = WriteConsoleInputW(handle, cr, 2, out written);
            }
        }
        if (!ok) {
            LastStage = 3;
            LastError = Marshal.GetLastWin32Error();
        }
        CloseHandle(handle);
        FreeConsole();
        return ok;
    }
}
"@

$result = [ConsoleInject]::Send([uint32]$ProcessId, $Text, $EnterCount, $CharDelayMs, $EnterDelayMs)
$line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' pid=' + $ProcessId + ' ok=' + $result +
    ' stage=' + [ConsoleInject]::LastStage + ' err=' + [ConsoleInject]::LastError +
    ' enters=' + $EnterCount + ' text=' + $Text
$dir = Split-Path $LogFile -Parent
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
Add-Content -Path $LogFile -Value $line -Encoding UTF8
