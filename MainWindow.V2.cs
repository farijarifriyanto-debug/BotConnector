using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private sealed class V2Session
    {
        public string Id { get; set; } = "";
        public string Title { get; set; } = "New Chat";
        public string Text { get; set; } = "";
        public DateTime UpdatedUtc { get; set; } = DateTime.UtcNow;

        public override string ToString()
        {
            return Title;
        }
    }

    private sealed class V2FileState
    {
        public string Hash { get; set; } = "";
        public string? Text { get; set; }
        public long Size { get; set; }
    }

    private readonly Dictionary<string,V2FileState>
        _v2BeforeFiles =
            new(StringComparer.OrdinalIgnoreCase);

    private readonly Dictionary<string,string?>
        _v2DiffBefore =
            new(StringComparer.OrdinalIgnoreCase);

    private readonly List<V2Session>
        _v2Sessions =
            new();

    private V2Session?
        _v2CurrentSession;

    private DispatcherTimer?
        _v2CompletionWatcher;

    private bool
        _v2LoadingSession;

    private string V2StateRoot =>
        Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "BotConnector",
            "DesktopV2");

    private string V2SessionsFile =>
        Path.Combine(
            V2StateRoot,
            "sessions.json");


    private void V2Initialize()
    {
        Directory.CreateDirectory(
            V2StateRoot);

        V2LoadSessions();

        RefreshV2AttachmentList();

        AssistantText.ScrollToEnd();
        TerminalText.ScrollToEnd();
    }


    private void V2LoadSessions()
    {
        try
        {
            _v2Sessions.Clear();

            if (
                File.Exists(
                    V2SessionsFile))
            {
                string json =
                    File.ReadAllText(
                        V2SessionsFile);

                var loaded =
                    JsonSerializer.Deserialize<List<V2Session>>(
                        json);

                if (loaded != null)
                {
                    _v2Sessions.AddRange(
                        loaded);
                }
            }
        }
        catch
        {
            _v2Sessions.Clear();
        }

        if (_v2Sessions.Count == 0)
        {
            _v2Sessions.Add(
                new V2Session
                {
                    Id =
                        Guid.NewGuid().
                        ToString("N"),

                    Title =
                        "New Chat",

                    Text =
                        AssistantText.Text ?? "",

                    UpdatedUtc =
                        DateTime.UtcNow
                });
        }

        V2RefreshSessions();

        V2LoadSession(
            _v2Sessions
                .OrderByDescending(
                    x => x.UpdatedUtc)
                .First());
    }


    private void V2SaveSessions()
    {
        try
        {
            Directory.CreateDirectory(
                V2StateRoot);

            string json =
                JsonSerializer.Serialize(
                    _v2Sessions,
                    new JsonSerializerOptions
                    {
                        WriteIndented =
                            true
                    });

            File.WriteAllText(
                V2SessionsFile,
                json,
                new UTF8Encoding(false));
        }
        catch
        {
        }
    }


    private void V2RefreshSessions()
    {
        V2SessionList.ItemsSource =
            null;

        V2SessionList.ItemsSource =
            _v2Sessions
                .OrderByDescending(
                    x => x.UpdatedUtc)
                .ToList();
    }


    private void V2LoadSession(
        V2Session session)
    {
        _v2LoadingSession =
            true;

        try
        {
            _v2CurrentSession =
                session;

            AssistantText.Text =
                session.Text ?? "";

            // Keep the structured renderer in sync with the active thread.
            V5RebuildConversationFromTranscript(
                session.Text ?? "");

            V2SessionList.SelectedItem =
                V2SessionList.Items
                    .Cast<V2Session>()
                    .FirstOrDefault(
                        x => x.Id == session.Id);

            AssistantText.ScrollToEnd();
        }
        finally
        {
            _v2LoadingSession =
                false;
        }
    }


    private void V2_NewChat_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (_v2CurrentSession != null)
        {
            _v2CurrentSession.Text =
                AssistantText.Text ?? "";

            _v2CurrentSession.UpdatedUtc =
                DateTime.UtcNow;
        }

        var session =
            new V2Session
            {
                Id =
                    Guid.NewGuid().
                    ToString("N"),

                Title =
                    "New Chat",

                Text =
                    "",

                UpdatedUtc =
                    DateTime.UtcNow
            };

        _v2Sessions.Add(
            session);

        _agentConversationId =
            null;

        AssistantText.Text =
            "";

        _composerAttachments.Clear();

        RefreshAttachmentBar();
        RefreshV2AttachmentList();

        V2RefreshSessions();
        V2LoadSession(session);
        V2SaveSessions();

        CommandBox.Focus();
    }


    private void V2_SessionChanged(
        object sender,
        SelectionChangedEventArgs e)
    {
        if (
            _v2LoadingSession ||
            V2SessionList.SelectedItem
                is not V2Session selected)
        {
            return;
        }

        if (
            _v2CurrentSession != null &&
            _v2CurrentSession.Id ==
            selected.Id)
        {
            return;
        }

        if (_v2CurrentSession != null)
        {
            _v2CurrentSession.Text =
                AssistantText.Text ?? "";

            _v2CurrentSession.UpdatedUtc =
                DateTime.UtcNow;
        }

        _agentConversationId =
            null;

        V2LoadSession(
            selected);

        V2SaveSessions();
    }


    private void V2_AssistantTextChanged(
        object sender,
        TextChangedEventArgs e)
    {
        if (_v2LoadingSession)
        {
            return;
        }

        AssistantText.ScrollToEnd();

        if (_v2CurrentSession == null)
        {
            return;
        }

        _v2CurrentSession.Text =
            AssistantText.Text ?? "";

        _v2CurrentSession.UpdatedUtc =
            DateTime.UtcNow;

        if (
            string.Equals(
                _v2CurrentSession.Title,
                "New Chat",
                StringComparison.Ordinal))
        {
            string first =
                GetFirstUserLine(
                    _v2CurrentSession.Text);

            if (
                !string.IsNullOrWhiteSpace(
                    first))
            {
                _v2CurrentSession.Title =
                    first.Length > 36
                        ? first.Substring(0,36) + "…"
                        : first;

                V2RefreshSessions();
            }
        }

        V2SaveSessions();
    }


    private static string GetFirstUserLine(
        string text)
    {
        if (
            string.IsNullOrWhiteSpace(
                text))
        {
            return "";
        }

        string[] lines =
            text.Replace("\r","")
                .Split('\n');

        for (
            int i = 0;
            i < lines.Length;
            i++)
        {
            string line =
                lines[i].Trim();

            if (
                line.Equals(
                    "YOU",
                    StringComparison.OrdinalIgnoreCase) &&
                i + 1 < lines.Length)
            {
                for (
                    int n = i + 1;
                    n < lines.Length;
                    n++)
                {
                    string candidate =
                        lines[n].Trim();

                    if (
                        !string.IsNullOrWhiteSpace(
                            candidate) &&
                        !candidate.StartsWith(
                            "──"))
                    {
                        return candidate;
                    }
                }
            }
        }

        return "";
    }


    private void V2_DragOver(
        object sender,
        System.Windows.DragEventArgs e)
    {
        if (
            e.Data.GetDataPresent(
                System.Windows.DataFormats.FileDrop))
        {
            e.Effects =
                System.Windows.DragDropEffects.Copy;

            e.Handled =
                true;
        }
    }


    private void V2_Drop(
        object sender,
        System.Windows.DragEventArgs e)
    {
        if (
            !e.Data.GetDataPresent(
                System.Windows.DataFormats.FileDrop))
        {
            return;
        }

        if (
            e.Data.GetData(
                System.Windows.DataFormats.FileDrop)
            is not string[] paths)
        {
            return;
        }

        foreach (
            string path in
            paths)
        {
            if (
                File.Exists(
                    path))
            {
                string full =
                    Path.GetFullPath(
                        path);

                if (
                    !_composerAttachments.Any(
                        x =>
                            string.Equals(
                                x,
                                full,
                                StringComparison.OrdinalIgnoreCase)))
                {
                    _composerAttachments.Add(
                        full);
                }
            }
        }

        RefreshAttachmentBar();
        RefreshV2AttachmentList();

        e.Handled =
            true;
    }


    private void RefreshV2AttachmentList()
    {
        if (
            V2AttachmentList == null)
        {
            return;
        }

        V2AttachmentList.ItemsSource =
            null;

        V2AttachmentList.ItemsSource =
            _composerAttachments
                .Select(
                    Path.GetFileName)
                .ToList();

        V2AttachmentList.Visibility =
            _composerAttachments.Count > 0
                ? Visibility.Visible
                : Visibility.Collapsed;
    }


    private void V2_RemoveAttachment_Click(
        object sender,
        RoutedEventArgs e)
    {
        int index =
            V2AttachmentList.SelectedIndex;

        if (
            index < 0 ||
            index >=
            _composerAttachments.Count)
        {
            return;
        }

        _composerAttachments.RemoveAt(
            index);

        RefreshAttachmentBar();
        RefreshV2AttachmentList();
    }


    private void V2_ClearAttachments_Click(
        object sender,
        RoutedEventArgs e)
    {
        _composerAttachments.Clear();

        RefreshAttachmentBar();
        RefreshV2AttachmentList();
    }


    private async void V2_Send_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(
                CommandBox.Text))
        {
            return;
        }

        if (
            _agentCancellation != null ||
            _v3AdvisorCancellation != null)
        {
            return;
        }

        string task =
            CommandBox.Text.Trim();

        V2CaptureWorkspaceBefore();

        SendButton.IsEnabled =
            false;

        StopButton.IsEnabled =
            true;

        CommandBox.IsEnabled =
            false;

        V2ActivityText.Text =
            "Planner · Coder-A · Reviewer · Tester…";

        var advisorCancellation =
            new System.Threading
                .CancellationTokenSource();

        _v3AdvisorCancellation =
            advisorCancellation;

        try
        {
            _v3ParallelAdvisory =
                await V3RunParallelAdvisorsAsync(
                    task,
                    advisorCancellation.Token);
        }
        catch (
            System.OperationCanceledException)
        {
            V2ActivityText.Text =
                "";

            StatusText.Text =
                "Stopped";

            SendButton.IsEnabled =
                true;

            StopButton.IsEnabled =
                false;

            CommandBox.IsEnabled =
                true;

            CommandBox.Focus();

            return;
        }
        catch (
            System.Exception ex)
        {
            _v3ParallelAdvisory =
                "[parallel advisory unavailable: " +
                ex.Message +
                "]";
        }
        finally
        {
            if (
                System.Object.ReferenceEquals(
                    _v3AdvisorCancellation,
                    advisorCancellation))
            {
                _v3AdvisorCancellation =
                    null;
            }

            advisorCancellation.Dispose();
        }

        V2ActivityText.Text =
            "Coder…";

        Send_Click(
            sender,
            e);

        V2StartCompletionWatcher();
    }


            private void V2StartCompletionWatcher()
    {
        _v2CompletionWatcher?.Stop();

        bool sawBusy =
            StopButton.IsEnabled;

        int ticks =
            0;

        _v2CompletionWatcher =
            new DispatcherTimer
            {
                Interval =
                    TimeSpan.FromMilliseconds(
                        400)
            };

        _v2CompletionWatcher.Tick +=
            async (_, _) =>
            {
                ticks++;

                if (StopButton.IsEnabled)
                {
                    sawBusy =
                        true;

                    return;
                }

                if (
                    sawBusy ||
                    ticks >= 450)
                {
                    _v2CompletionWatcher.Stop();

                    V2CaptureWorkspaceAfter();

                    RefreshFileTree();

                    RefreshV2AttachmentList();

                    V2ActivityText.Text =
                        "Validating…";

                    try
                    {
                        string validation =
                            await V3RunAutoValidationAsync();

                        if (
                            !string.IsNullOrWhiteSpace(
                                validation))
                        {
                            AppendTerminal(
                                "[V3 Auto Validation]");

                            AppendTerminal(
                                validation);
                        }
                    }
                    finally
                    {
                        V2ActivityText.Text =
                            "";

                        _v3ParallelAdvisory =
                            "";
                    }
                }
            };

        _v2CompletionWatcher.Start();
    }


    private void V2CaptureWorkspaceBefore()
    {
        _v2BeforeFiles.Clear();
        _v2DiffBefore.Clear();

        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
        {
            return;
        }

        foreach (
            string file in
            EnumerateWorkspaceFilesSafe(
                _workspace))
        {
            try
            {
                var info =
                    new FileInfo(
                        file);

                var state =
                    new V2FileState
                    {
                        Size =
                            info.Length,

                        Hash =
                            ComputeV2FileHash(
                                file),

                        Text =
                            ReadV2DiffText(
                                file,
                                info.Length)
                    };

                _v2BeforeFiles[file] =
                    state;

                _v2DiffBefore[file] =
                    state.Text;
            }
            catch
            {
            }
        }
    }


    private void V2CaptureWorkspaceAfter()
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
        {
            return;
        }

        var changed =
            new List<string>();

        var afterFiles =
            new HashSet<string>(
                StringComparer.OrdinalIgnoreCase);

        foreach (
            string file in
            EnumerateWorkspaceFilesSafe(
                _workspace))
        {
            afterFiles.Add(
                file);

            try
            {
                string hash =
                    ComputeV2FileHash(
                        file);

                if (
                    !_v2BeforeFiles.TryGetValue(
                        file,
                        out V2FileState? before) ||
                    !string.Equals(
                        before.Hash,
                        hash,
                        StringComparison.Ordinal))
                {
                    changed.Add(
                        file);
                }
            }
            catch
            {
            }
        }

        foreach (
            string before in
            _v2BeforeFiles.Keys)
        {
            if (
                !afterFiles.Contains(
                    before))
            {
                changed.Add(
                    before);
            }
        }

        V2ChangedFiles.ItemsSource =
            changed
                .Distinct(
                    StringComparer.OrdinalIgnoreCase)
                .Select(
                    file =>
                        Path.GetRelativePath(
                            _workspace,
                            file))
                .OrderBy(
                    x => x)
                .ToList();
    }


    private IEnumerable<string>
        EnumerateWorkspaceFilesSafe(
            string root)
    {
        var pending =
            new Stack<string>();

        pending.Push(
            root);

        while (
            pending.Count > 0)
        {
            string directory =
                pending.Pop();

            DirectoryInfo info;

            try
            {
                info =
                    new DirectoryInfo(
                        directory);

                if (
                    (
                        info.Attributes &
                        FileAttributes.ReparsePoint
                    ) != 0)
                {
                    continue;
                }
            }
            catch
            {
                continue;
            }

            string name =
                info.Name;

            if (
                name.Equals(
                    ".git",
                    StringComparison.OrdinalIgnoreCase) ||
                name.Equals(
                    ".botconnector",
                    StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            FileInfo[] files;

            try
            {
                files =
                    info.GetFiles();
            }
            catch
            {
                continue;
            }

            foreach (
                FileInfo file in
                files)
            {
                if (
                    (
                        file.Attributes &
                        FileAttributes.ReparsePoint
                    ) == 0)
                {
                    yield return
                        file.FullName;
                }
            }

            DirectoryInfo[] directories;

            try
            {
                directories =
                    info.GetDirectories();
            }
            catch
            {
                continue;
            }

            foreach (
                DirectoryInfo child in
                directories)
            {
                if (
                    (
                        child.Attributes &
                        FileAttributes.ReparsePoint
                    ) == 0)
                {
                    pending.Push(
                        child.FullName);
                }
            }
        }
    }


    private static string ComputeV2FileHash(
        string file)
    {
        using var stream =
            File.Open(
                file,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite);

        using var sha =
            System.Security.Cryptography
                .SHA256.Create();

        return Convert.ToHexString(
            sha.ComputeHash(
                stream));
    }


    private static string? ReadV2DiffText(
        string file,
        long size)
    {
        if (
            size > 524288)
        {
            return null;
        }

        string ext =
            Path.GetExtension(
                file).
            ToLowerInvariant();

        string[] allowed =
        {
            ".txt",".md",".cs",".ps1",".py",
            ".js",".ts",".json",".xml",".xaml",
            ".html",".css",".sql",".sh",".yml",
            ".yaml",".ini",".toml",".csv",".log"
        };

        if (
            !allowed.Contains(
                ext,
                StringComparer.OrdinalIgnoreCase))
        {
            return null;
        }

        try
        {
            return File.ReadAllText(
                file);
        }
        catch
        {
            return null;
        }
    }


    private void V2_ChangedFile_DoubleClick(
        object sender,
        MouseButtonEventArgs e)
    {
        if (
            V2ChangedFiles.SelectedItem
                is not string relative ||
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            return;
        }

        string file =
            Path.GetFullPath(
                Path.Combine(
                    _workspace,
                    relative));

        _v2DiffBefore.TryGetValue(
            file,
            out string? before);

        string? after =
            File.Exists(
                file)
                ? ReadV2DiffText(
                    file,
                    new FileInfo(
                        file).Length)
                : null;

        V2ShowDiff(
            relative,
            before,
            after);
    }


    private void V2ShowDiff(
        string name,
        string? before,
        string? after)
    {
        var window =
            new Window
            {
                Title =
                    "Changed File — " +
                    name,

                Width =
                    1050,

                Height =
                    700,

                Owner =
                    this,

                WindowStartupLocation =
                    WindowStartupLocation.CenterOwner,

                Background =
                    System.Windows.Media.Brushes.White
            };

        var grid =
            new Grid();

        grid.ColumnDefinitions.Add(
            new ColumnDefinition());

        grid.ColumnDefinitions.Add(
            new ColumnDefinition());

        var left =
            new System.Windows.Controls.TextBox
            {
                Text =
                    before ??
                    "[new file / binary / unavailable]",

                IsReadOnly =
                    true,

                AcceptsReturn =
                    true,

                TextWrapping =
                    TextWrapping.NoWrap,

                VerticalScrollBarVisibility =
                    ScrollBarVisibility.Auto,

                HorizontalScrollBarVisibility =
                    ScrollBarVisibility.Auto,

                FontFamily =
                    new System.Windows.Media.FontFamily(
                        "Consolas"),

                FontSize =
                    12,

                Margin =
                    new Thickness(
                        8)
            };

        var right =
            new System.Windows.Controls.TextBox
            {
                Text =
                    after ??
                    "[deleted file / binary / unavailable]",

                IsReadOnly =
                    true,

                AcceptsReturn =
                    true,

                TextWrapping =
                    TextWrapping.NoWrap,

                VerticalScrollBarVisibility =
                    ScrollBarVisibility.Auto,

                HorizontalScrollBarVisibility =
                    ScrollBarVisibility.Auto,

                FontFamily =
                    new System.Windows.Media.FontFamily(
                        "Consolas"),

                FontSize =
                    12,

                Margin =
                    new Thickness(
                        8)
            };

        Grid.SetColumn(
            left,
            0);

        Grid.SetColumn(
            right,
            1);

        grid.Children.Add(
            left);

        grid.Children.Add(
            right);

        window.Content =
            grid;

        window.ShowDialog();
    }
}






