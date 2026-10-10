// The release WinExe entry point. No PowerShell, compiler, SDK or installed Python is used.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Nerfed {
    internal static class Program {
        const string Version = "0.5.3-port.4";
        [STAThread]
        static int Main(string[] args) {
            string temporary = null, temporaryParent = null, temporaryName = null;
            bool temporaryCreated = false;
            var saved = new Dictionary<string, string>();
            int code = 1;
            try {
                // A WinExe has no console code page. Explicit writers also preserve UTF-8 when
                // tests/CLI launchers provide redirected standard handles.
                try {
                    Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
                    Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
                } catch (IOException) { }
                bool demo = false, smoke = false, selfTest = false, runtimeOnly = false;
                string render = "", page = ""; int width = 0; double scale = 1;
                for (int i = 0; i < args.Length; i++) {
                    switch (args[i]) {
                        case "--demo": demo = true; break;
                        case "--smoke-test": demo = true; smoke = true; break;
                        case "--self-test": demo = true; selfTest = true; break;
                        case "--render": render = Value(args, ref i); demo = true; break;
                        case "--render-detail": page = "detail"; break;
                        case "--render-settings": page = "settings"; break;
                        case "--render-width": width = Int32.Parse(Value(args, ref i), CultureInfo.InvariantCulture); break;
                        case "--render-scale": scale = Double.Parse(Value(args, ref i), CultureInfo.InvariantCulture); break;
                        case "--check-runtime": runtimeOnly = true; break;
                        case "--version": Console.WriteLine("IsGPTNerfed " + Version); return 0;
                        case "--help": Console.WriteLine("IsGPTNerfed.exe [--demo | --smoke-test | --self-test | --check-runtime | --version | --render FILE [--render-detail | --render-settings] [--render-width 380..1200] [--render-scale 0.5..3]]"); return 0;
                        default: throw new ArgumentException("Unknown argument: " + args[i]);
                    }
                }
                if (width != 0 && (width < 380 || width > 1200)) throw new ArgumentException("Render width must be 380..1200.");
                if (Double.IsNaN(scale) || scale < .5 || scale > 3) throw new ArgumentException("Render scale must be 0.5..3.");
                if (page.Length > 0 && render.Length == 0) throw new ArgumentException("--render-detail and --render-settings require --render FILE.");
                string root = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
                if (demo) {
                    temporaryParent = Path.GetFullPath(Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    temporaryName = "nerfed-native-" + Guid.NewGuid().ToString("N"); temporary = Path.GetFullPath(Path.Combine(temporaryParent, temporaryName));
                    if (Directory.Exists(temporary) || File.Exists(temporary)) throw new IOException("Temporary state collision.");
                    Directory.CreateDirectory(temporary);
                    temporaryCreated = true;
                    foreach (string key in new[] { "CODEX_HOME", "NERFED_HOME", "NERFED_NO_UPDATE_CHECK" }) saved[key] = Environment.GetEnvironmentVariable(key);
                    Environment.SetEnvironmentVariable("CODEX_HOME", Path.Combine(temporary, "codex-home"));
                    Environment.SetEnvironmentVariable("NERFED_HOME", Path.Combine(temporary, "ledger"));
                    Environment.SetEnvironmentVariable("NERFED_NO_UPDATE_CHECK", "1");
                }
                string python = FindPython(root);
                if (runtimeOnly) { Console.WriteLine(python); code = 0; }
                else code = RunPanel(python, root, demo, smoke, selfTest, render, page, width, scale);
            } catch (Exception error) {
                Console.Error.WriteLine(error.ToString()); code = 1;
                if (args.Length == 0) StartupError(error);
            } finally {
                foreach (var item in saved) Environment.SetEnvironmentVariable(item.Key, item.Value);
                if (temporaryCreated) {
                    try {
                        string target = Path.GetFullPath(temporary);
                        if (!String.Equals(Path.GetDirectoryName(target).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar), temporaryParent, StringComparison.OrdinalIgnoreCase) || Path.GetFileName(target) != temporaryName || !System.Text.RegularExpressions.Regex.IsMatch(temporaryName, "^nerfed-native-[0-9a-f]{32}$")) throw new IOException("Refusing unexpected temporary cleanup target.");
                        if (Directory.Exists(target)) {
                            if ((File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0) throw new IOException("Refusing to recursively clean a reparse point.");
                            Directory.Delete(target, true);
                        }
                    } catch (Exception cleanup) { Console.Error.WriteLine(cleanup.ToString()); code = 1; }
                }
            }
            return code;
        }
        static string Value(string[] args, ref int index) { if (++index >= args.Length || String.IsNullOrWhiteSpace(args[index])) throw new ArgumentException("Missing argument value."); return args[index]; }
        // Keep Panel loading behind the catch boundary, including a missing/broken DLL.
        [MethodImpl(MethodImplOptions.NoInlining)]
        static int RunPanel(string python, string root, bool demo, bool smoke, bool selfTest, string render, string page, int width, double scale) {
            return NativePanel.Run(python, root, demo, smoke, selfTest, render, page, width, scale);
        }
        static void StartupError(Exception error) {
            string detail = error.Message; if (detail.Length > 1200) detail = detail.Substring(0, 1200) + "...";
            MessageBox.Show("Unable to start is-gpt-nerfed.\r\n\r\n" + detail + "\r\n\r\nExtract the complete portable ZIP, including IsGPTNerfed.Panel.dll and runtime.\r\nRun IsGPTNerfed.exe --smoke-test in a terminal for full details.", "is-gpt-nerfed - startup error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        static string FindPython(string root) {
            var candidates = new List<string[]> { new[] { Path.Combine(root, "runtime", "python.exe") } };
            string configured = Environment.GetEnvironmentVariable("NERFED_PYTHON"); if (!String.IsNullOrWhiteSpace(configured)) candidates.Add(new[] { configured });
            foreach (string name in new[] { "py.exe", "python.exe", "python3.exe" }) {
                string path = FindOnPath(name); if (path != null) candidates.Add(name == "py.exe" ? new[] { path, "-3" } : new[] { path });
            }
            foreach (string[] candidate in candidates) {
                if (!File.Exists(candidate[0]) || candidate[0].IndexOf("\\Microsoft\\WindowsApps\\", StringComparison.OrdinalIgnoreCase) >= 0) continue;
                try {
                    var arguments = candidate.Skip(1).Concat(new[] { "-X", "utf8", "-c", "import sys; assert sys.version_info >= (3, 10); print(sys.executable)" });
                    var start = new ProcessStartInfo(candidate[0], String.Join(" ", arguments.Select(Quote))) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
                    using (var process = Process.Start(start)) {
                        Task<string> stdout = process.StandardOutput.ReadToEndAsync(), stderr = process.StandardError.ReadToEndAsync();
                        if (!process.WaitForExit(15000)) { try { process.Kill(); } catch { } continue; }
                        Task.WaitAll(new Task[] { stdout, stderr }, 3000);
                        if (process.ExitCode == 0 && stdout.IsCompleted && File.Exists(stdout.Result.Trim())) return stdout.Result.Trim();
                    }
                } catch (Exception) { }
            }
            throw new FileNotFoundException("Python runtime is unavailable. Re-extract runtime/python.exe from the portable ZIP, or set NERFED_PYTHON to Python 3.10+.");
        }
        static string FindOnPath(string name) {
            foreach (string directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator)) {
                try { string path = Path.Combine(directory.Trim('"'), name); if (File.Exists(path)) return path; } catch (ArgumentException) { }
            }
            return null;
        }
        static string Quote(string value) {
            if (value.Length > 0 && !value.Any(c => Char.IsWhiteSpace(c) || c == '"')) return value;
            var result = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) { if (c == '\\') { slashes++; continue; } if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); } else { result.Append('\\', slashes); result.Append(c); } slashes = 0; }
            result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
        }
    }
}
