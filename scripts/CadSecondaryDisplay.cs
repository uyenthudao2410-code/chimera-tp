using System;
using System.ComponentModel;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public sealed class CadSecondaryDisplay
{
    private const uint NoActivate = 0x0010;
    private const uint Show = 0x0040;
    private readonly string device;
    private readonly Rectangle bounds;
    private readonly Rectangle area;

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect { public int Left, Top, Right, Bottom; }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y,
        int width, int height, uint flags);

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr window, out Rect rect);
    [DllImport("user32.dll")]
    private static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")]
    private static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    private static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);

    public CadSecondaryDisplay(string deviceName)
    {
        if (SetThreadDpiAwarenessContext(new IntPtr(-4)) == IntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot use physical monitor coordinates");
        foreach (Screen screen in Screen.AllScreens)
        {
            if (screen.Primary || !String.Equals(screen.DeviceName, deviceName, StringComparison.OrdinalIgnoreCase))
                continue;
            device = screen.DeviceName;
            bounds = screen.Bounds;
            area = screen.WorkingArea;
            if (area.Width < 640 || area.Height < 480)
                throw new InvalidOperationException("Secondary monitor has too little working area");
            return;
        }
        throw new InvalidOperationException("Requested non-primary display is unavailable: " + deviceName);
    }

    public string Device { get { return device; } }
    public string Bounds { get { return bounds.ToString(); } }

    public void Place(IntPtr window, bool show)
    {
        // Leave room for invisible resizing borders. HWND_TOPMOST belongs exclusively
        // to this disposable CAD instance. SWP_NOACTIVATE preserves the user's input.
        const int margin = 12;
        if (!SetWindowPos(window, new IntPtr(-1), area.Left + margin, area.Top + margin,
                          area.Width - 2 * margin, area.Height - 2 * margin,
                          NoActivate | (show ? Show : 0)))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot place the CAD window");
        if (!Contained(window))
            throw new InvalidOperationException("CAD is not entirely on the requested secondary display");
    }

    public bool Contained(IntPtr window)
    {
        Rect r;
        if (!GetWindowRect(window, out r) || r.Right <= r.Left || r.Bottom <= r.Top)
            return false;
        var actual = Screen.FromHandle(window);
        return !actual.Primary && actual.DeviceName == device && actual.Bounds == bounds
            && bounds.Contains(Rectangle.FromLTRB(r.Left, r.Top, r.Right, r.Bottom));
    }

    public bool Exposed(IntPtr window)
    {
        if (!Contained(window) || IsIconic(window) || !IsWindowVisible(window))
            return false;
        Rect r;
        if (!GetWindowRect(window, out r))
            return false;
        // Check nine positions across the viewport. PresentMon independently checks
        // displayed frames and time coverage during the actual compiler overlap.
        for (int x = 1; x <= 3; x++)
        {
            for (int y = 1; y <= 3; y++)
            {
                var p = new Point(r.Left + (r.Right - r.Left) * x / 4,
                                  r.Top + (r.Bottom - r.Top) * y / 4);
                if (GetAncestor(WindowFromPoint(p), 2) != window)
                    return false;
            }
        }
        return true;
    }
}
