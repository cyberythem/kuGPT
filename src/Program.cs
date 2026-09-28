using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using Microsoft.Win32;

namespace KuGPT
{
    public static class RuntimeState
    {
        public static readonly string DataDirectory = ResolveDataDirectory();
        public static readonly string PidFile = Path.Combine(DataDirectory, "kugpt.pid");
        public static readonly string PauseFile = Path.Combine(DataDirectory, "paused");
        public static bool IsPaused { get { return File.Exists(PauseFile); } }

        private static string ResolveDataDirectory()
        {
            string overridden = Environment.GetEnvironmentVariable("KUGPT_DATA_DIR");
            if (!String.IsNullOrWhiteSpace(overridden)) return Path.GetFullPath(overridden);
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "kuGPT");
        }
    }

    public static class Program
    {
        private const string Version = "0.1.0";

        public static int Main(string[] args)
        {
            string command = args.Length == 0 ? "help" : args[0].ToLowerInvariant();
            try
            {
                switch (command)
                {
                    case "run": return RunDaemon();
                    case "start": return StartDaemon();
                    case "stop": return StopDaemon(true);
                    case "restart": StopDaemon(false); return StartDaemon();
                    case "status": return ShowStatus();
                    case "pause": return Pause();
                    case "resume": return Resume();
                    case "install": return Install();
                    case "uninstall": return Uninstall();
                    case "doctor": return Doctor();
                    case "version":
                    case "--version": Console.WriteLine("kuGPT " + Version); return 0;
                    case "help":
                    case "--help":
                    case "-h": ShowHelp(); return 0;
                    default: Console.Error.WriteLine("Unknown command: " + command); ShowHelp(); return 2;
                }
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine("kuGPT: " + exception.Message);
                return 1;
            }
        }

        private static int RunDaemon()
        {
            Directory.CreateDirectory(RuntimeState.DataDirectory);
            int existing;
            if (TryReadPid(out existing) && IsProcessRunning(existing))
            {
                Console.Error.WriteLine("kuGPT is already running (PID " + existing + ").");
                return 1;
            }

            File.WriteAllText(RuntimeState.PidFile, Process.GetCurrentProcess().Id.ToString());
            try
            {
                using (KeyboardDaemon daemon = new KeyboardDaemon())
                {
                    daemon.Run();
                }
            }
            finally
            {
                TryDelete(RuntimeState.PidFile);
            }
            return 0;
        }

        private static int StartDaemon()
        {
            int pid;
            if (TryReadPid(out pid) && IsProcessRunning(pid))
            {
                Console.WriteLine("kuGPT is already running (PID " + pid + ").");
                return 0;
            }

            string executable = Assembly.GetExecutingAssembly().Location;
            ProcessStartInfo info = new ProcessStartInfo(executable, "run");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            Process process = Process.Start(info);
            System.Threading.Thread.Sleep(400);
            if (process.HasExited)
            {
                Console.Error.WriteLine("kuGPT failed to start.");
                return 1;
            }
            Console.WriteLine("kuGPT started locally (PID " + process.Id + ").");
            return 0;
        }

        private static int StopDaemon(bool report)
        {
            int pid;
            if (!TryReadPid(out pid) || !IsProcessRunning(pid))
            {
                TryDelete(RuntimeState.PidFile);
                if (report) Console.WriteLine("kuGPT is not running.");
                return 0;
            }

            Process.GetProcessById(pid).Kill();
            TryDelete(RuntimeState.PidFile);
            if (report) Console.WriteLine("kuGPT stopped.");
            return 0;
        }

        private static int ShowStatus()
        {
            int pid;
            bool running = TryReadPid(out pid) && IsProcessRunning(pid);
            Console.WriteLine("Status: " + (running ? "running" : "stopped"));
            if (running) Console.WriteLine("PID: " + pid);
            Console.WriteLine("Corrections: " + (RuntimeState.IsPaused ? "paused" : "active"));
            Console.WriteLine("Processing: local memory only");
            return running ? 0 : 1;
        }

        private static int Pause()
        {
            Directory.CreateDirectory(RuntimeState.DataDirectory);
            File.WriteAllText(RuntimeState.PauseFile, String.Empty);
            Console.WriteLine("kuGPT corrections paused.");
            return 0;
        }

        private static int Resume()
        {
            TryDelete(RuntimeState.PauseFile);
            Console.WriteLine("kuGPT corrections resumed.");
            return 0;
        }

        private static int Install()
        {
            Directory.CreateDirectory(RuntimeState.DataDirectory);
            string source = Assembly.GetExecutingAssembly().Location;
            string target = Path.Combine(RuntimeState.DataDirectory, "kugpt.exe");
            if (!String.Equals(Path.GetFullPath(source), Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase))
            {
                File.Copy(source, target, true);
            }

            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run"))
            {
                key.SetValue("kuGPT", "\"" + target + "\" run");
            }

            Console.WriteLine("kuGPT installed for this Windows user.");
            Console.WriteLine("It will start automatically when you sign in.");
            return StartExecutable(target);
        }

        private static int Uninstall()
        {
            StopDaemon(false);
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run", true))
            {
                if (key != null) key.DeleteValue("kuGPT", false);
            }
            TryDelete(RuntimeState.PauseFile);
            Console.WriteLine("kuGPT startup was removed and the daemon was stopped.");
            return 0;
        }

        private static int StartExecutable(string executable)
        {
            ProcessStartInfo info = new ProcessStartInfo(executable, "start");
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process process = Process.Start(info);
            process.WaitForExit();
            return process.ExitCode;
        }

        private static int Doctor()
        {
            bool windows = Environment.OSVersion.Platform == PlatformID.Win32NT;
            Console.WriteLine("Windows: " + (windows ? "ok" : "unsupported"));
            Console.WriteLine("Data directory: " + RuntimeState.DataDirectory);
            Console.WriteLine("Architecture: " + (Environment.Is64BitOperatingSystem ? "64-bit" : "32-bit"));
            Console.WriteLine("Password fields: standard Windows fields excluded");
            Console.WriteLine("Password managers: excluded");
            return windows ? 0 : 1;
        }

        private static bool TryReadPid(out int pid)
        {
            pid = 0;
            try
            {
                return File.Exists(RuntimeState.PidFile) && Int32.TryParse(File.ReadAllText(RuntimeState.PidFile), out pid);
            }
            catch { return false; }
        }

        private static bool IsProcessRunning(int pid)
        {
            try { return !Process.GetProcessById(pid).HasExited; }
            catch { return false; }
        }

        private static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch { }
        }

        private static void ShowHelp()
        {
            Console.WriteLine("kuGPT - private, local writing correction for Windows");
            Console.WriteLine();
            Console.WriteLine("  kugpt install     Install and start at sign-in");
            Console.WriteLine("  kugpt start       Start correcting");
            Console.WriteLine("  kugpt stop        Stop correcting");
            Console.WriteLine("  kugpt pause       Temporarily pause corrections");
            Console.WriteLine("  kugpt resume      Resume corrections");
            Console.WriteLine("  kugpt status      Show current status");
            Console.WriteLine("  kugpt doctor      Check this system");
            Console.WriteLine("  kugpt uninstall   Remove startup and stop");
            Console.WriteLine();
            Console.WriteLine("Undo the latest correction: Ctrl+Alt+Backspace");
        }
    }
}

