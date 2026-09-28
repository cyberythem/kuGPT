using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace KuGPT
{
    public sealed class KeyboardDaemon : IDisposable
    {
        private const int WhKeyboardLl = 13;
        private const int WmKeyDown = 0x0100;
        private const int WmKeyUp = 0x0101;
        private const int WmSysKeyDown = 0x0104;
        private const int WmSysKeyUp = 0x0105;
        private const uint LlkhfInjected = 0x10;
        private const int VkBack = 0x08;
        private const int VkReturn = 0x0D;
        private const int VkSpace = 0x20;
        private const int VkControl = 0x11;
        private const int VkMenu = 0x12;
        private const int VkLWin = 0x5B;
        private const int VkRWin = 0x5C;
        private const uint InputKeyboard = 1;
        private const uint KeyeventfKeyup = 0x0002;
        private const uint KeyeventfUnicode = 0x0004;
        private const int EmGetPasswordChar = 0x00D2;

        private readonly TextEngine engine = new TextEngine();
        private readonly LowLevelKeyboardProc callback;
        private readonly HashSet<int> swallowedKeys = new HashSet<int>();
        private readonly HashSet<string> excludedProcesses = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "1Password", "Bitwarden", "CredentialUIBroker", "KeePass", "KeePassXC", "LastPass", "LogonUI"
        };

        private IntPtr hook = IntPtr.Zero;
        private IntPtr lastWindow = IntPtr.Zero;
        private UndoRecord lastUndo;

        public KeyboardDaemon()
        {
            callback = HookCallback;
        }

        public void Run()
        {
            using (Process process = Process.GetCurrentProcess())
            using (ProcessModule module = process.MainModule)
            {
                hook = SetWindowsHookEx(WhKeyboardLl, callback, GetModuleHandle(module.ModuleName), 0);
            }

            if (hook == IntPtr.Zero)
            {
                throw new InvalidOperationException("Could not attach the Windows keyboard hook. Error " + Marshal.GetLastWin32Error() + ".");
            }

            NativeMessage message;
            while (GetMessage(out message, IntPtr.Zero, 0, 0) > 0)
            {
                TranslateMessage(ref message);
                DispatchMessage(ref message);
            }
        }

        public void Dispose()
        {
            if (hook != IntPtr.Zero)
            {
                UnhookWindowsHookEx(hook);
                hook = IntPtr.Zero;
            }
        }

        private IntPtr HookCallback(int code, IntPtr wParam, IntPtr lParam)
        {
            if (code < 0)
            {
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            KeyboardData data = (KeyboardData)Marshal.PtrToStructure(lParam, typeof(KeyboardData));
            if ((data.flags & LlkhfInjected) != 0)
            {
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            int message = wParam.ToInt32();
            int vk = (int)data.vkCode;
            bool isDown = message == WmKeyDown || message == WmSysKeyDown;
            bool isUp = message == WmKeyUp || message == WmSysKeyUp;

            if (isUp && swallowedKeys.Remove(vk))
            {
                return new IntPtr(1);
            }
            if (!isDown)
            {
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            IntPtr foreground = GetForegroundWindow();
            if (foreground != lastWindow)
            {
                lastWindow = foreground;
                engine.ResetContext();
                lastUndo = null;
            }

            if (RuntimeState.IsPaused || IsSensitiveTarget(foreground))
            {
                engine.ResetContext();
                lastUndo = null;
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            if (vk == VkBack && IsPressed(VkControl) && IsPressed(VkMenu))
            {
                if (lastUndo != null)
                {
                    swallowedKeys.Add(vk);
                    SendReplacement(lastUndo.Replacement.Length, lastUndo.Original);
                    lastUndo = null;
                    engine.ResetContext();
                    return new IntPtr(1);
                }
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            if (IsPressed(VkControl) || IsPressed(VkMenu) || IsPressed(VkLWin) || IsPressed(VkRWin))
            {
                engine.ResetContext();
                lastUndo = null;
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            if (vk == VkBack)
            {
                engine.Backspace();
                lastUndo = null;
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            BoundaryKind kind;
            char punctuation;
            if (TryGetBoundary(vk, out kind, out punctuation))
            {
                EditPlan plan = engine.CompleteBoundary(kind, punctuation);
                if (plan != null)
                {
                    swallowedKeys.Add(vk);
                    SendReplacement(plan.DeleteCount, plan.InsertText);
                    lastUndo = new UndoRecord(plan.OriginalText, plan.InsertText);
                    return new IntPtr(1);
                }
                lastUndo = null;
                return CallNextHookEx(hook, code, wParam, lParam);
            }

            char typed;
            if (TryTranslate(vk, data.scanCode, out typed))
            {
                engine.TypeCharacter(typed);
            }
            else if (!IsModifier(vk))
            {
                engine.ResetContext();
            }
            lastUndo = null;
            return CallNextHookEx(hook, code, wParam, lParam);
        }

        private bool IsSensitiveTarget(IntPtr foreground)
        {
            if (foreground == IntPtr.Zero) return true;

            uint processId;
            uint threadId = GetWindowThreadProcessId(foreground, out processId);
            try
            {
                using (Process process = Process.GetProcessById((int)processId))
                {
                    if (excludedProcesses.Contains(process.ProcessName)) return true;
                }
            }
            catch
            {
                return true;
            }

            GuiThreadInfo info = new GuiThreadInfo();
            info.cbSize = Marshal.SizeOf(typeof(GuiThreadInfo));
            if (GetGUIThreadInfo(threadId, ref info) && info.hwndFocus != IntPtr.Zero)
            {
                if (SendMessage(info.hwndFocus, EmGetPasswordChar, IntPtr.Zero, IntPtr.Zero) != IntPtr.Zero)
                {
                    return true;
                }
            }
            return false;
        }

        private static bool TryGetBoundary(int vk, out BoundaryKind kind, out char punctuation)
        {
            punctuation = '\0';
            if (vk == VkSpace)
            {
                kind = BoundaryKind.Space;
                return true;
            }
            if (vk == VkReturn)
            {
                kind = BoundaryKind.Enter;
                return true;
            }

            char value;
            if (TryTranslate(vk, 0, out value) && ".!?,;:".IndexOf(value) >= 0)
            {
                kind = BoundaryKind.Punctuation;
                punctuation = value;
                return true;
            }

            kind = BoundaryKind.Space;
            return false;
        }

        private static bool TryTranslate(int vk, uint scanCode, out char value)
        {
            byte[] state = new byte[256];
            StringBuilder buffer = new StringBuilder(8);
            value = '\0';
            if (!GetKeyboardState(state)) return false;

            IntPtr layout = GetKeyboardLayout(0);
            uint scan = scanCode == 0 ? MapVirtualKeyEx((uint)vk, 0, layout) : scanCode;
            int result = ToUnicodeEx((uint)vk, scan, state, buffer, buffer.Capacity, 0, layout);
            if (result != 1) return false;
            value = buffer[0];
            return !Char.IsControl(value);
        }

        private static void SendReplacement(int deleteCount, string text)
        {
            List<Input> inputs = new List<Input>();
            for (int index = 0; index < deleteCount; index++)
            {
                inputs.Add(VirtualKeyInput(VkBack, false));
                inputs.Add(VirtualKeyInput(VkBack, true));
            }

            foreach (char value in text)
            {
                if (value == '\r')
                {
                    inputs.Add(VirtualKeyInput(VkReturn, false));
                    inputs.Add(VirtualKeyInput(VkReturn, true));
                }
                else
                {
                    inputs.Add(UnicodeInput(value, false));
                    inputs.Add(UnicodeInput(value, true));
                }
            }

            if (inputs.Count > 0)
            {
                Input[] values = inputs.ToArray();
                SendInput((uint)values.Length, values, Marshal.SizeOf(typeof(Input)));
            }
        }

        private static Input VirtualKeyInput(int vk, bool keyUp)
        {
            Input input = new Input();
            input.type = InputKeyboard;
            input.union.keyboard.virtualKey = (ushort)vk;
            input.union.keyboard.flags = keyUp ? KeyeventfKeyup : 0;
            return input;
        }

        private static Input UnicodeInput(char value, bool keyUp)
        {
            Input input = new Input();
            input.type = InputKeyboard;
            input.union.keyboard.scanCode = value;
            input.union.keyboard.flags = KeyeventfUnicode | (keyUp ? KeyeventfKeyup : 0);
            return input;
        }

        private static bool IsPressed(int vk)
        {
            return (GetAsyncKeyState(vk) & 0x8000) != 0;
        }

        private static bool IsModifier(int vk)
        {
            return vk == 0x10 || vk == 0x11 || vk == 0x12 || vk == 0xA0 || vk == 0xA1 ||
                   vk == 0xA2 || vk == 0xA3 || vk == 0xA4 || vk == 0xA5;
        }

        private sealed class UndoRecord
        {
            public string Original { get; private set; }
            public string Replacement { get; private set; }

            public UndoRecord(string original, string replacement)
            {
                Original = original;
                Replacement = replacement;
            }
        }

        private delegate IntPtr LowLevelKeyboardProc(int code, IntPtr wParam, IntPtr lParam);

        [StructLayout(LayoutKind.Sequential)]
        private struct KeyboardData
        {
            public uint vkCode;
            public uint scanCode;
            public uint flags;
            public uint time;
            public IntPtr extraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeMessage
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam;
            public IntPtr lParam;
            public uint time;
            public int pointX;
            public int pointY;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct GuiThreadInfo
        {
            public int cbSize;
            public uint flags;
            public IntPtr hwndActive;
            public IntPtr hwndFocus;
            public IntPtr hwndCapture;
            public IntPtr hwndMenuOwner;
            public IntPtr hwndMoveSize;
            public IntPtr hwndCaret;
            public System.Drawing.Rectangle rcCaret;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct Input
        {
            public uint type;
            public InputUnion union;
        }

        [StructLayout(LayoutKind.Explicit)]
        private struct InputUnion
        {
            [FieldOffset(0)] public MouseInput mouse;
            [FieldOffset(0)] public KeyboardInput keyboard;
            [FieldOffset(0)] public HardwareInput hardware;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct MouseInput
        {
            public int dx; public int dy; public uint mouseData; public uint flags; public uint time; public IntPtr extraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct KeyboardInput
        {
            public ushort virtualKey; public ushort scanCode; public uint flags; public uint time; public IntPtr extraInfo;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct HardwareInput
        {
            public uint message; public ushort parameterLow; public ushort parameterHigh;
        }

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelKeyboardProc callback, IntPtr module, uint threadId);
        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool UnhookWindowsHookEx(IntPtr hook);
        [DllImport("user32.dll")]
        private static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wParam, IntPtr lParam);
        [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        private static extern IntPtr GetModuleHandle(string moduleName);
        [DllImport("user32.dll")]
        private static extern int GetMessage(out NativeMessage message, IntPtr window, uint min, uint max);
        [DllImport("user32.dll")]
        private static extern bool TranslateMessage(ref NativeMessage message);
        [DllImport("user32.dll")]
        private static extern IntPtr DispatchMessage(ref NativeMessage message);
        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
        [DllImport("user32.dll")]
        private static extern bool GetGUIThreadInfo(uint threadId, ref GuiThreadInfo info);
        [DllImport("user32.dll")]
        private static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
        [DllImport("user32.dll")]
        private static extern short GetAsyncKeyState(int virtualKey);
        [DllImport("user32.dll")]
        private static extern bool GetKeyboardState(byte[] state);
        [DllImport("user32.dll")]
        private static extern IntPtr GetKeyboardLayout(uint threadId);
        [DllImport("user32.dll")]
        private static extern uint MapVirtualKeyEx(uint code, uint mapType, IntPtr layout);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int ToUnicodeEx(uint virtualKey, uint scanCode, byte[] state, StringBuilder buffer, int capacity, uint flags, IntPtr layout);
        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint SendInput(uint count, Input[] inputs, int size);
    }
}

