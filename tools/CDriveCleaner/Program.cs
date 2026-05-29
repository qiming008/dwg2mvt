using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using Microsoft.Win32;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace CDriveCleaner
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }
    }

    internal sealed class MainForm : Form
    {
        private CheckedListBox _cleanupList;
        private ListView _moveList;
        private TextBox _logBox;
        private Label _summaryLabel;
        private Button _scanCleanupButton;
        private Button _runCleanupButton;
        private Button _scanMoveButton;
        private Button _moveSelectedButton;
        private Button _scanAppDataButton;
        private readonly List<CleanupTarget> _cleanupTargets;
        private AnalysisViewMode _currentViewMode;

        public MainForm()
        {
            Text = "C盘清理与搬移助手";
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1120, 760);
            MinimumSize = new Size(1024, 680);
            Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);
            BackColor = Color.FromArgb(244, 247, 251);

            _cleanupTargets = CleanupTargetFactory.Create();

            var intro = new Label();
            intro.Dock = DockStyle.Top;
            intro.Height = 68;
            intro.Padding = new Padding(16, 12, 16, 0);
            intro.ForeColor = Color.FromArgb(55, 65, 81);
            intro.Text =
                "这个工具分两部分：左侧安全清理系统临时文件，右侧整理并搬移 C 盘里体积较大的个人文件或软件数据。"
                + Environment.NewLine
                + "不会主动删除你的文档内容；搬移微信、QQ、下载目录等数据前，建议先退出相关软件。";

            _summaryLabel = new Label();
            _summaryLabel.Dock = DockStyle.Top;
            _summaryLabel.Height = 34;
            _summaryLabel.Padding = new Padding(16, 0, 16, 0);
            _summaryLabel.TextAlign = ContentAlignment.MiddleLeft;
            _summaryLabel.BackColor = Color.FromArgb(225, 236, 250);
            _summaryLabel.ForeColor = Color.FromArgb(25, 55, 99);
            _summaryLabel.Text = BuildPrivilegeText();

            var split = new SplitContainer();
            split.Dock = DockStyle.Fill;
            split.Orientation = Orientation.Horizontal;
            split.SplitterDistance = 430;
            split.Panel1.Controls.Add(BuildTopPanel());
            split.Panel2.Controls.Add(BuildLogPanel());

            Controls.Add(split);
            Controls.Add(_summaryLabel);
            Controls.Add(intro);

            AppendLog("准备就绪。你可以先扫描可清理空间，或者扫描可搬移的大文件和目录。");
        }

        private Control BuildTopPanel()
        {
            var split = new SplitContainer();
            split.Dock = DockStyle.Fill;
            split.SplitterDistance = 380;
            split.Panel1.Controls.Add(BuildCleanupPanel());
            split.Panel2.Controls.Add(BuildMovePanel());
            return split;
        }

        private Control BuildCleanupPanel()
        {
            var panel = new Panel();
            panel.Dock = DockStyle.Fill;
            panel.Padding = new Padding(12);
            panel.BackColor = Color.White;

            var title = new Label();
            title.Dock = DockStyle.Top;
            title.Height = 30;
            title.Text = "安全清理";
            title.Font = new Font(Font, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(23, 37, 84);

            _cleanupList = new CheckedListBox();
            _cleanupList.Dock = DockStyle.Fill;
            _cleanupList.CheckOnClick = true;
            _cleanupList.HorizontalScrollbar = true;
            _cleanupList.BorderStyle = BorderStyle.None;
            _cleanupList.BackColor = Color.White;

            foreach (var target in _cleanupTargets)
            {
                _cleanupList.Items.Add(target, true);
            }

            _scanCleanupButton = new Button();
            _scanCleanupButton.Text = "扫描可清理项";
            _scanCleanupButton.Width = 126;
            _scanCleanupButton.Height = 34;
            _scanCleanupButton.Click += async delegate { await RunCleanupScanAsync(); };
            StylePrimaryButton(_scanCleanupButton);

            _runCleanupButton = new Button();
            _runCleanupButton.Text = "执行清理";
            _runCleanupButton.Width = 110;
            _runCleanupButton.Height = 34;
            _runCleanupButton.Click += async delegate { await RunCleanupAsync(); };
            StyleAccentButton(_runCleanupButton);

            var openTempButton = new Button();
            openTempButton.Text = "打开临时目录";
            openTempButton.Width = 120;
            openTempButton.Height = 34;
            openTempButton.Click += delegate { Process.Start("explorer.exe", Path.GetTempPath()); };
            StyleLightButton(openTempButton);

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 46;
            buttons.Padding = new Padding(0, 8, 0, 0);
            buttons.Controls.Add(_scanCleanupButton);
            buttons.Controls.Add(_runCleanupButton);
            buttons.Controls.Add(openTempButton);

            panel.Controls.Add(_cleanupList);
            panel.Controls.Add(buttons);
            panel.Controls.Add(title);
            return panel;
        }

        private Control BuildMovePanel()
        {
            var panel = new Panel();
            panel.Dock = DockStyle.Fill;
            panel.Padding = new Padding(12);
            panel.BackColor = Color.White;

            var title = new Label();
            title.Dock = DockStyle.Top;
            title.Height = 30;
            title.Text = "全盘分析器";
            title.Font = new Font(Font, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(23, 37, 84);

            _moveList = new ListView();
            _moveList.Dock = DockStyle.Fill;
            _moveList.CheckBoxes = true;
            _moveList.View = View.Details;
            _moveList.FullRowSelect = true;
            _moveList.GridLines = true;
            _moveList.HideSelection = false;
            _moveList.Columns.Add("名称", 170);
            _moveList.Columns.Add("大小", 90);
            _moveList.Columns.Add("类型", 80);
            _moveList.Columns.Add("分类", 100);
            _moveList.Columns.Add("建议", 120);
            _moveList.Columns.Add("路径", 320);
            _moveList.Columns.Add("说明", 220);

            _scanMoveButton = new Button();
            _scanMoveButton.Text = "扫描 C 盘";
            _scanMoveButton.Width = 110;
            _scanMoveButton.Height = 34;
            _scanMoveButton.Click += async delegate { await RunMoveScanAsync(); };
            StylePrimaryButton(_scanMoveButton);

            _moveSelectedButton = new Button();
            _moveSelectedButton.Text = "搬移可选项";
            _moveSelectedButton.Width = 120;
            _moveSelectedButton.Height = 34;
            _moveSelectedButton.Click += async delegate { await RunMoveAsync(); };
            StyleAccentButton(_moveSelectedButton);

            _scanAppDataButton = new Button();
            _scanAppDataButton.Text = "分析 Local 归属";
            _scanAppDataButton.Width = 126;
            _scanAppDataButton.Height = 34;
            _scanAppDataButton.Click += async delegate { await RunAppDataAnalysisAsync(); };
            StyleLightButton(_scanAppDataButton);

            var buttons = new FlowLayoutPanel();
            buttons.Dock = DockStyle.Bottom;
            buttons.Height = 46;
            buttons.Padding = new Padding(0, 8, 0, 0);
            buttons.Controls.Add(_scanMoveButton);
            buttons.Controls.Add(_moveSelectedButton);
            buttons.Controls.Add(_scanAppDataButton);

            panel.Controls.Add(_moveList);
            panel.Controls.Add(buttons);
            panel.Controls.Add(title);
            return panel;
        }

        private Control BuildLogPanel()
        {
            var panel = new Panel();
            panel.Dock = DockStyle.Fill;
            panel.Padding = new Padding(12, 0, 12, 12);
            panel.BackColor = Color.FromArgb(244, 247, 251);

            var title = new Label();
            title.Dock = DockStyle.Top;
            title.Height = 24;
            title.Text = "运行日志";
            title.Font = new Font(Font, FontStyle.Bold);
            title.ForeColor = Color.FromArgb(55, 65, 81);

            _logBox = new TextBox();
            _logBox.Dock = DockStyle.Fill;
            _logBox.Multiline = true;
            _logBox.ReadOnly = true;
            _logBox.ScrollBars = ScrollBars.Vertical;
            _logBox.Font = new Font("Consolas", 10F, FontStyle.Regular, GraphicsUnit.Point);
            _logBox.BackColor = Color.FromArgb(250, 252, 255);

            panel.Controls.Add(_logBox);
            panel.Controls.Add(title);
            return panel;
        }

        private async Task RunCleanupScanAsync()
        {
            var selected = GetSelectedCleanupTargets();
            if (selected.Count == 0)
            {
                MessageBox.Show(this, "请至少勾选一个清理项目。", "未选择项目", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            SetBusy(true);
            AppendLog(string.Empty);
            AppendLog("开始扫描可清理项目...");

            var result = await Task.Run(delegate { return CleanupEngine.Scan(selected); });

            AppendLog(string.Format("扫描完成，预计可释放空间：{0}。", FormatBytes(result.TotalBytes)));
            foreach (var item in result.Items)
            {
                AppendLog(string.Format("[清理扫描] {0} | {1} | {2} 个文件 {3}", item.TargetName, FormatBytes(item.Bytes), item.FileCount, item.Note));
            }
            foreach (var error in result.Errors)
            {
                AppendLog(string.Format("  已跳过：{0}", error));
            }

            UpdateSummary(result.TotalBytes);
            SetBusy(false);
        }

        private async Task RunCleanupAsync()
        {
            var selected = GetSelectedCleanupTargets();
            if (selected.Count == 0)
            {
                MessageBox.Show(this, "请至少勾选一个清理项目。", "未选择项目", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            var confirm = MessageBox.Show(this, "工具将删除临时文件并清空回收站，是否继续？", "确认清理", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning);
            if (confirm != DialogResult.OK)
            {
                return;
            }

            SetBusy(true);
            AppendLog(string.Empty);
            AppendLog("开始执行清理...");

            var result = await Task.Run(delegate { return CleanupEngine.Clean(selected); });

            AppendLog(string.Format("清理完成，实际释放约：{0}。", FormatBytes(result.BytesDeleted)));
            foreach (var item in result.Items)
            {
                AppendLog(string.Format("[清理结果] {0} | {1} 个文件 | {2}", item.TargetName, item.FilesDeleted, FormatBytes(item.BytesDeleted)));
            }
            foreach (var error in result.Errors)
            {
                AppendLog(string.Format("  已跳过：{0}", error));
            }

            SetBusy(false);
        }

        private async Task RunMoveScanAsync()
        {
            _currentViewMode = AnalysisViewMode.Drive;
            SetBusy(true);
            AppendLog(string.Empty);
            AppendLog("开始分析 C 盘中的大文件和大目录，这一步可能需要一点时间...");

            var items = await Task.Run(delegate { return MoveEngine.ScanCandidates(); });
            PopulateMoveList(items);

            long total = items.Sum(delegate(MovableItem item) { return item.SizeBytes; });
            int movableCount = items.Count(delegate(MovableItem item) { return item.CanMove; });
            AppendLog(string.Format("分析完成，共找到 {0} 个项目，总计 {1}；其中 {2} 个建议可搬移。", items.Count, FormatBytes(total), movableCount));
            foreach (var item in items.Take(20))
            {
                AppendLog(string.Format("[分析结果] {0} | {1} | {2} | {3}", item.DisplayName, FormatBytes(item.SizeBytes), item.Advice, item.SourcePath));
            }
            if (items.Count > 20)
            {
                AppendLog(string.Format("其余 {0} 个候选项已显示在上方列表中。", items.Count - 20));
            }

            SetBusy(false);
        }

        private async Task RunAppDataAnalysisAsync()
        {
            _currentViewMode = AnalysisViewMode.AppDataLocal;
            SetBusy(true);
            AppendLog(string.Empty);
            AppendLog("开始分析 AppData\\Local 一级目录与软件归属，这一步会读取已安装软件信息...");

            var items = await Task.Run(delegate { return AppDataLocalAnalyzer.Scan(); });
            PopulateMoveList(items);

            long total = items.Sum(delegate(MovableItem item) { return item.SizeBytes; });
            int possibleOrphans = items.Count(delegate(MovableItem item) { return item.Advice == "可能残留"; });
            AppendLog(string.Format("分析完成，共识别 {0} 个目录，总计 {1}；其中 {2} 个目录疑似已无软件使用。", items.Count, FormatBytes(total), possibleOrphans));
            foreach (var item in items.Take(20))
            {
                AppendLog(string.Format("[Local归属] {0} | {1} | {2} | {3}", item.DisplayName, item.Category, item.Advice, item.Note));
            }
            if (items.Count > 20)
            {
                AppendLog(string.Format("其余 {0} 个目录已显示在上方列表中。", items.Count - 20));
            }

            SetBusy(false);
        }

        private async Task RunMoveAsync()
        {
            var selected = GetSelectedMoveItems();
            if (selected.Count == 0)
            {
                MessageBox.Show(this, "请至少勾选一个要搬移的项目。", "未选择项目", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            var blocked = selected.Where(delegate(MovableItem item) { return !item.CanMove; }).ToList();
            if (blocked.Count > 0)
            {
                MessageBox.Show(this, "选中的项目里包含不建议直接搬移的系统或程序目录，请先取消勾选这些项目。", "包含高风险项目", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "请选择非系统盘上的目标目录。";
                dialog.ShowNewFolderButton = true;
                if (dialog.ShowDialog(this) != DialogResult.OK)
                {
                    return;
                }

                var destinationRoot = dialog.SelectedPath;
                if (string.IsNullOrWhiteSpace(destinationRoot))
                {
                    return;
                }

                if (string.Equals(Path.GetPathRoot(destinationRoot), @"C:\", StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show(this, "目标目录不能放在 C 盘，请选择其他磁盘。", "目标目录无效", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }

                var confirm = MessageBox.Show(this, "工具会先复制所选项目，复制成功后才删除原位置内容。是否继续？", "确认搬移", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning);
                if (confirm != DialogResult.OK)
                {
                    return;
                }

                SetBusy(true);
                AppendLog(string.Empty);
                AppendLog(string.Format("开始搬移 {0} 个项目到：{1}", selected.Count, destinationRoot));

                var result = await Task.Run(delegate { return MoveEngine.MoveItems(selected, destinationRoot); });

                foreach (var item in result.Items)
                {
                    AppendLog(string.Format("[搬移结果] {0} -> {1} | {2}", item.SourcePath, item.DestinationPath, item.Message));
                }
                foreach (var error in result.Errors)
                {
                    AppendLog(string.Format("  失败：{0}", error));
                }
                AppendLog(string.Format("搬移完成，成功处理 {0} 个项目，总计 {1}。", result.SuccessCount, FormatBytes(result.BytesMoved)));

                SetBusy(false);
                await RunMoveScanAsync();
            }
        }

        private void PopulateMoveList(List<MovableItem> items)
        {
            _moveList.BeginUpdate();
            _moveList.Items.Clear();
            _moveSelectedButton.Visible = _currentViewMode != AnalysisViewMode.AppDataLocal;
            foreach (var item in items.OrderByDescending(delegate(MovableItem x) { return x.SizeBytes; }))
            {
                var row = new ListViewItem(item.DisplayName);
                row.Tag = item;
                row.SubItems.Add(FormatBytes(item.SizeBytes));
                row.SubItems.Add(item.IsDirectory ? "目录" : "文件");
                row.SubItems.Add(item.Category);
                row.SubItems.Add(item.Advice);
                row.SubItems.Add(item.SourcePath);
                row.SubItems.Add(item.Note);
                row.Checked = _currentViewMode != AnalysisViewMode.AppDataLocal && item.CanMove;
                _moveList.Items.Add(row);
            }
            _moveList.EndUpdate();
        }

        private List<CleanupTarget> GetSelectedCleanupTargets()
        {
            return _cleanupList.CheckedItems.Cast<CleanupTarget>().ToList();
        }

        private List<MovableItem> GetSelectedMoveItems()
        {
            var result = new List<MovableItem>();
            foreach (ListViewItem item in _moveList.Items)
            {
                if (item.Checked && item.Tag is MovableItem)
                {
                    result.Add((MovableItem)item.Tag);
                }
            }
            return result;
        }

        private void SetBusy(bool busy)
        {
            UseWaitCursor = busy;
            _scanCleanupButton.Enabled = !busy;
            _runCleanupButton.Enabled = !busy;
            _scanMoveButton.Enabled = !busy;
            _moveSelectedButton.Enabled = !busy;
            _scanAppDataButton.Enabled = !busy;
            _cleanupList.Enabled = !busy;
            _moveList.Enabled = !busy;
            _moveSelectedButton.Visible = _currentViewMode != AnalysisViewMode.AppDataLocal;
        }

        private void UpdateSummary(long reclaimableBytes)
        {
            _summaryLabel.Text = string.Format("{0}  |  预计可清理：{1}", BuildPrivilegeText(), FormatBytes(reclaimableBytes));
        }

        private string BuildPrivilegeText()
        {
            return IsAdministrator() ? "当前权限：管理员" : "当前权限：普通用户";
        }

        private static bool IsAdministrator()
        {
            WindowsIdentity identity = WindowsIdentity.GetCurrent();
            WindowsPrincipal principal = new WindowsPrincipal(identity);
            return principal.IsInRole(WindowsBuiltInRole.Administrator);
        }

        private void AppendLog(string text)
        {
            _logBox.AppendText(text + Environment.NewLine);
        }

        private static void StylePrimaryButton(Button button)
        {
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 0;
            button.BackColor = Color.FromArgb(37, 99, 235);
            button.ForeColor = Color.White;
        }

        private static void StyleAccentButton(Button button)
        {
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 0;
            button.BackColor = Color.FromArgb(15, 118, 110);
            button.ForeColor = Color.White;
        }

        private static void StyleLightButton(Button button)
        {
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderColor = Color.FromArgb(191, 219, 254);
            button.BackColor = Color.FromArgb(239, 246, 255);
            button.ForeColor = Color.FromArgb(30, 64, 175);
        }

        private static string FormatBytes(long bytes)
        {
            if (bytes <= 0)
            {
                return "0 B";
            }

            string[] units = new[] { "B", "KB", "MB", "GB", "TB" };
            double size = bytes;
            int order = 0;
            while (size >= 1024 && order < units.Length - 1)
            {
                order++;
                size /= 1024;
            }
            return string.Format("{0:0.##} {1}", size, units[order]);
        }
    }

    internal sealed class CleanupTarget
    {
        private readonly string _name;
        private readonly string _description;
        private readonly Action<CleanupCollector> _scanAction;
        private readonly Action<CleanupCollector> _cleanAction;

        public CleanupTarget(string name, string description, Action<CleanupCollector> scanAction, Action<CleanupCollector> cleanAction)
        {
            _name = name;
            _description = description;
            _scanAction = scanAction;
            _cleanAction = cleanAction;
        }

        public string Name { get { return _name; } }
        public string Description { get { return _description; } }
        public Action<CleanupCollector> ScanAction { get { return _scanAction; } }
        public Action<CleanupCollector> CleanAction { get { return _cleanAction; } }

        public override string ToString()
        {
            return string.Format("{0} - {1}", Name, Description);
        }
    }

    internal static class CleanupTargetFactory
    {
        public static List<CleanupTarget> Create()
        {
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            string programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);

            return new List<CleanupTarget>
            {
                new CleanupTarget("用户临时文件", "清理 %TEMP% 中超过 1 天的临时文件。",
                    delegate(CleanupCollector c) { c.CollectDirectory(Path.GetTempPath(), 1, "*"); },
                    delegate(CleanupCollector c) { c.DeleteDirectoryContent(Path.GetTempPath(), 1, "*"); }),
                new CleanupTarget("Windows 临时目录", "清理 C:\\Windows\\Temp 中超过 1 天的临时文件。",
                    delegate(CleanupCollector c) { c.CollectDirectory(Path.Combine(windows, "Temp"), 1, "*"); },
                    delegate(CleanupCollector c) { c.DeleteDirectoryContent(Path.Combine(windows, "Temp"), 1, "*"); }),
                new CleanupTarget("Windows 更新缓存", "清理已下载的系统更新缓存。",
                    delegate(CleanupCollector c) { c.CollectDirectory(Path.Combine(windows, "SoftwareDistribution", "Download"), 0, "*"); },
                    delegate(CleanupCollector c) { c.DeleteDirectoryContent(Path.Combine(windows, "SoftwareDistribution", "Download"), 0, "*"); }),
                new CleanupTarget("传递优化缓存", "清理系统更新分发缓存。",
                    delegate(CleanupCollector c) { c.CollectDirectory(Path.Combine(programData, "Microsoft", "Windows", "DeliveryOptimization", "Cache"), 0, "*"); },
                    delegate(CleanupCollector c) { c.DeleteDirectoryContent(Path.Combine(programData, "Microsoft", "Windows", "DeliveryOptimization", "Cache"), 0, "*"); }),
                new CleanupTarget("系统日志与转储", "清理 CBS 日志、蓝屏转储和 MEMORY.DMP。",
                    delegate(CleanupCollector c)
                    {
                        c.CollectDirectory(Path.Combine(windows, "Logs", "CBS"), 0, "*.log");
                        c.CollectDirectory(Path.Combine(windows, "Minidump"), 0, "*");
                        c.CollectFile(Path.Combine(windows, "MEMORY.DMP"));
                    },
                    delegate(CleanupCollector c)
                    {
                        c.DeleteDirectoryContent(Path.Combine(windows, "Logs", "CBS"), 0, "*.log");
                        c.DeleteDirectoryContent(Path.Combine(windows, "Minidump"), 0, "*");
                        c.DeleteFile(Path.Combine(windows, "MEMORY.DMP"));
                    }),
                new CleanupTarget("回收站", "清空回收站中的内容。",
                    delegate(CleanupCollector c) { c.CollectRecycleBin(); },
                    delegate(CleanupCollector c) { c.EmptyRecycleBin(); })
            };
        }
    }

    internal sealed class CleanupCollector
    {
        private readonly List<string> _errors = new List<string>();

        public long BytesFound { get; private set; }
        public int FilesFound { get; private set; }
        public long BytesDeleted { get; private set; }
        public int FilesDeleted { get; private set; }
        public string Note { get; private set; }
        public List<string> Errors { get { return _errors; } }

        public void CollectDirectory(string path, int minAgeDays, string pattern)
        {
            if (!Directory.Exists(path))
            {
                Note = "目录不存在";
                return;
            }

            foreach (var file in EnumerateFilesSafe(path, pattern))
            {
                try
                {
                    var info = new FileInfo(file);
                    if (IsOldEnough(info, minAgeDays))
                    {
                        BytesFound += info.Length;
                        FilesFound++;
                    }
                }
                catch (Exception ex)
                {
                    Errors.Add(file + " | " + ex.Message);
                }
            }
        }

        public void DeleteDirectoryContent(string path, int minAgeDays, string pattern)
        {
            if (!Directory.Exists(path))
            {
                Note = "目录不存在";
                return;
            }

            foreach (var file in EnumerateFilesSafe(path, pattern))
            {
                try
                {
                    var info = new FileInfo(file);
                    if (!IsOldEnough(info, minAgeDays))
                    {
                        continue;
                    }

                    long size = info.Length;
                    info.IsReadOnly = false;
                    info.Delete();
                    BytesDeleted += size;
                    FilesDeleted++;
                }
                catch (Exception ex)
                {
                    Errors.Add(file + " | " + ex.Message);
                }
            }
        }

        public void CollectFile(string path)
        {
            if (!File.Exists(path))
            {
                return;
            }

            try
            {
                var info = new FileInfo(path);
                BytesFound += info.Length;
                FilesFound++;
            }
            catch (Exception ex)
            {
                Errors.Add(path + " | " + ex.Message);
            }
        }

        public void DeleteFile(string path)
        {
            if (!File.Exists(path))
            {
                return;
            }

            try
            {
                var info = new FileInfo(path);
                long size = info.Length;
                info.IsReadOnly = false;
                info.Delete();
                BytesDeleted += size;
                FilesDeleted++;
            }
            catch (Exception ex)
            {
                Errors.Add(path + " | " + ex.Message);
            }
        }

        public void CollectRecycleBin()
        {
            var info = new SHQUERYRBINFO();
            info.cbSize = Marshal.SizeOf(typeof(SHQUERYRBINFO));
            int hr = SHQueryRecycleBin(null, ref info);
            if (hr != 0)
            {
                Errors.Add("读取回收站失败，错误码：" + hr);
                return;
            }

            BytesFound += info.i64Size;
            FilesFound += (int)Math.Min(info.i64NumItems, int.MaxValue);
        }

        public void EmptyRecycleBin()
        {
            var info = new SHQUERYRBINFO();
            info.cbSize = Marshal.SizeOf(typeof(SHQUERYRBINFO));
            if (SHQueryRecycleBin(null, ref info) == 0)
            {
                BytesDeleted += info.i64Size;
                FilesDeleted += (int)Math.Min(info.i64NumItems, int.MaxValue);
            }

            int flags = 0x1 | 0x2 | 0x4;
            int hr = SHEmptyRecycleBin(IntPtr.Zero, null, flags);
            if (hr != 0)
            {
                Errors.Add("清空回收站失败，错误码：" + hr);
            }
        }

        private static bool IsOldEnough(FileInfo info, int minAgeDays)
        {
            if (minAgeDays <= 0)
            {
                return true;
            }
            return info.LastWriteTimeUtc <= DateTime.UtcNow.AddDays(-minAgeDays);
        }

        private IEnumerable<string> EnumerateFilesSafe(string root, string pattern)
        {
            var stack = new Stack<string>();
            stack.Push(root);

            while (stack.Count > 0)
            {
                string current = stack.Pop();

                IEnumerable<string> files = Enumerable.Empty<string>();
                try
                {
                    files = Directory.EnumerateFiles(current, pattern, SearchOption.TopDirectoryOnly);
                }
                catch (Exception ex)
                {
                    Errors.Add(current + " | " + ex.Message);
                }

                foreach (var file in files)
                {
                    yield return file;
                }

                IEnumerable<string> dirs = Enumerable.Empty<string>();
                try
                {
                    dirs = Directory.EnumerateDirectories(current, "*", SearchOption.TopDirectoryOnly);
                }
                catch (Exception ex)
                {
                    Errors.Add(current + " | " + ex.Message);
                }

                foreach (var dir in dirs)
                {
                    stack.Push(dir);
                }
            }
        }

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct SHQUERYRBINFO
        {
            public int cbSize;
            public long i64Size;
            public long i64NumItems;
        }

        [DllImport("Shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHQueryRecycleBin(string pszRootPath, ref SHQUERYRBINFO pSHQueryRBInfo);

        [DllImport("Shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SHEmptyRecycleBin(IntPtr hwnd, string pszRootPath, int dwFlags);
    }

    internal static class CleanupEngine
    {
        public static CleanupScanResult Scan(IEnumerable<CleanupTarget> targets)
        {
            var result = new CleanupScanResult();
            foreach (var target in targets)
            {
                var collector = new CleanupCollector();
                target.ScanAction(collector);
                result.Items.Add(new CleanupScanItem
                {
                    TargetName = target.Name,
                    Bytes = collector.BytesFound,
                    FileCount = collector.FilesFound,
                    Note = collector.Note ?? string.Empty
                });
                result.TotalBytes += collector.BytesFound;
                result.Errors.AddRange(collector.Errors.Select(delegate(string x) { return target.Name + ": " + x; }));
            }
            return result;
        }

        public static CleanupExecutionResult Clean(IEnumerable<CleanupTarget> targets)
        {
            var result = new CleanupExecutionResult();
            foreach (var target in targets)
            {
                var collector = new CleanupCollector();
                target.CleanAction(collector);
                result.Items.Add(new CleanupExecutionItem
                {
                    TargetName = target.Name,
                    BytesDeleted = collector.BytesDeleted,
                    FilesDeleted = collector.FilesDeleted
                });
                result.BytesDeleted += collector.BytesDeleted;
                result.Errors.AddRange(collector.Errors.Select(delegate(string x) { return target.Name + ": " + x; }));
            }
            return result;
        }
    }

    internal sealed class CleanupScanResult
    {
        public CleanupScanResult()
        {
            Items = new List<CleanupScanItem>();
            Errors = new List<string>();
        }

        public long TotalBytes { get; set; }
        public List<CleanupScanItem> Items { get; set; }
        public List<string> Errors { get; set; }
    }

    internal sealed class CleanupScanItem
    {
        public string TargetName { get; set; }
        public long Bytes { get; set; }
        public int FileCount { get; set; }
        public string Note { get; set; }
    }

    internal sealed class CleanupExecutionResult
    {
        public CleanupExecutionResult()
        {
            Items = new List<CleanupExecutionItem>();
            Errors = new List<string>();
        }

        public long BytesDeleted { get; set; }
        public List<CleanupExecutionItem> Items { get; set; }
        public List<string> Errors { get; set; }
    }

    internal sealed class CleanupExecutionItem
    {
        public string TargetName { get; set; }
        public long BytesDeleted { get; set; }
        public int FilesDeleted { get; set; }
    }

    internal sealed class MovableItem
    {
        public string DisplayName { get; set; }
        public string SourcePath { get; set; }
        public string Category { get; set; }
        public string Advice { get; set; }
        public string Note { get; set; }
        public bool IsDirectory { get; set; }
        public bool CanMove { get; set; }
        public long SizeBytes { get; set; }
    }

    internal enum AnalysisViewMode
    {
        Drive,
        AppDataLocal
    }

    internal sealed class MoveResult
    {
        public MoveResult()
        {
            Items = new List<MoveResultItem>();
            Errors = new List<string>();
        }

        public int SuccessCount { get; set; }
        public long BytesMoved { get; set; }
        public List<MoveResultItem> Items { get; set; }
        public List<string> Errors { get; set; }
    }

    internal sealed class MoveResultItem
    {
        public string SourcePath { get; set; }
        public string DestinationPath { get; set; }
        public string Message { get; set; }
    }

    internal static class AppDataLocalAnalyzer
    {
        public static List<MovableItem> Scan()
        {
            string root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var installedApps = LoadInstalledApps();
            var packageNames = LoadPackageNames(Path.Combine(root, "Packages"));
            var items = new List<MovableItem>();

            foreach (string dir in SafeEnumerateDirectories(root))
            {
                string name = Path.GetFileName(dir);
                long size = TryGetDirectorySize(dir, 2);
                var match = MatchFolder(name, dir, installedApps, packageNames);

                items.Add(new MovableItem
                {
                    DisplayName = name,
                    SourcePath = dir,
                    Category = match.SoftwareName,
                    Advice = match.Advice,
                    Note = string.Format("置信度：{0} | {1}", match.Confidence, match.Note),
                    IsDirectory = true,
                    CanMove = false,
                    SizeBytes = size
                });
            }

            return items
                .OrderByDescending(delegate(MovableItem item) { return item.SizeBytes; })
                .ToList();
        }

        private static FolderMatch MatchFolder(string folderName, string fullPath, List<InstalledAppInfo> installedApps, HashSet<string> packageNames)
        {
            string lower = folderName.ToLowerInvariant();
            string pathLower = fullPath.ToLowerInvariant();

            if (folderName == "Temp" || folderName == "SquirrelTemp" || folderName == "D3DSCache" || folderName == "CrashDumps")
            {
                return new FolderMatch("系统缓存/临时文件", "可清理", "高", "缓存或转储目录，通常不依赖已安装软件。");
            }

            if (folderName == "Packages")
            {
                return new FolderMatch("Microsoft Store 应用容器", "谨慎处理", "高", "容器里是商店应用数据，建议只进一步分析子目录，不要整目录删除。");
            }

            if (folderName == "Microsoft" || folderName == "ConnectedDevicesPlatform" || folderName == "Comms" || folderName == "VirtualStore")
            {
                return new FolderMatch("Windows 系统组件", "谨慎处理", "高", "系统或兼容性目录，不建议直接删除。");
            }

            if (lower.Contains("cache") || lower.Contains("updater") || lower.Contains("update"))
            {
                string appName = FindBestInstalledApp(folderName, installedApps) ?? folderName;
                return new FolderMatch(appName, "优先检查", "中", "看起来是缓存或更新器目录，若对应软件已卸载，通常可清理。");
            }

            if (packageNames.Contains(folderName))
            {
                return new FolderMatch(folderName, "谨慎处理", "高", "这是商店应用包目录名，建议按具体应用判断。");
            }

            InstalledAppInfo exact = installedApps.FirstOrDefault(delegate(InstalledAppInfo app)
            {
                return Normalize(app.DisplayName) == Normalize(folderName);
            });
            if (exact != null)
            {
                return new FolderMatch(exact.DisplayName, "正在使用", "高", BuildInstallNote(exact));
            }

            InstalledAppInfo partial = installedApps.FirstOrDefault(delegate(InstalledAppInfo app)
            {
                string display = Normalize(app.DisplayName);
                string folder = Normalize(folderName);
                return display.Contains(folder) || folder.Contains(display);
            });
            if (partial != null)
            {
                return new FolderMatch(partial.DisplayName, "大概率关联", "中", BuildInstallNote(partial));
            }

            if (pathLower.Contains("\\google") || pathLower.Contains("\\jetbrains") || pathLower.Contains("\\docker") || pathLower.Contains("\\tencent") || pathLower.Contains("\\nvidia"))
            {
                return new FolderMatch(folderName, "大概率关联", "中", "目录名与常见厂商一致，通常仍在被软件使用。");
            }

            if (folderName == "pip" || folderName == "npm-cache" || folderName == "pnpm-cache" || folderName == "Yarn" || folderName == "node-gyp" || folderName == "pnpm" || folderName == "pnpm-state")
            {
                return new FolderMatch("开发工具缓存", "可清理", "高", "包管理器缓存目录，通常不影响已安装软件运行。");
            }

            if (folderName == "Programs")
            {
                return new FolderMatch("用户级安装目录", "谨慎处理", "高", "这里常存放按用户安装的软件程序本体，不要直接删除。");
            }

            return new FolderMatch("未明确识别", "可能残留", "低", "没有匹配到已安装软件。若你确认软件已卸载，可先备份后清理。");
        }

        private static string BuildInstallNote(InstalledAppInfo app)
        {
            if (!string.IsNullOrWhiteSpace(app.Publisher))
            {
                return "已匹配安装软件，发布者：" + app.Publisher;
            }
            return "已匹配安装软件。";
        }

        private static string FindBestInstalledApp(string folderName, List<InstalledAppInfo> installedApps)
        {
            InstalledAppInfo app = installedApps.FirstOrDefault(delegate(InstalledAppInfo x)
            {
                return Normalize(x.DisplayName).Contains(Normalize(folderName)) || Normalize(folderName).Contains(Normalize(x.DisplayName));
            });
            return app != null ? app.DisplayName : null;
        }

        private static string Normalize(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return string.Empty;
            }

            var chars = value.ToLowerInvariant().Where(delegate(char c)
            {
                return char.IsLetterOrDigit(c);
            });
            return new string(chars.ToArray());
        }

        private static List<InstalledAppInfo> LoadInstalledApps()
        {
            var result = new List<InstalledAppInfo>();
            string[] roots = new[]
            {
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
            };

            LoadInstalledAppsFromHive(Registry.LocalMachine, roots, result);
            LoadInstalledAppsFromHive(Registry.CurrentUser, new[] { @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" }, result);

            return result
                .Where(delegate(InstalledAppInfo item) { return !string.IsNullOrWhiteSpace(item.DisplayName); })
                .GroupBy(delegate(InstalledAppInfo item) { return item.DisplayName; })
                .Select(delegate(IGrouping<string, InstalledAppInfo> group) { return group.First(); })
                .ToList();
        }

        private static void LoadInstalledAppsFromHive(RegistryKey hive, IEnumerable<string> paths, List<InstalledAppInfo> result)
        {
            foreach (string path in paths)
            {
                using (RegistryKey key = hive.OpenSubKey(path))
                {
                    if (key == null)
                    {
                        continue;
                    }

                    foreach (string subName in key.GetSubKeyNames())
                    {
                        using (RegistryKey subKey = key.OpenSubKey(subName))
                        {
                            if (subKey == null)
                            {
                                continue;
                            }

                            string displayName = Convert.ToString(subKey.GetValue("DisplayName"));
                            if (string.IsNullOrWhiteSpace(displayName))
                            {
                                continue;
                            }

                            result.Add(new InstalledAppInfo
                            {
                                DisplayName = displayName,
                                Publisher = Convert.ToString(subKey.GetValue("Publisher")),
                                InstallLocation = Convert.ToString(subKey.GetValue("InstallLocation"))
                            });
                        }
                    }
                }
            }
        }

        private static HashSet<string> LoadPackageNames(string packagesPath)
        {
            return new HashSet<string>(SafeEnumerateDirectories(packagesPath).Select(Path.GetFileName), StringComparer.OrdinalIgnoreCase);
        }

        private static IEnumerable<string> SafeEnumerateDirectories(string root)
        {
            try
            {
                return Directory.EnumerateDirectories(root, "*", SearchOption.TopDirectoryOnly).ToList();
            }
            catch
            {
                return new string[0];
            }
        }

        private static long TryGetDirectorySize(string root, int maxDepth)
        {
            long total = 0;
            var stack = new Stack<DirectoryDepthItem>();
            stack.Push(new DirectoryDepthItem(root, 0));

            while (stack.Count > 0)
            {
                DirectoryDepthItem current = stack.Pop();
                try
                {
                    foreach (string file in Directory.EnumerateFiles(current.Path, "*", SearchOption.TopDirectoryOnly))
                    {
                        try
                        {
                            total += new FileInfo(file).Length;
                        }
                        catch
                        {
                        }
                    }

                    if (current.Depth >= maxDepth)
                    {
                        continue;
                    }

                    foreach (string dir in Directory.EnumerateDirectories(current.Path, "*", SearchOption.TopDirectoryOnly))
                    {
                        stack.Push(new DirectoryDepthItem(dir, current.Depth + 1));
                    }
                }
                catch
                {
                }
            }

            return total;
        }

        private sealed class DirectoryDepthItem
        {
            public DirectoryDepthItem(string path, int depth)
            {
                Path = path;
                Depth = depth;
            }

            public string Path { get; private set; }
            public int Depth { get; private set; }
        }

        private sealed class FolderMatch
        {
            public FolderMatch(string softwareName, string advice, string confidence, string note)
            {
                SoftwareName = softwareName;
                Advice = advice;
                Confidence = confidence;
                Note = note;
            }

            public string SoftwareName { get; private set; }
            public string Advice { get; private set; }
            public string Confidence { get; private set; }
            public string Note { get; private set; }
        }

        private sealed class InstalledAppInfo
        {
            public string DisplayName { get; set; }
            public string Publisher { get; set; }
            public string InstallLocation { get; set; }
        }
    }

    internal static class MoveEngine
    {
        private const long LargeFileThreshold = 300L * 1024 * 1024;
        private const long LargeFolderThreshold = 1024L * 1024 * 1024;
        private const int MaxResultCount = 220;

        public static List<MovableItem> ScanCandidates()
        {
            var items = new List<MovableItem>();
            string root = Path.GetPathRoot(Environment.SystemDirectory);
            AddKnownHeavyHitters(items, root);
            AnalyzeDirectory(root, items, true);

            return items
                .GroupBy(delegate(MovableItem item) { return item.SourcePath; })
                .Select(delegate(IGrouping<string, MovableItem> group) { return group.OrderByDescending(delegate(MovableItem item) { return item.SizeBytes; }).First(); })
                .OrderByDescending(delegate(MovableItem x) { return x.SizeBytes; })
                .Take(MaxResultCount)
                .ToList();
        }

        private static void AddKnownHeavyHitters(List<MovableItem> items, string root)
        {
            string user = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string roamingAppData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            string programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);

            AddKnownFile(items, Path.Combine(root, "hiberfil.sys"));
            AddKnownFile(items, Path.Combine(root, "pagefile.sys"));
            AddKnownFile(items, Path.Combine(root, "swapfile.sys"));

            AddKnownDirectory(items, Path.Combine(windows, "WinSxS"));
            AddKnownDirectory(items, Path.Combine(windows, "Installer"));
            AddKnownDirectory(items, Path.Combine(windows, "SoftwareDistribution"));
            AddKnownDirectory(items, Path.Combine(root, "System Volume Information"));
            AddKnownDirectory(items, Path.Combine(programData));
            AddKnownDirectory(items, Path.Combine(localAppData));
            AddKnownDirectory(items, Path.Combine(roamingAppData));
            AddKnownDirectory(items, Path.Combine(user, "Downloads"));
            AddKnownDirectory(items, Path.Combine(user, "Desktop"));
            AddKnownDirectory(items, Path.Combine(user, "Documents"));
            AddKnownDirectory(items, Path.Combine(user, "Pictures"));
            AddKnownDirectory(items, Path.Combine(user, "Videos"));
        }

        private static void AddKnownFile(List<MovableItem> items, string path)
        {
            try
            {
                if (!File.Exists(path))
                {
                    return;
                }

                FileInfo info = new FileInfo(path);
                items.Add(BuildItem(path, info.Length, false));
            }
            catch
            {
            }
        }

        private static void AddKnownDirectory(List<MovableItem> items, string path)
        {
            try
            {
                if (!Directory.Exists(path))
                {
                    return;
                }

                long size = TryGetDirectorySize(path, 2);
                if (size <= 0)
                {
                    return;
                }

                items.Add(BuildItem(path, size, true));
            }
            catch
            {
            }
        }

        public static MoveResult MoveItems(List<MovableItem> items, string destinationRoot)
        {
            var result = new MoveResult();
            Directory.CreateDirectory(destinationRoot);

            foreach (var item in items)
            {
                try
                {
                    string categoryFolder = MakeSafeName(item.Category);
                    string targetBase = Path.Combine(destinationRoot, categoryFolder);
                    Directory.CreateDirectory(targetBase);

                    string targetPath = GetAvailablePath(Path.Combine(targetBase, Path.GetFileName(item.SourcePath)));
                    EnsureDestinationOutsideSource(item.SourcePath, targetPath);

                    if (item.IsDirectory)
                    {
                        CopyDirectory(item.SourcePath, targetPath);
                        Directory.Delete(item.SourcePath, true);
                    }
                    else
                    {
                        File.Copy(item.SourcePath, targetPath);
                        File.Delete(item.SourcePath);
                    }

                    result.SuccessCount++;
                    result.BytesMoved += item.SizeBytes;
                    result.Items.Add(new MoveResultItem
                    {
                        SourcePath = item.SourcePath,
                        DestinationPath = targetPath,
                        Message = "成功"
                    });
                }
                catch (Exception ex)
                {
                    result.Errors.Add(item.SourcePath + " | " + ex.Message);
                }
            }

            return result;
        }

        private static long AnalyzeDirectory(string root, List<MovableItem> items, bool isRoot)
        {
            if (!Directory.Exists(root))
            {
                return 0;
            }

            long total = 0;

            foreach (var file in SafeEnumerateFiles(root))
            {
                try
                {
                    var info = new FileInfo(file);
                    total += info.Length;
                    if (info.Length >= LargeFileThreshold)
                    {
                        items.Add(BuildItem(file, info.Length, false));
                    }
                }
                catch
                {
                }
            }

            foreach (var dir in SafeEnumerateDirectories(root))
            {
                if (IsReparsePoint(dir))
                {
                    continue;
                }

                total += AnalyzeDirectory(dir, items, false);
            }

            if (!isRoot && total >= LargeFolderThreshold)
            {
                items.Add(BuildItem(root, total, true));
            }

            return total;
        }

        private static MovableItem BuildItem(string path, long sizeBytes, bool isDirectory)
        {
            string category = ClassifyCategory(path, isDirectory);
            bool canMove = IsMoveRecommended(path, isDirectory);
            string advice = canMove ? "建议搬移" : "谨慎处理";
            string note = BuildNote(path, isDirectory, canMove);

            return new MovableItem
            {
                DisplayName = isDirectory ? Path.GetFileName(path.TrimEnd('\\')) : Path.GetFileName(path),
                SourcePath = path,
                Category = category,
                Advice = advice,
                Note = note,
                IsDirectory = isDirectory,
                CanMove = canMove,
                SizeBytes = sizeBytes
            };
        }

        private static IEnumerable<string> SafeEnumerateDirectories(string root)
        {
            try
            {
                return Directory.EnumerateDirectories(root, "*", SearchOption.TopDirectoryOnly).ToList();
            }
            catch
            {
                return new string[0];
            }
        }

        private static IEnumerable<string> SafeEnumerateFiles(string root)
        {
            try
            {
                return Directory.EnumerateFiles(root, "*", SearchOption.TopDirectoryOnly).ToList();
            }
            catch
            {
                return new string[0];
            }
        }

        private static bool IsReparsePoint(string path)
        {
            try
            {
                return (File.GetAttributes(path) & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint;
            }
            catch
            {
                return true;
            }
        }

        private static string MakeSafeName(string value)
        {
            foreach (char c in Path.GetInvalidFileNameChars())
            {
                value = value.Replace(c, '_');
            }
            return value;
        }

        private static string GetAvailablePath(string path)
        {
            if (!File.Exists(path) && !Directory.Exists(path))
            {
                return path;
            }

            string directory = Path.GetDirectoryName(path);
            string name = Path.GetFileNameWithoutExtension(path);
            string ext = Path.GetExtension(path);
            int index = 1;

            while (true)
            {
                string candidate = Path.Combine(directory, name + "_" + index + ext);
                if (!File.Exists(candidate) && !Directory.Exists(candidate))
                {
                    return candidate;
                }
                index++;
            }
        }

        private static void EnsureDestinationOutsideSource(string sourcePath, string destinationPath)
        {
            string sourceFull = Path.GetFullPath(sourcePath).TrimEnd('\\') + "\\";
            string destinationFull = Path.GetFullPath(destinationPath).TrimEnd('\\') + "\\";
            if (destinationFull.StartsWith(sourceFull, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("目标目录不能位于源目录内部。");
            }
        }

        private static void CopyDirectory(string sourceDir, string destDir)
        {
            Directory.CreateDirectory(destDir);

            foreach (var file in Directory.EnumerateFiles(sourceDir, "*", SearchOption.TopDirectoryOnly))
            {
                string targetFile = Path.Combine(destDir, Path.GetFileName(file));
                File.Copy(file, targetFile);
            }

            foreach (var directory in Directory.EnumerateDirectories(sourceDir, "*", SearchOption.TopDirectoryOnly))
            {
                string targetSubDir = Path.Combine(destDir, Path.GetFileName(directory));
                CopyDirectory(directory, targetSubDir);
            }
        }

        private static string ClassifyCategory(string path, bool isDirectory)
        {
            string lower = path.ToLowerInvariant();

            if (lower.EndsWith("\\hiberfil.sys"))
            {
                return "休眠文件";
            }

            if (lower.EndsWith("\\pagefile.sys") || lower.EndsWith("\\swapfile.sys"))
            {
                return "虚拟内存";
            }

            if (lower.Contains("\\winsxs"))
            {
                return "系统组件";
            }

            if (lower.Contains("\\system volume information"))
            {
                return "系统还原";
            }

            if (lower.Contains("\\windows\\"))
            {
                return "系统";
            }

            if (lower.Contains("\\program files") || lower.Contains("\\programdata\\"))
            {
                return "程序";
            }

            if (lower.Contains("\\downloads\\"))
            {
                return "下载";
            }

            if (lower.Contains("\\desktop\\"))
            {
                return "桌面";
            }

            if (lower.Contains("\\videos\\") || lower.Contains("\\pictures\\") || lower.Contains("\\music\\"))
            {
                return "媒体";
            }

            if (lower.Contains("\\documents\\wechat files") || lower.Contains("\\documents\\tencent files"))
            {
                return "聊天数据";
            }

            if (lower.Contains("\\appdata\\local\\packages"))
            {
                return "商店应用";
            }

            if (lower.Contains("\\appdata\\"))
            {
                return "应用数据";
            }

            if (!isDirectory)
            {
                string ext = Path.GetExtension(path).ToLowerInvariant();
                if (ext == ".zip" || ext == ".rar" || ext == ".7z" || ext == ".iso")
                {
                    return "压缩包";
                }

                if (ext == ".mp4" || ext == ".mkv" || ext == ".avi" || ext == ".mov")
                {
                    return "视频";
                }

                if (ext == ".msi" || ext == ".exe")
                {
                    return "安装包";
                }
            }

            return "其他";
        }

        private static bool IsMoveRecommended(string path, bool isDirectory)
        {
            string lower = path.ToLowerInvariant();

            if (lower.EndsWith("\\hiberfil.sys") || lower.EndsWith("\\pagefile.sys") || lower.EndsWith("\\swapfile.sys"))
            {
                return false;
            }

            if (lower.Contains("\\windows\\") || lower.StartsWith(@"c:\windows"))
            {
                return false;
            }

            if (lower.Contains("\\program files") || lower.StartsWith(@"c:\program files") || lower.StartsWith(@"c:\programdata"))
            {
                return false;
            }

            if (lower.Contains("\\appdata\\local\\packages"))
            {
                return false;
            }

            if (lower.Contains("\\downloads\\") || lower.Contains("\\desktop\\") || lower.Contains("\\videos\\") || lower.Contains("\\music\\") || lower.Contains("\\pictures\\"))
            {
                return true;
            }

            if (lower.Contains("\\documents\\wechat files") || lower.Contains("\\documents\\tencent files"))
            {
                return true;
            }

            if (!isDirectory && lower.Contains("\\documents\\"))
            {
                return true;
            }

            if (!isDirectory && lower.EndsWith(".zip"))
            {
                return true;
            }

            return false;
        }

        private static string BuildNote(string path, bool isDirectory, bool canMove)
        {
            string lower = path.ToLowerInvariant();

            if (!canMove)
            {
                if (lower.EndsWith("\\hiberfil.sys"))
                {
                    return "这是休眠文件，通常会占用很多空间。可通过关闭系统休眠来释放，但不是直接搬移。";
                }

                if (lower.EndsWith("\\pagefile.sys") || lower.EndsWith("\\swapfile.sys"))
                {
                    return "这是虚拟内存文件，可调整大小或迁移到其他盘，但需要在系统高级设置里修改。";
                }

                if (lower.Contains("\\winsxs"))
                {
                    return "这是 WinSxS 组件存储，体积大很常见。建议用系统组件清理，而不是手动删除或搬移。";
                }

                if (lower.Contains("\\system volume information"))
                {
                    return "这里通常是系统还原点和卷影副本，可能非常占空间。建议去系统保护里调整。";
                }

                if (lower.EndsWith("\\appdata\\local") || lower.EndsWith("\\appdata\\roaming"))
                {
                    return "这里通常是软件缓存和配置的大本营，建议进一步查看子目录，找微信、浏览器、开发工具等大户。";
                }

                if (lower.Contains("\\windows\\"))
                {
                    return "系统目录，建议只分析，不要直接搬移。";
                }

                if (lower.Contains("\\program files") || lower.Contains("\\programdata\\"))
                {
                    return "程序安装目录，建议通过软件设置或重装迁移。";
                }

                if (lower.Contains("\\appdata\\local\\packages"))
                {
                    return "商店应用数据目录，建议只清缓存或用系统“移动应用”功能。";
                }

                return "该项目可能依赖固定路径，请先确认用途。";
            }

            if (lower.Contains("\\documents\\wechat files"))
            {
                return "建议先退出微信，再搬移旧数据，并在微信里改默认保存位置。";
            }

            if (lower.Contains("\\documents\\tencent files"))
            {
                return "建议先退出 QQ，再搬移旧数据，并在 QQ 设置里改保存位置。";
            }

            if (lower.Contains("\\downloads\\"))
            {
                return "下载内容通常适合搬移，搬移后建议把浏览器下载目录改到其他盘。";
            }

            if (lower.EndsWith("\\desktop") || lower.EndsWith("\\documents") || lower.EndsWith("\\videos") || lower.EndsWith("\\pictures"))
            {
                return "这是用户目录，通常适合把旧资料搬到其他磁盘，再把默认保存位置也改掉。";
            }

            if (isDirectory)
            {
                return "这是大目录，适合先归档或搬移到非系统盘。";
            }

            return "这是大文件，通常适合直接搬移到其他磁盘。";
        }

        private static long TryGetDirectorySize(string root, int maxDepth)
        {
            long total = 0;
            var stack = new Stack<DirectoryDepthItem>();
            stack.Push(new DirectoryDepthItem(root, 0));

            while (stack.Count > 0)
            {
                DirectoryDepthItem item = stack.Pop();
                try
                {
                    foreach (string file in Directory.EnumerateFiles(item.Path, "*", SearchOption.TopDirectoryOnly))
                    {
                        try
                        {
                            total += new FileInfo(file).Length;
                        }
                        catch
                        {
                        }
                    }

                    if (item.Depth >= maxDepth)
                    {
                        continue;
                    }

                    foreach (string dir in Directory.EnumerateDirectories(item.Path, "*", SearchOption.TopDirectoryOnly))
                    {
                        if (!IsReparsePoint(dir))
                        {
                            stack.Push(new DirectoryDepthItem(dir, item.Depth + 1));
                        }
                    }
                }
                catch
                {
                }
            }

            return total;
        }

        private sealed class DirectoryDepthItem
        {
            public DirectoryDepthItem(string path, int depth)
            {
                Path = path;
                Depth = depth;
            }

            public string Path { get; private set; }
            public int Depth { get; private set; }
        }
    }
}
