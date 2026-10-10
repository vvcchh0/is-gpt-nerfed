// Native Windows presentation only. Detection, scoring and persistence belong to nerfed.
// Compiled ahead of time for releases, or by the optional PowerShell source entry point.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using Forms = System.Windows.Forms;

namespace Nerfed {
    internal static class Json {
        internal static JavaScriptSerializer Serializer() { return new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 }; }
        internal static Dictionary<string, object> Parse(string text) { return Serializer().Deserialize<Dictionary<string, object>>(text); }
        internal static Dictionary<string, object> Map(object value) { return value as Dictionary<string, object> ?? new Dictionary<string, object>(); }
        internal static object Get(object value, string key) { object result; return Map(value).TryGetValue(key, out result) ? result : null; }
        internal static string S(object value, string key) { return Convert.ToString(Get(value, key), CultureInfo.InvariantCulture) ?? ""; }
        internal static bool B(object value, string key) { return Get(value, key) is bool && (bool)Get(value, key); }
        internal static int N(object value, string key) { try { return Convert.ToInt32(Get(value, key), CultureInfo.InvariantCulture); } catch { return 0; } }
        internal static double P(object value, string key) { try { return Convert.ToDouble(Get(value, key), CultureInfo.InvariantCulture); } catch { return 0; } }
        internal static IEnumerable<object> Items(object value) { var list = value as IEnumerable; return list == null || value is string ? new object[0] : list.Cast<object>(); }
        internal static string Encode(object value) { return Serializer().Serialize(value); }
    }

    internal sealed class Request {
        internal string Action, Target, Model, Effort;
        internal Dictionary<string, string> Settings;
        internal static readonly string[] SettingKeys = { "frequency", "fresh_frequency", "mode", "queries", "parallel", "passive", "notify", "notify_on_ok", "announce_ok", "sound", "hide_titles" };
        internal List<string[]> Commands(bool demo) {
            var commands = new List<string[]>();
            switch (Action) {
                case "snapshot": commands.Add(demo ? new[] { "snapshot", "--json", "--demo" } : new[] { "snapshot", "--json" }); break;
                case "doctor": commands.Add(new[] { "doctor" }); break;
                case "tick": commands.Add(new[] { "tick" }); break;
                case "probe": case "retry": commands.Add(new[] { "worker", "--thread", Target }); break;
                case "fresh": case "heartbeat":
                    var fresh = new List<string> { "probe", "fresh" };
                    if (Action == "fresh" && !String.IsNullOrWhiteSpace(Model)) { fresh.Add("--model"); fresh.Add(Model.Trim()); }
                    if (Action == "fresh" && !String.IsNullOrWhiteSpace(Effort)) { fresh.Add("--effort"); fresh.Add(Effort.Trim()); }
                    commands.Add(fresh.ToArray()); break;
                case "settings":
                    if (Settings == null || Settings.Keys.Any(k => !SettingKeys.Contains(k))) throw new ArgumentException("Unsupported panel setting.");
                    foreach (string key in SettingKeys) if (Settings.ContainsKey(key)) commands.Add(new[] { "config", "set", key, Settings[key] });
                    break;
                default: throw new ArgumentException("Unknown panel action: " + Action);
            }
            return commands;
        }
        internal bool Inference { get { return Action == "probe" || Action == "retry" || Action == "fresh" || Action == "heartbeat" || Action == "tick"; } }
    }
    internal sealed class Result {
        internal Request Request;
        internal bool Ok;
        internal string Output = "", Error = "";
        internal Dictionary<string, object> Snapshot;
    }
    internal interface ITransport : IDisposable {
        bool Submit(Request request, Action<Result> completed);
    }

    internal sealed class BackendTransport : ITransport {
        readonly string python, root, backend;
        readonly bool demo;
        readonly object gate = new object();
        readonly HashSet<Process> active = new HashSet<Process>();
        bool closed;
        internal BackendTransport(string python, string root, bool demo) {
            this.python = python; this.root = root; this.demo = demo;
            backend = System.IO.Path.Combine(root, "plugin", "skills", "is-gpt-nerfed", "scripts", "nerfed");
        }
        // Windows CommandLineToArgvW/CRT quoting, including trailing backslashes and quotes.
        internal static string Quote(string value) {
            value = value ?? "";
            if (value.Length > 0 && !value.Any(c => Char.IsWhiteSpace(c) || c == '"')) return value;
            var result = new StringBuilder("\""); int slashes = 0;
            foreach (char c in value) {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append('"'); }
                else { result.Append('\\', slashes); result.Append(c); }
                slashes = 0;
            }
            result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
        }
        public bool Submit(Request request, Action<Result> completed) {
            lock (gate) {
                if (closed) return false;
                if (demo && request.Inference) {
                    ThreadPool.QueueUserWorkItem(delegate { completed(new Result { Request = request, Error = "演示模式不会调用推理或调度器。" }); });
                    return true;
                }
                ThreadPool.QueueUserWorkItem(delegate {
                    var result = new Result { Request = request };
                    try {
                        var outputs = new List<string>();
                        foreach (string[] args in request.Commands(demo)) outputs.Add(Execute(args, request.Inference ? 1200 : request.Action == "doctor" ? 240 : 90));
                        result.Output = String.Join("\n", outputs).Trim();
                        if (request.Action == "snapshot") result.Snapshot = Json.Parse(result.Output);
                        result.Ok = true;
                    } catch (Exception error) { result.Error = error.Message; }
                    completed(result);
                });
                return true;
            }
        }
        string Execute(string[] args, int timeoutSeconds) {
            Process process;
            lock (gate) {
                // This lock covers the last shutdown check AND Process.Start. A queued settings
                // continuation can never start the next command after Dispose has returned.
                if (closed) throw new OperationCanceledException("面板正在退出。");
                var all = new List<string> { "-X", "utf8", backend }; all.AddRange(args);
                var info = new ProcessStartInfo(python, String.Join(" ", all.Select(Quote))) {
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = true,
                    StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                if (!info.EnvironmentVariables.ContainsKey("NERFED_NO_UPDATE_CHECK")) info.EnvironmentVariables["NERFED_NO_UPDATE_CHECK"] = "1";
                process = new Process { StartInfo = info };
                process.Start(); active.Add(process);
                process.StandardInput.Close();
            }
            try {
                // Both pipes drain concurrently on Tasks. Nothing waits on the WPF dispatcher.
                Task<string> stdout = process.StandardOutput.ReadToEndAsync();
                Task<string> stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(timeoutSeconds * 1000)) {
                    try { process.Kill(); } catch { }
                    process.WaitForExit(2000);
                    throw new TimeoutException("后端命令超时（" + timeoutSeconds + " 秒）：" + args[0]);
                }
                Task.WaitAll(new Task[] { stdout, stderr }, 5000);
                string output = stdout.IsCompleted ? stdout.Result : "";
                string errors = stderr.IsCompleted ? stderr.Result : "";
                if (process.ExitCode != 0) throw new InvalidOperationException((output + "\n" + errors).Trim().Length > 0 ? (output + "\n" + errors).Trim() : "后端退出码 " + process.ExitCode);
                return args[0] == "snapshot" ? output : (output + "\n" + errors).Trim();
            } finally {
                lock (gate) { active.Remove(process); }
                process.Dispose();
            }
        }
        public void Dispose() {
            lock (gate) {
                if (closed) return;
                closed = true;
                // Only processes started and still owned by this transport are touched.
                foreach (Process process in active) try { if (!process.HasExited) process.Kill(); } catch { }
            }
        }
    }

    internal static class Scheduler {
        internal static string Next(object snapshot, bool demo, bool busy, DateTime now, DateTime heartbeat, DateTime tick) {
            if (demo || busy) return null;
            object config = Json.Get(snapshot, "config");
            if (Json.S(config, "fresh_frequency") != "manual" && Json.B(snapshot, "fresh_due") && !Json.B(snapshot, "global_running") && (now - heartbeat).TotalSeconds > 300) return "heartbeat";
            if ((now - tick).TotalSeconds > 60 && Json.Items(Json.Get(snapshot, "threads")).Any(t => Json.B(t, "due") && Json.B(t, "active") && !Json.B(t, "probe_running") && !Json.B(t, "halted"))) return "tick";
            return null;
        }
    }

    public sealed class NativePanel {
        readonly string root, python;
        readonly bool demo, smoke, selfTest;
        readonly string renderPath, renderPage;
        readonly double renderScale;
        readonly int renderWidth;
        Window window;
        Grid surface;
        StackPanel header, body;
        ScrollViewer scroll;
        TextBlock activity, version;
        Button refreshButton, settingsButton, doctorButton, saveButton;
        ComboBox freshModel, freshEffort;
        Forms.NotifyIcon tray;
        System.Drawing.Icon trayIcon;
        readonly DispatcherTimer timer = new DispatcherTimer();
        ITransport transport;
        Dictionary<string, object> snapshot;
        readonly HashSet<string> pending = new HashSet<string>();
        readonly Dictionary<string, string> commandFailures = new Dictionary<string, string>();
        readonly Dictionary<string, Control> settings = new Dictionary<string, Control>();
        readonly Dictionary<string, string> draftOriginal = new Dictionary<string, string>();
        readonly Dictionary<string, string> demoOverrides = new Dictionary<string, string>();
        readonly Dictionary<string, Button> probeButtons = new Dictionary<string, Button>();
        string expanded, inferenceTarget, operation = "正在读取快照…", diagnosticOutput = "", modelDraft = "", effortDraft = "";
        string previousSignature, previousVerdict;
        bool settingsPage, closing, windowClosing, rendered, fakeInference, testStarted, mainStale;
        DateTime lastHeartbeat = DateTime.MinValue, lastTick = DateTime.MinValue;
        int exitCode;
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr handle);

        NativePanel(string python, string root, bool demo, bool smoke, bool selfTest, string renderPath, string page, int width, double scale) {
            this.python = python; this.root = root; this.demo = demo; this.smoke = smoke; this.selfTest = selfTest;
            this.renderPath = renderPath; renderPage = page; renderWidth = width; renderScale = scale;
            transport = new BackendTransport(python, root, demo);
        }
        public static int Run(string python, string root, bool demo, bool smoke, bool selfTest, string renderPath, string page, int width, double scale) {
            if (Thread.CurrentThread.GetApartmentState() != ApartmentState.STA) throw new InvalidOperationException("WPF requires an STA entry thread.");
            if (selfTest) TransportContracts.Run(python);
            var panel = new NativePanel(python, root, demo, smoke, selfTest, renderPath, page, width, scale);
            var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
            try { panel.BuildWindow(); app.Run(panel.window); return panel.exitCode; }
            finally { panel.Shutdown(); }
        }
        static Brush Color(string color) { var brush = new SolidColorBrush((System.Windows.Media.Color)ColorConverter.ConvertFromString(color)); brush.Freeze(); return brush; }
        static readonly Brush Ink = Color("#24272B"), Muted = Color("#747A82"), Faint = Color("#969BA2"), Red = Color("#ED4B55"), Orange = Color("#D58225"), Green = Color("#299A64");
        static TextBlock Text(string text, double size, Brush color, bool bold) {
            return new TextBlock { Text = text, FontSize = size, Foreground = color, FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 2, 0, 2) };
        }
        static Button Button(string text, Action action) {
            var button = new Button { Content = text, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Left };
            AutomationProperties.SetName(button, text);
            button.Click += delegate { action(); }; return button;
        }
        static Border Card(UIElement child) { return new Border { Background = Color("#F3F4F5"), CornerRadius = new CornerRadius(11), Padding = new Thickness(12, 10, 12, 10), Margin = new Thickness(0, 0, 0, 8), Child = child }; }
        void BuildWindow() {
            window = new Window { Title = "is-gpt-nerfed", Width = 520, Height = Math.Min(950, SystemParameters.WorkArea.Height * .92), MinWidth = 380, MinHeight = 560, Background = Brushes.White, WindowStartupLocation = WindowStartupLocation.CenterScreen, UseLayoutRounding = true, SnapsToDevicePixels = true };
            ResourceDictionary resources;
            using (Stream resource = typeof(NativePanel).Assembly.GetManifestResourceStream("Nerfed.Native.xaml")) {
                resources = resource == null ? new ResourceDictionary { Source = new Uri(System.IO.Path.Combine(root, "windows", "native.xaml"), UriKind.Absolute) } : (ResourceDictionary)System.Windows.Markup.XamlReader.Load(resource);
            }
            window.Resources.MergedDictionaries.Add(resources);
            try { window.Icon = FaceImage("ok"); } catch { }
            surface = new Grid { Background = Brushes.White, Margin = new Thickness(18, 10, 18, 10) };
            surface.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            surface.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            surface.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            header = new StackPanel { Margin = new Thickness(0, 3, 0, 12) }; surface.Children.Add(header);
            body = new StackPanel { Margin = new Thickness(0, 0, 8, 0) };
            scroll = new ScrollViewer { Content = body, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, CanContentScroll = false };
            Grid.SetRow(scroll, 1); surface.Children.Add(scroll);
            var footer = new StackPanel { Margin = new Thickness(0, 8, 0, 0) };
            activity = Text(operation, 11, Muted, false); activity.MaxHeight = 34; footer.Children.Add(activity);
            var controls = new DockPanel { Margin = new Thickness(0, 5, 0, 0), LastChildFill = true };
            var exit = Button("退出", Shutdown); DockPanel.SetDock(exit, Dock.Right); controls.Children.Add(exit);
            settingsButton = Button("设置", ToggleSettings); settingsButton.Margin = new Thickness(0, 0, 7, 0); controls.Children.Add(settingsButton);
            refreshButton = Button("刷新", delegate { Begin(new Request { Action = "snapshot" }); }); refreshButton.Margin = new Thickness(0, 0, 7, 0); controls.Children.Add(refreshButton);
            doctorButton = Button("诊断", delegate { Begin(new Request { Action = "doctor" }); }); doctorButton.Margin = new Thickness(0, 0, 7, 0); controls.Children.Add(doctorButton);
            version = Text("", 10, Faint, false); version.HorizontalAlignment = HorizontalAlignment.Right; version.VerticalAlignment = VerticalAlignment.Center; controls.Children.Add(version);
            footer.Children.Add(controls); Grid.SetRow(footer, 2); surface.Children.Add(footer); window.Content = surface;
            RenderHeader(); body.Children.Add(Text("正在读取近期会话…", 12, Muted, false));
            window.Loaded += delegate { Begin(new Request { Action = "snapshot" }); };
            window.Closing += delegate(object sender, System.ComponentModel.CancelEventArgs e) {
                if (!closing && tray != null) { e.Cancel = true; HideToTray(); }
                else { windowClosing = true; Shutdown(); }
            };
            window.PreviewKeyDown += delegate(object sender, KeyEventArgs e) {
                if (e.Key == Key.F5) { Begin(new Request { Action = "snapshot" }); e.Handled = true; }
                if (e.Key == Key.Escape && settingsPage) { ToggleSettings(); e.Handled = true; }
            };
            bool offline = smoke || selfTest || !String.IsNullOrEmpty(renderPath);
            if (offline) {
                window.ShowInTaskbar = false; window.Opacity = 0; window.Left = -20000; window.Top = -20000; window.WindowStartupLocation = WindowStartupLocation.Manual;
                window.Width = renderWidth > 0 ? renderWidth : 540;
                window.Height = renderPage == "detail" ? 1480 : renderPage == "settings" ? 1080 : 1120;
            } else { CreateTray(); }
            timer.Interval = TimeSpan.FromSeconds(8);
            timer.Tick += delegate { if (!closing) Begin(new Request { Action = "snapshot" }); };
            if (!offline) timer.Start();
        }
        string FacePath(string state) { return System.IO.Path.Combine(root, "macos", "Resources", "face-" + state + ".png"); }
        Stream FaceStream(string state) { return typeof(NativePanel).Assembly.GetManifestResourceStream("Nerfed.face-" + state + ".png") ?? File.OpenRead(FacePath(state)); }
        BitmapImage FaceImage(string state) {
            using (Stream stream = FaceStream(state)) {
                var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad; image.StreamSource = stream; image.EndInit(); image.Freeze(); return image;
            }
        }
        static string Ago(string value) {
            if (String.IsNullOrEmpty(value)) return "";
            if (value == "just now") return "刚刚";
            return value.Replace("s ago", " 秒前").Replace("m ago", " 分钟前").Replace("h ago", " 小时前").Replace("d ago", " 天前");
        }
        static bool PassiveAlert(object probe) {
            return Json.S(probe, "verdict_basis") == "passive" || Json.Items(Json.Get(probe, "passive_reasons")).Any() || Json.S(probe, "verdict") == "DOWNGRADED!";
        }
        static string PassiveKind(string kind) {
            if (kind.Contains("effort")) return "推理强度变化";
            if (kind.Contains("model")) return "模型标识变化";
            if (kind.Contains("context")) return "上下文变化";
            if (kind.Contains("tier")) return "服务等级变化";
            return "被动证据";
        }
        static string PassiveLabel(object probe) {
            var kinds = Json.Items(Json.Get(probe, "passive_reasons")).Select(e => PassiveKind(Json.S(e, "kind"))).Distinct().ToList();
            return kinds.Count > 1 ? "混合被动告警" : kinds.Count == 1 ? kinds[0] + "告警" : "被动变化告警";
        }
        static string FingerprintCode(object probe) {
            string value = Json.S(probe, "fingerprint_verdict"); return value.Length > 0 ? value : Json.S(probe, "verdict");
        }
        static bool FingerprintOverlap(object probe) { return Json.S(probe, "fingerprint_resolution") == "overlap" || FingerprintCode(probe) == "AMBIGUOUS"; }
        static string FingerprintVerdict(object probe) {
            if (probe == null || Json.Map(probe).Count == 0) return "尚未检测";
            if (Json.B(probe, "stale_account")) return "未验证";
            string verdict = FingerprintCode(probe);
            if (FingerprintOverlap(probe)) return "无法区分";
            if (verdict == "MISMATCH" && !PassiveAlert(probe) && Json.B(probe, "is_upgrade")) return "升配";
            if (verdict == "MISMATCH" && !PassiveAlert(probe) && Json.B(probe, "is_downgrade")) return "降配";
            switch (verdict) { case "MATCH": return "匹配"; case "MISMATCH": return "模型改道"; case "SUSPICIOUS": return "可疑"; case "INVALID": return "样本无效"; case "UNLISTED": return "未收录 · 不可归因"; case "DOWNGRADED!": return "未独立记录"; default: return Json.S(probe, "status") == "failed" ? "检测失败" : "等待结果"; }
        }
        static string Verdict(object probe) { return PassiveAlert(probe) && !Json.B(probe, "stale_account") ? PassiveLabel(probe) : FingerprintVerdict(probe); }
        static Brush FingerprintColor(object probe) {
            if (probe == null || Json.B(probe, "stale_account")) return Muted;
            if (FingerprintOverlap(probe)) return Muted;
            string verdict = FingerprintCode(probe);
            if (verdict == "MISMATCH" && !PassiveAlert(probe) && Json.B(probe, "is_downgrade")) return Red;
            if (verdict == "MATCH" || (verdict == "MISMATCH" && !PassiveAlert(probe) && Json.B(probe, "is_upgrade"))) return Green;
            if (verdict == "MISMATCH" || verdict == "SUSPICIOUS") return Orange;
            return Muted;
        }
        static Brush VerdictColor(object probe) { return PassiveAlert(probe) && !Json.B(probe, "stale_account") ? Red : FingerprintColor(probe); }
        static string Percent(object value) { try { return Math.Round(Convert.ToDouble(value, CultureInfo.InvariantCulture) * 100).ToString("0", CultureInfo.InvariantCulture) + "%"; } catch { return ""; } }
        static string ProbeDetail(object probe) {
            if (probe == null) return "";
            string detail = FingerprintOverlap(probe) ? "Astra / Sol 6.1 · 无法区分" : Json.S(probe, "prediction");
            if (Json.B(probe, "stale_account")) return "此前结果来自其他或未知账号 · " + Ago(Json.S(probe, "finished_ago"));
            if (!FingerprintOverlap(probe) && Json.S(probe, "fingerprint_resolution") != "unlisted" && FingerprintCode(probe) != "UNLISTED") {
                if (Json.Get(probe, "probability") != null) detail += " " + Percent(Json.Get(probe, "probability"));
                if (Json.S(probe, "expected") != Json.S(probe, "prediction") && Json.Get(probe, "p_expected") != null) detail += "，声明模型相似分 " + Percent(Json.Get(probe, "p_expected"));
            } else if (!FingerprintOverlap(probe)) detail = "";
            if (Json.N(probe, "used_outputs") < Json.N(probe, "queries")) detail += " · " + Json.N(probe, "used_outputs") + "/" + Json.N(probe, "queries") + " 份回答";
            if (Json.N(probe, "rounds") > 1) detail += " · " + Json.N(probe, "rounds") + " 轮检测";
            string ago = Ago(Json.S(probe, "finished_ago")); return detail + (ago.Length == 0 ? "" : " · " + ago);
        }
        static string FingerprintLine(object probe) {
            string detail = ProbeDetail(probe);
            return "指纹 · " + (FingerprintOverlap(probe) && !Json.B(probe, "stale_account") ? detail : FingerprintVerdict(probe) + (detail.Length > 0 ? " · " + detail : ""));
        }
        static string PassiveLine(object probe) {
            string time = Json.Items(Json.Get(probe, "passive_reasons")).Select(e => Json.S(e, "ts")).FirstOrDefault(t => t.Length > 0) ?? "";
            return "被动 · " + PassiveLabel(probe) + (time.Length > 0 ? " · " + time : "");
        }
        string HookLine(out bool attention) {
            attention = false; object hooks = Json.Get(snapshot, "hooks"), install = Json.Get(snapshot, "install");
            if (install != null && !Json.B(install, "codex_found")) { attention = true; return "未找到 Codex · 请先安装并打开 Codex，再点诊断。"; }
            if (install != null && !Json.B(install, "plugin_enabled")) { attention = true; return "插件尚未启用 · 在插件目录运行 install.ps1 后重启 Codex。"; }
            string state = Json.S(hooks, "state");
            if (state == "untrusted") { attention = true; return "Hooks 尚未信任 · 在终端运行 bin\\nerfed.cmd hooks trust，再刷新。"; }
            if (state == "missing") { attention = true; return "Codex 未列出插件 Hooks · 运行 install.ps1，再重启 Codex。"; }
            if (Json.N(hooks, "disabled") > 0) { attention = true; return "Hooks 已被关闭 · 请在 Codex 的 Hooks 页面启用。"; }
            if (state != "trusted" && Json.S(hooks, "error").Length > 0) { attention = true; return "无法核对 Hooks 状态 · 点诊断查看原因。"; }
            if (hooks != null && !Json.B(hooks, "desktop_loaded")) { attention = true; return "Codex 尚未加载插件 · 请完全退出并重新打开 Codex。"; }
            string ago = Ago(Json.S(snapshot, "hooks_last_event_ago"));
            return state == "trusted" ? "Hooks 已信任" + (ago.Length > 0 ? " · 最近回调 " + ago : " · 等待首次回调") : "尚无 Hook 回调 · 可运行诊断核对安装";
        }
        void RenderHeader() {
            header.Children.Clear();
            object overall = Json.Get(snapshot, "overall"); string state = Json.S(overall, "status");
            var image = new Image { Width = 62, Height = 62, Margin = new Thickness(0, 1, 0, 7), HorizontalAlignment = HorizontalAlignment.Center };
            try { image.Source = FaceImage(state == "alert" ? "alert" : state == "warn" ? "warn" : "ok"); header.Children.Add(image); } catch { header.Children.Add(Text("(•ᴗ•)", 28, Ink, true)); }
            int downgrade = Json.N(overall, "downgraded"), suspicious = Json.N(overall, "suspicious");
            string headline = snapshot == null ? "正在连接检测后端" : downgrade > 0 ? downgrade + " 个会话告警" : suspicious > 0 ? suspicious + " 个会话可疑" : Json.N(overall, "unverified") > 0 ? "有会话等待验证" : Json.N(overall, "running") > 0 ? "正在检测模型" : "未发现模型或设置异常";
            var title = Text(headline, 20, downgrade > 0 ? Red : suspicious > 0 ? Orange : Ink, true); title.TextAlignment = TextAlignment.Center; header.Children.Add(title);
            var counts = new List<string>();
            if (downgrade > 0 && suspicious > 0) counts.Add(suspicious + " 个可疑");
            if (Json.N(overall, "upgraded") > 0) counts.Add(Json.N(overall, "upgraded") + " 个升配");
            if (Json.N(overall, "unverified") > 0) counts.Add(Json.N(overall, "unverified") + " 个待验证");
            if (Json.N(overall, "running") > 0) counts.Add(Json.N(overall, "running") + " 个检测中");
            if (counts.Count > 0) { var text = Text(String.Join(" · ", counts), 12, Muted, false); text.TextAlignment = TextAlignment.Center; header.Children.Add(text); }
            object last = Json.Get(snapshot, "last_verdict");
            if (last != null) { var text = Text("上次检测 · " + Verdict(last) + " · " + Ago(Json.S(last, "finished_ago")), 11, Muted, false); text.TextAlignment = TextAlignment.Center; header.Children.Add(text); }
            if (snapshot != null) {
                bool attention; string hookLine = HookLine(out attention);
                var facts = new List<string>();
                if (!Json.B(Json.Get(snapshot, "config"), "hide_titles") && Json.S(Json.Get(snapshot, "account"), "label").Length > 0) facts.Add(Json.S(Json.Get(snapshot, "account"), "label"));
                if (!attention) facts.Add(hookLine);
                var text = Text(String.Join(" · ", facts), 10, Faint, false); text.TextAlignment = TextAlignment.Center; header.Children.Add(text);
                if (attention) { var warning = Text(hookLine, 11, Orange, false); warning.TextAlignment = TextAlignment.Center; header.Children.Add(warning); }
            }
        }
        static Grid Split(UIElement left, UIElement right) {
            var grid = new Grid(); grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.Children.Add(left); Grid.SetColumn(right, 1); grid.Children.Add(right); return grid;
        }
        void Section(string title, string trailing) {
            var right = Text(trailing, 11, Faint, false); right.HorizontalAlignment = HorizontalAlignment.Right;
            var section = Split(Text(title, 12, Muted, true), right); section.Margin = new Thickness(2, 6, 2, 7); body.Children.Add(section);
        }
        string SessionTitle(object row, int index) {
            if (Json.B(Json.Get(snapshot, "config"), "hide_titles")) return "会话 " + (index + 1);
            string title = Json.S(row, "title");
            if (demo) {
                var titles = new Dictionary<string, string> { { "payments", "重构支付回调" }, { "ci-flaky", "排查主分支 CI 偶发失败" }, { "oauth", "添加 OAuth 设备授权" }, { "docs", "重做文档站" }, { "pg17", "迁移到 Postgres 17" }, { "relnotes", "编写 v2.3 更新说明" } };
                string synthetic; if (titles.TryGetValue(Json.S(row, "id"), out synthetic)) return synthetic;
            }
            return String.IsNullOrEmpty(title) ? "未命名会话" : title;
        }
        void RenderMain() {
            if (closing) return;
            mainStale = false;
            body.Children.Clear(); probeButtons.Clear(); settingsPage = false; settingsButton.Content = "设置";
            var rows = Json.Items(Json.Get(snapshot, "threads")).ToList(); Section("近期会话", "近 48 小时 · " + rows.Count + " 个");
            if (rows.Count == 0) { var empty = new StackPanel(); empty.Children.Add(Text("近期还没有可检测的会话", 14, Ink, true)); empty.Children.Add(Text("在 Codex 中开始一次对话，再点刷新。也可以先检测下方的新会话。", 12, Muted, false)); body.Children.Add(Card(empty)); }
            for (int i = 0; i < rows.Count; i++) AddSession(rows[i], i);
            AddFresh();
        }
        void AddSession(object row, int index) {
            string id = Json.S(row, "id"); object probe = Json.Get(row, "last_probe"), failure = Json.Get(row, "last_failure");
            var content = new StackPanel();
            var text = new StackPanel { Margin = new Thickness(0, 0, 9, 0) };
            var titleButton = Button(SessionTitle(row, index), delegate { expanded = expanded == id ? null : id; RenderMain(); });
            titleButton.Background = Brushes.Transparent; titleButton.Padding = new Thickness(0, 1, 0, 2); titleButton.FontSize = 14; titleButton.FontWeight = FontWeights.SemiBold;
            titleButton.HorizontalContentAlignment = HorizontalAlignment.Left; titleButton.HorizontalAlignment = HorizontalAlignment.Stretch;
            titleButton.Content = Text(SessionTitle(row, index), 14, Ink, true); titleButton.ToolTip = "展开或收起模型归因、检测历史与被动证据";
            text.Children.Add(titleButton);
            text.Children.Add(Text("声明模型：" + Json.S(row, "model") + (Json.S(row, "effort").Length > 0 ? " @ " + Json.S(row, "effort") : "") + " · " + Json.N(row, "turns") + " 轮 · " + Ago(Json.S(row, "updated_ago")), 11, Muted, false));
            text.Children.Add(Text(FingerprintLine(probe) + (probe == null && Json.B(row, "due") ? " · 已到检测时间" : ""), 11, FingerprintColor(probe), false));
            if (PassiveAlert(probe)) text.Children.Add(Text(PassiveLine(probe), 11, Json.B(probe, "stale_account") ? Muted : Red, false));
            string error; if (commandFailures.TryGetValue(id, out error)) text.Children.Add(Text("最近尝试失败 · " + error, 11, Orange, false));
            else if (failure != null) text.Children.Add(Text("最近尝试失败 · " + Ago(Json.S(failure, "finished_ago")) + " · 有效裁决仍保留", 11, Orange, false));
            string evidence = TranslateEvidence(Json.S(row, "last_evidence"));
            if (evidence.Length > 0) text.Children.Add(Text("被动记录 · " + evidence + (Json.S(row, "last_evidence_ago").Length > 0 ? " · " + Ago(Json.S(row, "last_evidence_ago")) : ""), 11, Json.N(row, "hard_evidence") > 0 ? Red : Json.N(row, "good_evidence") > 0 ? Green : Orange, false));
            if (Json.B(row, "halted")) text.Children.Add(Text("工作工具已暂停 · 恢复命令：bin\\nerfed.cmd resume --thread " + id, 11, Orange, false));
            bool running = inferenceTarget == id || Json.B(row, "probe_running");
            bool retry = failure != null || commandFailures.ContainsKey(id);
            var action = Button(running ? "检测中…" : retry ? "重试" : "检测", delegate { StartProbe(id, retry); });
            action.IsEnabled = !running && !demo; action.ToolTip = demo ? "示例数据不调用推理" : "在该会话的临时分支中检测，会使用推理额度"; probeButtons[id] = action;
            var dot = new Ellipse { Width = 7, Height = 7, Fill = Json.B(row, "alert") ? Red : Json.B(row, "suspicious") ? Orange : VerdictColor(probe), VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(0, 10, 9, 0) };
            var summary = Split(text, action); var withDot = new DockPanel(); DockPanel.SetDock(dot, Dock.Left); withDot.Children.Add(dot); withDot.Children.Add(summary); content.Children.Add(withDot);
            if (expanded == id) AddDetails(content, row, false);
            body.Children.Add(Card(content));
        }
        static string TranslateEvidence(string text) {
            return (text ?? "").Replace("Silent model change:", "模型标识变化：").Replace("Silent effort change:", "推理强度变化：").Replace("Settings: model", "模型标识设置：").Replace("Settings: effort", "推理强度设置：").Replace("Hidden model ran:", "记录到隐藏模型：").Replace("Context window", "上下文变化：").Replace("was that you?", "是你改的吗？").Replace("Upgraded:", "已升配：");
        }
        void AddDetails(StackPanel target, object row, bool fresh) {
            target.Children.Add(new Border { Height = 1, Background = Color("#DDE0E3"), Margin = new Thickness(15, 9, 0, 7) });
            var detail = new StackPanel { Margin = new Thickness(15, 0, 0, 0) };
            object probe = Json.Get(row, fresh ? "global_probe" : "last_probe");
            detail.Children.Add(Text("模型指纹归因", 11, Muted, true));
            detail.Children.Add(Text("声明模型：" + (Json.S(probe, "expected").Length > 0 ? Json.S(probe, "expected") : Json.S(row, fresh ? "default_model" : "model")), 11, Muted, false));
            detail.Children.Add(Text(FingerprintLine(probe), 11, FingerprintColor(probe), false));
            if (FingerprintOverlap(probe)) detail.Children.Add(Text("现有指纹库无法稳定区分 Astra 与 Sol 6.1；原始候选不代表已确认的模型身份。", 10, Faint, false));
            else if (FingerprintCode(probe) == "UNLISTED") detail.Children.Add(Text("声明模型未被指纹库收录，原始候选只能作为相似线索，无法归因。", 10, Faint, false));
            var results = Json.Items(Json.Get(probe, "results")).ToList();
            if (results.Count == 0) detail.Children.Add(Text("尚无可用的模型归因。", 11, Faint, false));
            else detail.Children.Add(Text("原始候选 · 闭集相似分（非模型身份确认概率）", 10, Faint, false));
            foreach (object result in results.Take(6)) {
                var line = Split(Text(Json.S(result, "model"), 11, Muted, false), Text(Percent(Json.Get(result, "probability")), 11, Ink, true)); detail.Children.Add(line);
                detail.Children.Add(new Border { Height = 3, Background = Color("#E0E3E6"), Margin = new Thickness(0, 1, 0, 4), Child = new Border { HorizontalAlignment = HorizontalAlignment.Left, Width = Math.Max(0, Math.Min(1, Json.P(result, "probability"))) * 220, Background = FingerprintColor(probe), CornerRadius = new CornerRadius(2) } });
            }
            AddPassiveReasons(detail, probe);
            detail.Children.Add(Text("检测历史", 11, Muted, true));
            var history = Json.Items(Json.Get(row, fresh ? "global_probes" : "probes")).ToList();
            if (history.Count == 0) detail.Children.Add(Text("还没有检测记录。", 11, Faint, false));
            foreach (object item in history.Take(8)) {
                detail.Children.Add(Text(FingerprintLine(item), 11, FingerprintColor(item), false));
                if (Json.S(item, "recorded_verdict").Length > 0) detail.Children.Add(Text("原记录裁决：" + Json.S(item, "recorded_verdict") + " · 按当前归因规则展示", 10, Faint, false));
                AddPassiveReasons(detail, item);
            }
            object failure = Json.Get(row, fresh ? "global_failure" : "last_failure");
            if (failure != null) detail.Children.Add(Text("最近失败：" + String.Join("；", Json.Items(Json.Get(failure, "errors")).Select(Convert.ToString)), 11, Orange, false));
            if (!fresh) {
                detail.Children.Add(Text("被动证据", 11, Muted, true));
                var evidence = Json.Items(Json.Get(row, "evidence")).ToList();
                if (evidence.Count == 0) detail.Children.Add(Text("没有记录到模型或设置变化。", 11, Faint, false));
                foreach (object item in evidence.Take(8)) {
                    bool active = Json.B(item, "active"); string severity = Json.S(item, "severity");
                    detail.Children.Add(Text(TranslateEvidence(Json.S(item, "text")) + " · " + Ago(Json.S(item, "ago")) + (Json.S(item, "ts").Length > 0 ? " · " + Json.S(item, "ts") : "") + (active ? "" : " · 已还原"), 11, !active ? Muted : severity == "hard" ? Red : severity == "good" ? Green : Orange, false));
                }
            }
            detail.Children.Add(Text("指纹相似分是归因线索；被动记录显示模型标识或设置变化。", 10, Faint, false));
            var copy = Button("复制报告", delegate { CopyReport(row, fresh); }); copy.Margin = new Thickness(0, 6, 0, 2); detail.Children.Add(copy);
            target.Children.Add(detail);
        }
        static void AddPassiveReasons(StackPanel target, object probe) {
            if (!PassiveAlert(probe)) return;
            Brush color = Json.B(probe, "stale_account") ? Muted : Red;
            target.Children.Add(Text(PassiveLine(probe), 11, color, true));
            var reasons = Json.Items(Json.Get(probe, "passive_reasons")).ToList();
            foreach (object reason in reasons) target.Children.Add(Text(PassiveKind(Json.S(reason, "kind")) + "：" + Json.S(reason, "detail") + (Json.S(reason, "ts").Length > 0 ? " · " + Json.S(reason, "ts") : ""), 11, color, false));
            if (reasons.Count == 0) target.Children.Add(Text("原记录保留了被动告警，但未单独保存原因；请查看下方被动证据或完整报告。", 10, Faint, false));
        }
        void AddFresh() {
            Section("新会话", Json.S(snapshot, "default_model") + (Json.S(snapshot, "default_effort").Length > 0 ? " @ " + Json.S(snapshot, "default_effort") : ""));
            var content = new StackPanel(); object probe = Json.Get(snapshot, "global_probe"), failure = Json.Get(snapshot, "global_failure");
            bool running = inferenceTarget == "fresh" || Json.B(snapshot, "global_running");
            var summary = new StackPanel(); summary.Children.Add(Text(FingerprintLine(probe), 11, FingerprintColor(probe), false));
            if (PassiveAlert(probe)) summary.Children.Add(Text(PassiveLine(probe), 11, Json.B(probe, "stale_account") ? Muted : Red, false));
            if (failure != null || commandFailures.ContainsKey("fresh")) summary.Children.Add(Text("最近尝试失败 · 可重试，有效裁决仍保留", 11, Orange, false));
            var action = Button(running ? "检测中…" : failure != null || commandFailures.ContainsKey("fresh") ? "重试" : "检测", StartFresh);
            action.IsEnabled = !running && !demo; action.ToolTip = demo ? "示例数据不调用推理" : "使用独立新会话检测，会使用推理额度"; probeButtons["fresh"] = action;
            content.Children.Add(Split(summary, action));
            var options = new Grid { Margin = new Thickness(0, 9, 0, 2) };
            options.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(3, GridUnitType.Star) }); options.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(2, GridUnitType.Star) });
            var modelGroup = new StackPanel { Margin = new Thickness(0, 0, 8, 0) }; modelGroup.Children.Add(Text("模型（留空跟随 Codex）", 10, Muted, false));
            freshModel = new ComboBox { IsEditable = true, IsTextSearchEnabled = false, Text = modelDraft }; foreach (string model in new[] { "", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-5.6-sol", "gpt-5.6-luna" }) freshModel.Items.Add(model); freshModel.Text = modelDraft;
            freshModel.AddHandler(TextBox.TextChangedEvent, new TextChangedEventHandler(delegate { modelDraft = freshModel.Text; })); modelGroup.Children.Add(freshModel); options.Children.Add(modelGroup);
            freshModel.LostKeyboardFocus += delegate { RefreshAfterEditing(); }; freshModel.DropDownClosed += delegate { RefreshAfterEditing(); };
            var effortGroup = new StackPanel(); effortGroup.Children.Add(Text("推理级别（可留空）", 10, Muted, false));
            freshEffort = new ComboBox(); foreach (string effort in new[] { "", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra" }) freshEffort.Items.Add(effort); freshEffort.SelectedItem = effortDraft;
            freshEffort.SelectionChanged += delegate { effortDraft = Convert.ToString(freshEffort.SelectedItem) ?? ""; }; effortGroup.Children.Add(freshEffort); Grid.SetColumn(effortGroup, 1); options.Children.Add(effortGroup); content.Children.Add(options);
            freshEffort.LostKeyboardFocus += delegate { RefreshAfterEditing(); }; freshEffort.DropDownClosed += delegate { RefreshAfterEditing(); };
            content.Children.Add(Text("仅覆盖这次新会话检测；不改变已有会话、定时检测或 Codex 默认值。检测会使用推理额度。", 10, Muted, false));
            var details = Button(expanded == "fresh" ? "收起报告" : "查看报告", delegate { expanded = expanded == "fresh" ? null : "fresh"; RenderMain(); }); details.Background = Brushes.Transparent; details.Padding = new Thickness(0, 5, 0, 0); content.Children.Add(details);
            if (expanded == "fresh") AddDetails(content, snapshot, true);
            body.Children.Add(Card(content));
            if (demo) body.Children.Add(Text("示例数据 · 检测与自动调度均关闭", 10, Faint, false));
            else if (tray != null) body.Children.Add(Text("关闭窗口后驻留托盘；点“退出”结束面板。", 10, Faint, false));
        }
        void CopyReport(object row, bool fresh) {
            string report = Json.S(row, fresh ? "global_report_text" : "report_text");
            if (String.IsNullOrEmpty(report)) { object probe = Json.Get(row, fresh ? "global_probe" : "last_probe"); report = "声明模型：" + Json.S(probe, "expected") + "\n" + FingerprintLine(probe) + (PassiveAlert(probe) ? "\n" + PassiveLine(probe) : ""); }
            try { Clipboard.SetText(report); operation = "报告已复制"; } catch (Exception error) { operation = "无法访问剪贴板：" + error.Message; }
            UpdateActivity();
        }
        bool FreshEditorActive() {
            return (freshModel != null && (freshModel.IsKeyboardFocusWithin || freshModel.IsDropDownOpen)) || (freshEffort != null && (freshEffort.IsKeyboardFocusWithin || freshEffort.IsDropDownOpen));
        }
        void RefreshMain() {
            if (settingsPage) return;
            if (FreshEditorActive()) { mainStale = true; return; }
            RenderMain();
        }
        void RefreshAfterEditing() {
            if (closing || !mainStale || settingsPage) return;
            window.Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(delegate { if (!closing && mainStale && !settingsPage && !FreshEditorActive()) RenderMain(); }));
        }
        void ToggleSettings() {
            if (closing) return;
            if (settingsPage) { RenderMain(); scroll.ScrollToTop(); }
            else { BuildSettings(); scroll.ScrollToTop(); }
        }
        static string ConfigValue(object config, string key) {
            object value = Json.Get(config, key);
            return value is bool ? ((bool)value ? "true" : "false") : Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
        }
        void BuildSettings() {
            settingsPage = true; settingsButton.Content = "返回"; body.Children.Clear(); settings.Clear(); draftOriginal.Clear();
            object config = Json.Get(snapshot, "config");
            Section("设置", "保存后生效");
            AddSettingsGroup("检测计划", new[] { "frequency", "fresh_frequency", "mode", "queries", "parallel" }, config);
            body.Children.Add(Text("时间频率按上次检测、提醒或会话创建后的经过时间计；后台只补查最近 15 分钟有 Hook 活动的到期会话。新会话计划独立计时，当前账号尚无新会话检测历史时可能立即到期。", 11, Muted, false));
            body.Children.Add(Text("“仅提醒”只影响会话到期处理。要完全手动，请把两项计划都选为“手动”。", 11, Muted, false));
            body.Children.Add(Text("每次检测的样本数也是临时分支数。1 份用于初探；至少 2 份有效回答才能给出强不匹配裁决。", 11, Muted, false));
            AddSettingsGroup("观察与通知", new[] { "passive", "notify", "notify_on_ok", "announce_ok", "sound" }, config);
            AddSettingsGroup("隐私", new[] { "hide_titles" }, config);
            body.Children.Add(Text("被动观察读取本地会话记录，不调用推理。通知、声音与会话内公告按各自开关生效。", 11, Muted, false));
            body.Children.Add(Text("高级阈值和暂停工作工具仍由后端配置管理；本面板不修改这些选项。", 11, Faint, false));
            saveButton = Button(pending.Contains("settings") ? "正在保存…" : "保存设置", SaveSettings); saveButton.Margin = new Thickness(0, 12, 0, 8); saveButton.IsEnabled = !pending.Contains("settings"); body.Children.Add(saveButton);
            body.Children.Add(Text(demo ? "演示设置保存在隔离临时目录，退出后清除。" : "刷新快照不会覆盖本页未保存的输入。", 10, Faint, false));
        }
        static string SettingLabel(string key) {
            switch (key) {
                case "frequency": return "每个活跃会话"; case "fresh_frequency": return "独立新会话检测"; case "mode": return "会话到期时"; case "queries": return "每次检测的样本数"; case "parallel": return "并行收集样本";
                case "passive": return "逐轮被动观察"; case "notify": return "系统通知"; case "notify_on_ok": return "匹配时也通知"; case "announce_ok": return "将匹配结果发布到会话"; case "sound": return "降配时播放声音"; case "hide_titles": return "隐藏会话标题与账号"; default: return key;
            }
        }
        static List<KeyValuePair<string, string>> Options(string key) {
            var list = new List<KeyValuePair<string, string>>();
            if (key == "mode") { list.Add(new KeyValuePair<string, string>("auto", "后台检测")); list.Add(new KeyValuePair<string, string>("nudge", "仅提醒")); }
            else if (key == "queries") foreach (string v in new[] { "1", "2", "3" }) list.Add(new KeyValuePair<string, string>(v, v + " 份"));
            else {
                list.Add(new KeyValuePair<string, string>("manual", "手动"));
                if (key == "frequency") foreach (string turns in new[] { "4", "8", "16" }) list.Add(new KeyValuePair<string, string>("turns:" + turns, "每 " + turns + " 轮"));
                foreach (string time in key == "frequency" ? new[] { "15m", "30m", "1h", "2h" } : new[] { "15m", "30m", "1h", "2h", "6h" }) list.Add(new KeyValuePair<string, string>(time, "每 " + time.Replace("m", " 分钟").Replace("h", " 小时")));
            }
            return list;
        }
        void AddSettingsGroup(string title, string[] keys, object config) {
            Section(title, ""); var group = new StackPanel();
            foreach (string key in keys) {
                string value = ConfigValue(config, key); draftOriginal[key] = value; Control input;
                if (key == "frequency" || key == "fresh_frequency" || key == "mode" || key == "queries") {
                    var options = Options(key); if (!options.Any(o => o.Key == value)) options.Add(new KeyValuePair<string, string>(value, value));
                    var combo = new ComboBox { ItemsSource = options, DisplayMemberPath = "Value", SelectedValuePath = "Key", SelectedValue = value, MinWidth = 140, MaxWidth = 205, HorizontalAlignment = HorizontalAlignment.Stretch }; input = combo;
                } else input = new CheckBox { IsChecked = value == "true", HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 4, 0) };
                AutomationProperties.SetName(input, SettingLabel(key)); settings[key] = input;
                var label = Text(SettingLabel(key), 12, Ink, false); label.VerticalAlignment = VerticalAlignment.Center; label.Margin = new Thickness(0, 0, 12, 0);
                var row = new Grid { Margin = new Thickness(0, 5, 0, 5) }; row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1.1, GridUnitType.Star) }); row.Children.Add(label); Grid.SetColumn(input, 1); row.Children.Add(input); group.Children.Add(row);
                if (key != keys.Last()) group.Children.Add(new Border { Height = 1, Background = Color("#E0E3E6"), Margin = new Thickness(0, 3, 0, 3) });
            }
            body.Children.Add(Card(group));
        }
        void SaveSettings() {
            var values = new Dictionary<string, string>();
            foreach (var item in settings) {
                var combo = item.Value as ComboBox; var check = item.Value as CheckBox;
                string value = combo != null ? Convert.ToString(combo.SelectedValue) : check.IsChecked == true ? "true" : "false";
                if (value != draftOriginal[item.Key]) values[item.Key] = value;
            }
            if (values.Count == 0) { operation = "设置没有变化"; UpdateActivity(); return; }
            Begin(new Request { Action = "settings", Settings = values });
        }
        void StartProbe(string target, bool retry) { Begin(new Request { Action = retry ? "retry" : "probe", Target = target }); }
        void StartFresh() { Begin(new Request { Action = "fresh", Target = "fresh", Model = freshModel == null ? modelDraft : freshModel.Text, Effort = freshEffort == null ? effortDraft : Convert.ToString(freshEffort.SelectedItem) }); }
        bool Begin(Request request) {
            if (closing || pending.Contains(request.Action)) return false;
            if (request.Inference) {
                if (demo && !fakeInference) { operation = "示例模式不调用推理"; UpdateActivity(); return false; }
                if (inferenceTarget != null) { operation = "已有检测在运行，请完成后再检测其他目标；刷新和设置仍可使用。"; UpdateActivity(); return false; }
                inferenceTarget = request.Action == "tick" ? "scheduler" : request.Target ?? "fresh";
            }
            pending.Add(request.Action);
            if (!transport.Submit(request, Deliver)) { pending.Remove(request.Action); if (request.Inference) inferenceTarget = null; return false; }
            UpdateControls(); return true;
        }
        void Deliver(Result result) {
            if (closing || window.Dispatcher.HasShutdownStarted) return;
            if (window.Dispatcher.CheckAccess()) Complete(result);
            else try { window.Dispatcher.BeginInvoke(new Action(delegate { if (!closing) Complete(result); })); } catch (InvalidOperationException) { }
        }
        void Complete(Result result) {
            if (closing) return;
            string action = result.Request.Action; pending.Remove(action);
            if (result.Request.Inference) inferenceTarget = null;
            if (!result.Ok) {
                operation = (action == "snapshot" ? "读取快照失败" : action == "settings" ? "保存失败，部分设置可能已生效；刷新核对" : action == "doctor" ? "诊断失败" : "最近检测失败") + "：" + result.Error;
                if (result.Request.Inference && action != "tick") commandFailures[result.Request.Target ?? "fresh"] = result.Error;
                if (action == "doctor") ShowDiagnostics(result.Error);
                if (smoke || selfTest || !String.IsNullOrEmpty(renderPath)) { if (!fakeInference) { exitCode = 1; Console.Error.WriteLine(operation); Shutdown(); return; } }
            } else {
                if (action == "snapshot") {
                    snapshot = result.Snapshot;
                    if (demo) ApplyDemoOverrides();
                    RenderHeader(); NotifyChanges();
                    RefreshMain();
                    operation = "快照已刷新 · " + DateTime.Now.ToString("HH:mm:ss");
                    version.Text = "v" + Json.S(snapshot, "version") + (demo ? " · 示例" : "");
                } else if (action == "settings") {
                    foreach (var item in result.Request.Settings) { draftOriginal[item.Key] = item.Value; if (demo) demoOverrides[item.Key] = item.Value; }
                    operation = demo ? "演示设置已保存（退出后清除）" : "设置已保存";
                    Begin(new Request { Action = "snapshot" });
                } else if (action == "doctor") { operation = "诊断完成"; ShowDiagnostics(result.Output); }
                else {
                    if (action != "tick") commandFailures.Remove(result.Request.Target ?? "fresh");
                    // Scheduler stdout is operational state only; it never enters a session report.
                    operation = action == "tick" ? "后台调度已检查" : action == "heartbeat" ? "定时新会话检测完成" : "检测完成，正在刷新裁决";
                    Begin(new Request { Action = "snapshot" });
                }
            }
            if (result.Request.Inference) RefreshMain();
            UpdateControls();
            if (action == "snapshot" && result.Ok) {
                if (selfTest && !testStarted) { testStarted = true; RunSelfTests(); return; }
                if (!String.IsNullOrEmpty(renderPath) && !rendered) {
                    rendered = true;
                    if (renderPage == "settings") BuildSettings();
                    if (renderPage == "detail") { expanded = "payments"; RenderMain(); }
                    window.Dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(delegate {
                        try { RenderToFile(renderPath, renderScale); Console.WriteLine("Rendered synthetic native panel: " + System.IO.Path.GetFullPath(renderPath)); }
                        catch (Exception error) { exitCode = 1; Console.Error.WriteLine(error.ToString()); }
                        Shutdown();
                    })); return;
                }
                if (smoke) { Console.WriteLine("Native WPF smoke passed: synthetic snapshot and UI loaded; inference disabled."); Shutdown(); return; }
                Schedule();
            }
        }
        void ApplyDemoOverrides() {
            var config = Json.Map(Json.Get(snapshot, "config"));
            foreach (var item in demoOverrides) { if (item.Value == "true" || item.Value == "false") config[item.Key] = item.Value == "true"; else if (item.Key == "queries") config[item.Key] = Int32.Parse(item.Value); else config[item.Key] = item.Value; }
        }
        void Schedule() {
            string next = Scheduler.Next(snapshot, demo, inferenceTarget != null, DateTime.UtcNow, lastHeartbeat, lastTick);
            if (next == "heartbeat") { lastHeartbeat = DateTime.UtcNow; Begin(new Request { Action = "heartbeat", Target = "fresh" }); }
            else if (next == "tick") { lastTick = DateTime.UtcNow; Begin(new Request { Action = "tick", Target = "scheduler" }); }
        }
        void UpdateControls() {
            if (refreshButton == null || closing) return;
            refreshButton.IsEnabled = !pending.Contains("snapshot"); refreshButton.Content = pending.Contains("snapshot") ? "读取中…" : "刷新";
            doctorButton.IsEnabled = !pending.Contains("doctor"); doctorButton.Content = pending.Contains("doctor") ? "诊断中…" : "诊断";
            if (saveButton != null) { saveButton.IsEnabled = !pending.Contains("settings"); saveButton.Content = pending.Contains("settings") ? "正在保存…" : "保存设置"; }
            foreach (var item in probeButtons) {
                bool running = inferenceTarget == item.Key;
                object row = item.Key == "fresh" ? snapshot : Json.Items(Json.Get(snapshot, "threads")).FirstOrDefault(t => Json.S(t, "id") == item.Key);
                running = running || Json.B(row, item.Key == "fresh" ? "global_running" : "probe_running");
                item.Value.IsEnabled = !running && (!demo || fakeInference);
                if (running) item.Value.Content = "检测中…";
            }
            UpdateActivity();
        }
        void UpdateActivity() {
            if (activity == null) return;
            var parts = new List<string>();
            if (inferenceTarget != null) parts.Add(inferenceTarget == "scheduler" ? "后台调度运行中" : inferenceTarget == "fresh" ? "新会话检测中" : "会话检测中");
            if (pending.Contains("snapshot")) parts.Add("读取快照");
            if (pending.Contains("settings")) parts.Add("保存设置");
            if (pending.Contains("doctor")) parts.Add("运行诊断");
            activity.Text = parts.Count > 0 ? String.Join(" · ", parts) + " · 刷新与设置可独立使用" : operation;
            activity.ToolTip = activity.Text;
        }
        void ShowDiagnostics(string text) {
            diagnosticOutput = text;
            if (selfTest || smoke || !String.IsNullOrEmpty(renderPath) || closing) return;
            var dialog = new Window { Title = "诊断 · is-gpt-nerfed", Owner = window, Width = 620, Height = 450, MinWidth = 360, MinHeight = 260, WindowStartupLocation = WindowStartupLocation.CenterOwner };
            var box = new TextBox { Text = String.IsNullOrWhiteSpace(text) ? "诊断没有返回文本。" : text, IsReadOnly = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, FontFamily = new FontFamily("Consolas, Microsoft YaHei UI"), Margin = new Thickness(12) };
            var dock = new DockPanel(); var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(12, 0, 12, 12) };
            buttons.Children.Add(Button("复制诊断", delegate { try { Clipboard.SetText(box.Text); } catch { } })); var close = Button("关闭", delegate { dialog.Close(); }); close.Margin = new Thickness(8, 0, 0, 0); buttons.Children.Add(close); DockPanel.SetDock(buttons, Dock.Bottom); dock.Children.Add(buttons); dock.Children.Add(box); dialog.Content = dock; dialog.Show();
        }
        void CreateTray() {
            try {
                using (Stream stream = FaceStream("ok")) using (var bitmap = new System.Drawing.Bitmap(stream)) { IntPtr icon = bitmap.GetHicon(); try { trayIcon = (System.Drawing.Icon)System.Drawing.Icon.FromHandle(icon).Clone(); } finally { DestroyIcon(icon); } }
                tray = new Forms.NotifyIcon { Icon = trayIcon, Text = "is-gpt-nerfed · 点击打开面板", Visible = true };
                var menu = new Forms.ContextMenuStrip();
                menu.Items.Add("打开面板", null, delegate { OnUI(ShowPanel); });
                menu.Items.Add("设置", null, delegate { OnUI(delegate { ShowPanel(); if (!settingsPage) BuildSettings(); }); });
                menu.Items.Add(new Forms.ToolStripSeparator()); menu.Items.Add("退出", null, delegate { OnUI(Shutdown); }); tray.ContextMenuStrip = menu;
                tray.DoubleClick += delegate { OnUI(ShowPanel); }; tray.Click += delegate(object sender, EventArgs e) { if (!(e is Forms.MouseEventArgs) || ((Forms.MouseEventArgs)e).Button == Forms.MouseButtons.Left) OnUI(ShowPanel); };
            } catch { if (tray != null) tray.Dispose(); tray = null; if (trayIcon != null) trayIcon.Dispose(); trayIcon = null; }
        }
        void OnUI(Action action) { if (!closing && !window.Dispatcher.HasShutdownStarted) window.Dispatcher.BeginInvoke(action); }
        void ShowPanel() { if (closing) return; window.Show(); window.WindowState = WindowState.Normal; window.Activate(); }
        void HideToTray() { if (closing) return; window.Hide(); operation = "面板驻留托盘"; UpdateActivity(); }
        void NotifyChanges() {
            object overall = Json.Get(snapshot, "overall"), config = Json.Get(snapshot, "config"), verdict = Json.Get(snapshot, "last_verdict");
            string signature = Json.S(overall, "status") + "|" + Json.N(overall, "downgraded") + "|" + Json.N(overall, "suspicious"), id = Json.S(verdict, "id");
            bool changed = previousSignature != null && signature != previousSignature, newVerdict = previousSignature != null && id.Length > 0 && id != previousVerdict;
            if (tray != null && Json.B(config, "notify")) {
                bool alert = Json.S(overall, "status") == "alert" || Json.B(verdict, "is_downgrade"), warn = Json.S(overall, "status") == "warn" || Json.B(verdict, "is_suspicious");
                if ((changed && (alert || warn)) || (newVerdict && (alert || warn || (Json.B(config, "notify_on_ok") && FingerprintCode(verdict) == "MATCH" && !FingerprintOverlap(verdict))))) {
                    tray.ShowBalloonTip(6000, alert ? (PassiveAlert(verdict) ? PassiveLabel(verdict) : "检测到模型变化告警") : warn ? "检测结果可疑" : "检测结果匹配", Json.N(overall, "downgraded") + " 个告警 · " + Json.N(overall, "suspicious") + " 个可疑", alert ? Forms.ToolTipIcon.Error : warn ? Forms.ToolTipIcon.Warning : Forms.ToolTipIcon.Info);
                    // Sound is emitted once by the shared backend, independently of notifications.
                }
            }
            previousSignature = signature; previousVerdict = id;
        }
        void RenderToFile(string path, double scale) {
            // A desktop window is constrained by the current monitor. Lay out only our synthetic
            // content on an independent white visual, so exported pages are complete at any DPI.
            window.Content = null; surface.Margin = new Thickness(0);
            double width = renderWidth > 0 ? renderWidth : 540;
            double height = renderPage == "detail" ? 1480 : renderPage == "settings" ? 1080 : 1120;
            var canvas = new Border { Width = width, Height = height, Background = Brushes.White, Padding = new Thickness(18, 12, 18, 12), Child = surface, Resources = window.Resources };
            canvas.Measure(new Size(width, height)); canvas.Arrange(new Rect(0, 0, width, height)); canvas.UpdateLayout();
            var bitmap = new RenderTargetBitmap((int)Math.Ceiling(width * scale), (int)Math.Ceiling(height * scale), 96 * scale, 96 * scale, PixelFormats.Pbgra32); bitmap.Render(canvas);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
            string full = System.IO.Path.GetFullPath(path); Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)); using (var output = File.Create(full)) encoder.Save(output);
        }
        void Shutdown() {
            if (closing) return; closing = true; timer.Stop();
            transport.Dispose();
            if (tray != null) { tray.Visible = false; if (tray.ContextMenuStrip != null) tray.ContextMenuStrip.Dispose(); tray.Dispose(); tray = null; }
            if (trayIcon != null) { trayIcon.Dispose(); trayIcon = null; }
            if (window != null && !windowClosing) window.Close();
        }

        static void Assert(bool condition, string message) { if (!condition) throw new InvalidOperationException("Native self-test failed: " + message); }
        void RunSelfTests() {
            try {
                string initial = Json.Encode(snapshot); transport.Dispose(); var fake = new FakeTransport(initial); transport = fake; fakeInference = true;
                Assert(demo && !String.IsNullOrEmpty(Environment.GetEnvironmentVariable("CODEX_HOME")) && Environment.GetEnvironmentVariable("CODEX_HOME").Contains("nerfed-native-"), "temporary homes");
                var overlap = Json.Parse(@"{""expected"":""gpt-6.1-sol"",""prediction"":""gpt-6-astra"",""probability"":1.0,""verdict"":""AMBIGUOUS"",""fingerprint_verdict"":""AMBIGUOUS"",""fingerprint_resolution"":""overlap"",""results"":[{""model"":""gpt-6-astra"",""probability"":1.0}]}");
                Assert(FingerprintLine(overlap).Contains("Astra / Sol 6.1 · 无法区分") && !FingerprintLine(overlap).Contains("100%") && FingerprintColor(overlap) == Muted && !PassiveAlert(overlap), "ambiguous fingerprint is neutral and does not confirm raw candidate");
                var passive = Json.Parse(Json.Encode(overlap)); passive["verdict"] = "DOWNGRADED!"; passive["verdict_basis"] = "passive"; passive["is_downgrade"] = true;
                passive["passive_reasons"] = new[] { Json.Parse(@"{""kind"":""silent_effort_change"",""detail"":""high → low"",""ts"":""2026-10-10T10:00:00Z""}") };
                Assert(Verdict(passive) == "推理强度变化告警" && VerdictColor(passive) == Red && FingerprintColor(passive) == Muted, "passive alert does not change independent fingerprint color");
                var syntheticDetails = new StackPanel(); AddDetails(syntheticDetails, new Dictionary<string, object> { { "last_probe", passive } }, false);
                string presented = String.Join("\n", syntheticDetails.Children.OfType<StackPanel>().First().Children.OfType<TextBlock>().Select(t => t.Text));
                Assert(presented.Contains("声明模型：gpt-6.1-sol") && presented.Contains("闭集相似分") && presented.Contains("high → low") && presented.Contains("2026-10-10T10:00:00Z"), "rendered details distinguish declaration, raw scores and timed passive evidence");
                var unlisted = Json.Parse(@"{""expected"":""future-model"",""prediction"":""gpt-6-astra"",""probability"":1.0,""verdict"":""UNLISTED""}");
                Assert(FingerprintLine(unlisted).Contains("未收录 · 不可归因") && !FingerprintLine(unlisted).Contains("100%") && FingerprintColor(unlisted) == Muted, "unlisted model remains unattributable with older fields");
                // The real row click path, not an alternate inference implementation.
                fake.HoldInference = true; UpdateControls(); probeButtons["payments"].RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent));
                Assert(fake.Calls.Last()[0] == "worker" && fake.Calls.Last()[2] == "payments", "selected session arguments");
                Assert(!probeButtons["payments"].IsEnabled && inferenceTarget == "payments", "target busy state");
                int before = fake.Calls.Count; Assert(!Begin(new Request { Action = "probe", Target = "payments" }) && fake.Calls.Count == before, "duplicate target rejected");
                refreshButton.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent)); Assert(fake.Calls.Last()[0] == "snapshot" && refreshButton.IsEnabled, "refresh during long probe");
                settingsButton.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent)); Assert(settingsPage, "settings during long probe");
                ((ComboBox)settings["frequency"]).SelectedValue = "manual"; ((ComboBox)settings["fresh_frequency"]).SelectedValue = "2h"; ((ComboBox)settings["queries"]).SelectedValue = "2";
                ((ComboBox)settings["mode"]).SelectedValue = "nudge"; ((CheckBox)settings["notify_on_ok"]).IsChecked = true;
                Begin(new Request { Action = "snapshot" }); Assert(Convert.ToString(((ComboBox)settings["frequency"]).SelectedValue) == "manual", "refresh preserves unsaved draft");
                saveButton.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent));
                Assert(fake.Calls.Any(a => a.SequenceEqual(new[] { "config", "set", "fresh_frequency", "2h" })) && fake.Calls.Any(a => a.SequenceEqual(new[] { "config", "set", "queries", "2" })), "settings forwarding");
                doctorButton.RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent)); Assert(diagnosticOutput == "fake doctor ok", "diagnostics during long probe");
                window.Width = 380; window.Height = 560; window.UpdateLayout(); saveButton.BringIntoView(); scroll.ScrollToEnd(); window.UpdateLayout();
                Point savedPosition = saveButton.TranslatePoint(new Point(0, 0), scroll);
                Assert(savedPosition.Y >= -1 && savedPosition.Y + saveButton.ActualHeight <= scroll.ActualHeight + 1, "save button reachable at minimum window size");
                window.Width = 540; window.Height = 1120; window.UpdateLayout();
                fake.Release(false); Assert(commandFailures.ContainsKey("payments"), "failed operation separate from valid verdict");
                ToggleSettings(); UpdateControls(); Assert(Convert.ToString(probeButtons["payments"].Content) == "重试", "retry affordance");
                probeButtons["payments"].RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent)); Assert(fake.Calls.Last().SequenceEqual(new[] { "worker", "--thread", "payments" }), "retry reuses worker"); fake.Release(true);
                ComboBox editing = freshModel; Keyboard.Focus(editing); editing.Text = "gpt-6.1-";
                Assert(FreshEditorActive(), "fresh editor has focus"); Begin(new Request { Action = "snapshot" });
                Assert(Object.ReferenceEquals(editing, freshModel) && editing.IsKeyboardFocusWithin && editing.Text == "gpt-6.1-", "snapshot preserves editor instance and keyboard focus");
                Keyboard.ClearFocus(); RenderMain();
                freshModel.Text = "gpt-6.1-sol"; freshEffort.SelectedItem = "xhigh"; probeButtons["fresh"].RaiseEvent(new RoutedEventArgs(System.Windows.Controls.Primitives.ButtonBase.ClickEvent));
                Assert(fake.Calls.Last().SequenceEqual(new[] { "probe", "fresh", "--model", "gpt-6.1-sol", "--effort", "xhigh" }), "fresh model and effort"); fake.Release(true);
                freshModel.Text = ""; freshEffort.SelectedItem = ""; StartFresh(); Assert(fake.Calls.Last().SequenceEqual(new[] { "probe", "fresh" }), "empty fresh overrides omitted"); fake.Release(true);
                string report = Json.S(Json.Items(Json.Get(snapshot, "threads")).First(), "report_text"); fake.HoldInference = false; Begin(new Request { Action = "tick", Target = "scheduler" });
                Assert(Json.S(Json.Items(Json.Get(snapshot, "threads")).First(), "report_text") == report && !report.Contains("nothing due"), "tick output excluded from report");
                Assert(Scheduler.Next(snapshot, true, false, DateTime.UtcNow, DateTime.MinValue, DateTime.MinValue) == null, "demo scheduler disabled");
                var scheduled = Json.Parse(initial); Json.Map(Json.Get(scheduled, "config"))["fresh_frequency"] = "30m"; scheduled["fresh_due"] = true;
                Assert(Scheduler.Next(scheduled, false, false, DateTime.UtcNow, DateTime.MinValue, DateTime.MinValue) == "heartbeat", "independent fresh heartbeat");
                Assert(Scheduler.Next(scheduled, false, false, DateTime.UtcNow, DateTime.UtcNow, DateTime.UtcNow) == null, "scheduler throttle");
                Assert(new Request { Action = "heartbeat", Model = "ignored", Effort = "ignored" }.Commands(false)[0].SequenceEqual(new[] { "probe", "fresh" }), "heartbeat uses Codex defaults");
                // Exercise the actual inbox NotifyIcon lifecycle with only this synthetic window.
                CreateTray(); Assert(tray != null && tray.Visible && trayIcon != null, "native NotifyIcon created and visible");
                HideToTray(); Assert(!window.IsVisible, "hide to tray"); ShowPanel(); Assert(window.IsVisible, "restore from tray");
                fake.HoldInference = true; StartProbe("payments", false); int count = fake.Calls.Count; Shutdown();
                Assert(fake.Closed && tray == null && trayIcon == null && !Begin(new Request { Action = "snapshot" }) && !fake.Submit(new Request { Action = "doctor" }, delegate { }) && fake.Calls.Count == count, "shutdown disposes tray and cannot start more work");
                fake.Release(true); Assert(fake.Calls.Count == count, "late callback cannot refresh after shutdown");
                using (var backend = new BackendTransport(python, root, true)) { backend.Dispose(); Assert(!backend.Submit(new Request { Action = "snapshot" }, delegate { }), "real transport closed gate"); }
                Console.WriteLine("Native isolated state: " + System.IO.Path.GetDirectoryName(Environment.GetEnvironmentVariable("CODEX_HOME")));
                Console.WriteLine("Native self-test passed: conservative attribution and timed passive evidence, session/retry/fresh/settings, long-probe refresh and diagnostics, draft/focus preservation, minimum-size Save reachability, scheduler isolation/throttle, NotifyIcon lifecycle, shutdown gate.");
            } catch (Exception error) { exitCode = 1; Console.Error.WriteLine(error.ToString()); Shutdown(); }
        }
    }

    internal static class TransportContracts {
        static void Check(bool condition, string message) { if (!condition) throw new InvalidOperationException("Transport self-test failed: " + message); }
        internal static void Run(string python) {
            // This is a dummy executable transport fixture, never the real nerfed backend.
            string temp = System.IO.Path.Combine(System.IO.Path.GetDirectoryName(Environment.GetEnvironmentVariable("CODEX_HOME")), "backend 中文 space");
            string scripts = System.IO.Path.Combine(temp, "plugin", "skills", "is-gpt-nerfed", "scripts"); Directory.CreateDirectory(scripts);
            string log = System.IO.Path.Combine(temp, "commands.jsonl"), marker = System.IO.Path.Combine(temp, "started");
            string previous = Environment.GetEnvironmentVariable("NERFED_NATIVE_TEST_LOG");
            File.WriteAllText(System.IO.Path.Combine(scripts, "nerfed"), @"import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ['NERFED_NATIVE_TEST_LOG'])
with log.open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(args, ensure_ascii=False) + '\n')
print(json.dumps(args, ensure_ascii=False), flush=True)
if args[0] == 'probe':
    sys.stdout.write('x' * 200000)
    sys.stderr.write('中文错误' * 100000)
if args[:3] == ['config', 'set', 'frequency']:
    log.with_name('started').write_text('ready', encoding='utf-8')
    time.sleep(30)
", new UTF8Encoding(false));
            Environment.SetEnvironmentVariable("NERFED_NATIVE_TEST_LOG", log);
            try {
                using (var backend = new BackendTransport(python, temp, false)) {
                    using (var done = new ManualResetEventSlim()) {
                        Result response = null; string model = "gpt-6 \"中文 path\" \\";
                        backend.Submit(new Request { Action = "fresh", Model = model, Effort = "xhigh" }, delegate(Result r) { response = r; done.Set(); });
                        Check(done.Wait(10000), "bounded quoted/UTF8 command completion"); Check(response.Ok, response.Error);
                        string firstLine = response.Output.Split('\n')[0].TrimEnd('\r');
                        var received = Json.Serializer().Deserialize<string[]>(firstLine);
                        Check(received.SequenceEqual(new[] { "probe", "fresh", "--model", model, "--effort", "xhigh" }), "CRT quoting and Unicode round trip");
                        Check(response.Output.Contains("中文错误") && response.Output.Length > 500000, "both large pipes drain without deadlock");
                    }
                    using (var settingsDone = new ManualResetEventSlim()) using (var doctorDone = new ManualResetEventSlim()) {
                        backend.Submit(new Request { Action = "settings", Settings = new Dictionary<string, string> { { "frequency", "manual" }, { "fresh_frequency", "2h" } } }, delegate { settingsDone.Set(); });
                        var watch = Stopwatch.StartNew(); while (!File.Exists(marker) && watch.ElapsedMilliseconds < 5000) Thread.Sleep(20);
                        Check(File.Exists(marker), "first settings command started");
                        backend.Submit(new Request { Action = "doctor" }, delegate(Result r) { if (r.Ok) doctorDone.Set(); });
                        Check(doctorDone.Wait(5000), "independent process while another command waits");
                        backend.Dispose(); Check(settingsDone.Wait(5000), "owned process stopped on shutdown");
                        Check(!backend.Submit(new Request { Action = "doctor" }, delegate { }), "no process after shutdown");
                        Check(!File.ReadAllLines(log).Any(line => line.Contains("fresh_frequency")), "queued settings continuation cannot start after shutdown");
                    }
                }
                Console.WriteLine("Native transport self-test passed: Unicode/space/quote/backslash arguments, concurrent large stdout/stderr, independent reads, in-flight shutdown and queued-settings gate.");
            } finally { Environment.SetEnvironmentVariable("NERFED_NATIVE_TEST_LOG", previous); }
        }
    }

    // Used only by --self-test, after loading the isolated synthetic snapshot. No inference is run.
    internal sealed class FakeTransport : ITransport {
        internal readonly List<string[]> Calls = new List<string[]>();
        internal bool HoldInference, Closed;
        string snapshot;
        Action<Result> heldCallback;
        Request heldRequest;
        internal FakeTransport(string snapshot) { this.snapshot = snapshot; }
        public bool Submit(Request request, Action<Result> completed) {
            if (Closed) return false;
            foreach (string[] command in request.Commands(true)) Calls.Add(command);
            if (request.Inference && HoldInference) { heldRequest = request; heldCallback = completed; return true; }
            if (request.Action == "settings") {
                var data = Json.Parse(snapshot); var config = Json.Map(Json.Get(data, "config"));
                foreach (var value in request.Settings) config[value.Key] = value.Value == "true" || value.Value == "false" ? (object)(value.Value == "true") : value.Key == "queries" ? (object)Int32.Parse(value.Value) : value.Value;
                snapshot = Json.Encode(data);
            }
            completed(new Result { Request = request, Ok = true, Output = request.Action == "doctor" ? "fake doctor ok" : request.Action == "tick" ? "nothing due" : "fake completed", Snapshot = request.Action == "snapshot" ? Json.Parse(snapshot) : null }); return true;
        }
        internal void Release(bool ok) { var callback = heldCallback; var request = heldRequest; heldCallback = null; heldRequest = null; if (callback != null) callback(new Result { Request = request, Ok = ok, Output = "fake probe completed", Error = ok ? "" : "合成超时，未得到新样本" }); }
        public void Dispose() { Closed = true; }
    }
}
