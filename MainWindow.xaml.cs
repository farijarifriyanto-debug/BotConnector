using BotConnector.Auth;
using Microsoft.Win32;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace BotConnector.Desktop;

public partial class MainWindow : Window
{
    private readonly System.Collections.Generic.List<string>
        _composerAttachments =
            new System.Collections.Generic.List<string>();

    private readonly DesktopAuthClient _desktopAuth = new();
    private System.Threading.CancellationTokenSource?
        _agentCancellation;

    private string?
        _agentConversationId;

    private readonly string
        _chatHistoryPath =
            System.IO.Path.Combine(
                System.Environment.GetFolderPath(
                    System.Environment.SpecialFolder.LocalApplicationData),
                "BotConnector",
                "DesktopState",
                "chat-history.txt");

    private readonly string _controlRoot =
        Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "BotConnector",
            "DesktopControl");

    private string BrokerPath =>
        Path.Combine(
            _controlRoot,
            "BotConnector-ApprovalBroker.ps1");

    private string RegistryPath =>
        Path.Combine(
            _controlRoot,
            "approved-folders.json");

    private string? _workspace;

    public MainWindow()
    {
        if (!V412InitializeOperationalMode())
        {
            System.Windows.Application.Current.Shutdown();
            return;
        }
        InitializeComponent();
        V5InitConversation();
        V4InitializeCommandCenter();

        // Tear the local Hermes SSH bridge down when the app closes.
        Closed += (_, _) => V5StopHermesBridge();

// BOTCONNECTOR_WEB_DESKTOP_JOB_BRIDGE_V1_1_R2A
StartWebDesktopJobBridge();

        Loaded += async (_, _) =>
        {
            LoadExistingWorkspace();
            LoadChatHistory();
            V2Initialize();

            await RestoreDeviceSessionAsync();

            AssistantText.ScrollToEnd();
            TerminalText.ScrollToEnd();
        };
    }

    private void LoadExistingWorkspace()
    {
        try
        {
            if (!File.Exists(RegistryPath))
                return;

            using JsonDocument document =
                JsonDocument.Parse(
                    File.ReadAllText(
                        RegistryPath));

            JsonElement root =
                document.RootElement;

            if (!root.TryGetProperty(
                    "ApprovedFolders",
                    out JsonElement folders))
                return;

            foreach (
                JsonElement item in
                folders.EnumerateArray())
            {
                if (!item.TryGetProperty(
                        "Path",
                        out JsonElement pathValue))
                    continue;

                string? path =
                    pathValue.GetString();

                if (
                    string.IsNullOrWhiteSpace(
                        path) ||
                    !Directory.Exists(path))
                    continue;

                SetWorkspace(path);
                break;
            }
        }
        catch (Exception ex)
        {
            AppendTerminal(
                "Registry load error: " +
                ex.Message);
        }
    }

    private async void OpenFolder_Click(
        object sender,
        RoutedEventArgs e)
    {
        using var dialog =
            new System.Windows.Forms.FolderBrowserDialog
            {
                Description =
                    "Pilih folder project untuk BotConnector AI",
                UseDescriptionForTitle =
                    true,
                ShowNewFolderButton =
                    true
            };

        if (
            dialog.ShowDialog() !=
            System.Windows.Forms.DialogResult.OK)
            return;

        string path =
            Path.GetFullPath(
                dialog.SelectedPath);

        StatusText.Text =
            "Approving workspace...";

        string output =
            await RunPowerShellAsync(
                new[]
                {
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    BrokerPath,
                    "approve",
                    "-Workspace",
                    path
                });

        AppendTerminal(output);

        if (
            output.Contains(
                "APPROVAL=PASS",
                StringComparison.OrdinalIgnoreCase))
        {
            SetWorkspace(path);

            AssistantText.Text =
                "Workspace approved.\n\n" +
                path +
                "\n\nAI dapat read/write di project ini melalui sandbox.";

            StatusText.Text =
                "Workspace approved";
        }
        else
        {
            StatusText.Text =
                "Approval failed";
        }
    }

    private void SetWorkspace(
        string path)
    {
        _v3AdvisorCancellation?.Cancel();

        _agentCancellation?.Cancel();

        _v2CompletionWatcher?.Stop();

        _agentConversationId =
            null;

        _v3ParallelAdvisory =
            "";

        _v2BeforeFiles.Clear();

        _v2DiffBefore.Clear();

        if (V2ChangedFiles != null)
        {
            V2ChangedFiles.ItemsSource =
                null;
        }

        if (V2ActivityText != null)
        {
            V2ActivityText.Text =
                "";
        }

        _composerAttachments.Clear();

        RefreshAttachmentBar();

        RefreshV2AttachmentList();

        _workspace =
            Path.GetFullPath(
                path);

        WorkspaceText.Text =
            _workspace;

        RefreshFileTree();
    }

    private void RefreshFileTree()
    {
        FileList.Items.Clear();

        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
            return;

        try
        {
            foreach (
                string file in
                Directory.EnumerateFiles(
                    _workspace,
                    "*",
                    SearchOption.AllDirectories)
                    .Take(800))
            {
                string relative =
                    Path.GetRelativePath(
                        _workspace,
                        file);

                FileList.Items.Add(
                    relative);
            }
        }
        catch (Exception ex)
        {
            AppendTerminal(
                "File tree: " +
                ex.Message);
        }
    }

    private void FileList_DoubleClick(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
            return;

        if (
            FileList.SelectedItem is
            not string relative)
            return;

        string full =
            Path.Combine(
                _workspace,
                relative);

        try
        {
            if (
                new FileInfo(full).Length >
                1024 * 1024)
            {
                AssistantText.Text =
                    "File terlalu besar untuk preview.";
                return;
            }

            AssistantText.Text =
                File.ReadAllText(full);
        }
        catch (Exception ex)
        {
            AssistantText.Text =
                "Preview error:\n" +
                ex.Message;
        }
    }

    private async void Run_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            System.Windows.MessageBox.Show(
                "Buka dan approve folder project terlebih dahulu.",
                "BotConnector",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Information);

            return;
        }

        string command =
            CommandBox.Text.Trim();

        if (
            string.IsNullOrWhiteSpace(
                command))
            return;

        string mode =
            (
                ModeBox.SelectedIndex == 1
                    ? "online"
                    : "offline"
            );

        string cmdArgs =
            "/d /c " +
            command;

        string b64 =
            Convert.ToBase64String(
                Encoding.UTF8.GetBytes(
                    cmdArgs));

        StatusText.Text =
            "Running in sandbox...";

        AppendTerminal(
            "> " +
            command);

        string output =
            await RunPowerShellAsync(
                new[]
                {
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    BrokerPath,
                    "run",
                    "-Workspace",
                    _workspace,
                    "-Mode",
                    mode,
                    "-Exe",
                    Path.Combine(
                        Environment.GetFolderPath(
                            Environment.SpecialFolder.Windows),
                        "System32",
                        "cmd.exe"),
                    "-ArgumentsB64",
                    b64
                });

        AppendTerminal(
            output);

        RefreshFileTree();

        StatusText.Text =
            "Sandbox: Ready";
    }

    private async void Revoke_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
            return;

        System.Windows.MessageBoxResult confirmation =
            System.Windows.MessageBox.Show(
                "Cabut akses BotConnector dari folder ini?",
                "Revoke Folder",
                System.Windows.MessageBoxButton.YesNo,
                System.Windows.MessageBoxImage.Question);

        if (
            confirmation !=
            System.Windows.MessageBoxResult.Yes)
            return;

        string output =
            await RunPowerShellAsync(
                new[]
                {
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    BrokerPath,
                    "revoke",
                    "-Workspace",
                    _workspace
                });

        AppendTerminal(
            output);

        if (
            output.Contains(
                "REVOKE=PASS",
                StringComparison.OrdinalIgnoreCase))
        {
            _workspace = null;

            WorkspaceText.Text =
                "Belum ada workspace";

            FileList.Items.Clear();

            AssistantText.Text =
                "Akses folder berhasil dicabut.";

            StatusText.Text =
                "Workspace revoked";
        }
    }

    private void ClearTerminal_Click(
        object sender,
        RoutedEventArgs e)
    {
        TerminalText.Clear();
    }

    private void AppendTerminal(
        string text)
    {
        if (
            string.IsNullOrWhiteSpace(
                text))
            return;

        TerminalText.AppendText(
            text.TrimEnd() +
            Environment.NewLine);

        CapTextBoxTail(TerminalText, 200_000);

        TerminalText.ScrollToEnd();
    }

    // Perf: bound live UI text controls so long sessions/output cannot grow
    // unbounded and lock the UI. Trims oldest content, keeps the tail.
    private static void CapTextBoxTail(
        System.Windows.Controls.TextBox box,
        int maxChars)
    {
        string t = box.Text;

        if (t.Length <= maxChars)
            return;

        int cut = t.Length - maxChars;

        int nl = t.IndexOf('\n', cut);
        if (nl >= 0 && nl < t.Length - 1)
            cut = nl + 1;

        box.Text =
            "[... earlier output trimmed ...]" +
            Environment.NewLine +
            t.Substring(cut);

        box.CaretIndex = box.Text.Length;
    }

    private static async Task<string>
        RunPowerShellAsync(
            IEnumerable<string> arguments)
    {
        var psi =
            new ProcessStartInfo
            {
                FileName =
                    "powershell.exe",

                UseShellExecute =
                    false,

                RedirectStandardOutput =
                    true,

                RedirectStandardError =
                    true,

                CreateNoWindow =
                    true
            };

        foreach (
            string argument in
            arguments)
        {
            psi.ArgumentList.Add(
                argument);
        }

        using Process process =
            new Process
            {
                StartInfo =
                    psi
            };

        process.Start();

        Task<string> stdout =
            process.StandardOutput
                .ReadToEndAsync();

        Task<string> stderr =
            process.StandardError
                .ReadToEndAsync();

        await process.WaitForExitAsync();

        string output =
            await stdout;

        string error =
            await stderr;

        if (
            !string.IsNullOrWhiteSpace(
                error))
        {
            output +=
                Environment.NewLine +
                error;
        }

        output +=
            Environment.NewLine +
            "EXIT=" +
            process.ExitCode;

        return output;
    }

    private async void SignInButton_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        try
        {
            SignInButton.IsEnabled = false;
            AuthStatusText.Text = "Signing in...";

            await _desktopAuth.SignInAsync(
                Environment.MachineName);

            var ok =
                await _desktopAuth.VerifyAsync();

            if (!ok)
            {
                var refreshed =
                    await _desktopAuth.RefreshAsync();

                if (refreshed)
                {
                    ok =
                        await _desktopAuth.VerifyAsync();
                }
            }

            AuthStatusText.Text =
                ok
                    ? "Signed in"
                    : "Authentication failed";

            if (!ok)
            {
                throw new InvalidOperationException(
                    "Device token verification failed.");
            }

            System.Windows.MessageBox.Show(
                "Device authentication PASS.",
                "BotConnector",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            AuthStatusText.Text =
                "Not signed in";

            System.Windows.MessageBox.Show(
                ex.Message,
                "BotConnector Sign in",
                System.Windows.MessageBoxButton.OK,
                System.Windows.MessageBoxImage.Error);
        }
        finally
        {
            SignInButton.IsEnabled = true;
        }
    }

    private async System.Threading.Tasks.Task
        RestoreDeviceSessionAsync()
    {
        try
        {
            SignInButton.IsEnabled = false;

            _desktopAuth.LoadStored();

            if (_desktopAuth.Current is null)
            {
                AuthStatusText.Text =
                    "Not signed in";
                SignInButton.Visibility =
                    Visibility.Visible;

                return;
            }

            bool ok =
                await _desktopAuth.VerifyAsync();

            if (!ok)
            {
                bool refreshed =
                    await _desktopAuth.RefreshAsync();

                if (refreshed)
                {
                    ok =
                        await _desktopAuth.VerifyAsync();
                }
            }

            if (ok)
            {
                AuthStatusText.Text =
                    "Signed in";
                SignInButton.Visibility =
                    Visibility.Collapsed;
            }
            else
            {
                _desktopAuth.SignOutLocal();

                AuthStatusText.Text =
                    "Not signed in";
                SignInButton.Visibility =
                    Visibility.Visible;
            }
        }
        catch
        {
            AuthStatusText.Text =
                "Not signed in";
        }
        finally
        {
            SignInButton.IsEnabled = true;
        }
    }


    private sealed class AgentActionEnvelope
    {
        public System.Collections.Generic.List<AgentAction>?
            actions
        {
            get;
            set;
        }
    }


    private sealed class AgentAction
    {
        public string? type
        {
            get;
            set;
        }

        public string? path
        {
            get;
            set;
        }

        public string? content
        {
            get;
            set;
        }

        public string? command
        {
            get;
            set;
        }

        // edit_file: replace an exact anchor (find) with new text (replace).
        public string? find
        {
            get;
            set;
        }

        public string? replace
        {
            get;
            set;
        }

        // search: substring/regex query across workspace files.
        public string? query
        {
            get;
            set;
        }
    }


    private async void Send_Click(
        object sender,
        RoutedEventArgs e)
    {
        string userPrompt =
            CommandBox.Text.Trim();

        string displayPrompt = userPrompt;

        if (_composerAttachments.Count > 0)
        {
            userPrompt = BuildAttachmentPrompt(userPrompt);
        }

        if (
            string.IsNullOrWhiteSpace(
                userPrompt))
        {
            return;
        }

        if (_agentCancellation is not null)
        {
            return;
        }

        _agentCancellation =
            new System.Threading
                .CancellationTokenSource();

        SendButton.IsEnabled = false;
        StopButton.IsEnabled = true;
        CommandBox.IsEnabled = false;

        try
        {
            AppendConversation(
                "You",
                displayPrompt);

            SetAgentActivity(
                "Thinking...");

            string prompt =
                BuildAgentPrompt(
                    V3AugmentUserPrompt(
                        userPrompt));

            var response =
                await _desktopAuth.SendChatAsync(
                    prompt,
                    _agentConversationId,
                    _agentCancellation.Token);

            _agentConversationId =
                response.conversation_id;

            string answer =
                ExtractAssistantText(
                    response.result);

            int rounds = 0;
            int parseRetries = 0;
            const int maxRounds = 25;

            while (
                rounds < maxRounds &&
                !_agentCancellation
                    .IsCancellationRequested)
            {
                var actions =
                    ExtractAgentActions(
                        answer);

                if (
                    actions is null ||
                    actions.Count == 0)
                {
                    bool hadBlock =
                        answer.IndexOf(
                            "<botconnector_actions>",
                            System.StringComparison.Ordinal) >= 0;

                    if (hadBlock && parseRetries < 2)
                    {
                        parseRetries++;

                        SetAgentActivity(
                            "Fixing action format...");

                        var fixResp =
                            await _desktopAuth.SendChatAsync(
                                "Your <botconnector_actions> block was not valid " +
                                "JSON and could not be parsed. Resend ONLY a " +
                                "corrected <botconnector_actions>...</botconnector_actions> " +
                                "block with valid JSON. Escape every quote, newline " +
                                "and backslash inside string values. No prose.",
                                _agentConversationId,
                                _agentCancellation.Token);

                        _agentConversationId =
                            fixResp.conversation_id;

                        answer =
                            ExtractAssistantText(
                                fixResp.result);

                        continue;
                    }

                    break;
                }

                parseRetries = 0;

                string localResults =
                    await ExecuteAgentActionsAsync(
                        actions);

                P52AddActivity(
                    "TOOLS",
                    P52SummarizeToolResults(
                        localResults));

                RefreshFileTree();

                await P52RefreshReviewAsync();

                string continuation =
                    "Local workspace action results:" +
                    System.Environment.NewLine +
                    localResults +
                    System.Environment.NewLine +
                    System.Environment.NewLine +
                    "Continue the original task. " +
                    "If more local operations are needed, " +
                    "use another botconnector_actions block.";

                response =
                    await _desktopAuth.SendChatAsync(
                        continuation,
                        _agentConversationId,
                        _agentCancellation.Token);

                _agentConversationId =
                    response.conversation_id;

                answer =
                    ExtractAssistantText(
                        response.result);

                rounds++;
            }

            AppendConversation(
                "Assistant",
                RemoveActionBlock(
                    answer));

            CommandBox.Clear();

            AuthStatusText.Text =
                "Signed in";

            StatusText.Text =
                "Ready";
        }
        catch (
            System.OperationCanceledException)
        {
            AppendConversation(
                "System",
                "Request stopped.");

            StatusText.Text =
                "Stopped";
        }
        catch (System.Exception ex)
        {
            AppendConversation(
                "Error",
                ex.Message);

            StatusText.Text =
                "AI error";
        }
        finally
        {
            if (_agentCancellation is not null)
            {
                _agentCancellation.Dispose();
                _agentCancellation = null;
            }

            SendButton.IsEnabled = true;
            StopButton.IsEnabled = false;
            CommandBox.IsEnabled = true;
            CommandBox.Focus();
        }
    }


    private void Stop_Click(
        object sender,
        RoutedEventArgs e)
    {
        // V6 OpenCode Direct: Stop natively aborts the active OpenCode session
        // (POST /session/{id}/abort), then cancels local awaits below.
        V6OpenCodeDirectAbort();

        _v3AdvisorCancellation?.Cancel();

        _agentCancellation?.Cancel();
    }


    private void LocalAi_Changed(
        object sender,
        RoutedEventArgs e)
    {
        bool on =
            LocalAiCheck.IsChecked == true;

        _desktopAuth.UseLocalModel = on;

        if (on)
        {
            // Local model needs no sign-in; enable the composer directly.
            SendButton.IsEnabled = true;
            CommandBox.IsEnabled = true;
            AuthStatusText.Text = "Local AI";
            StatusText.Text =
                "Local AI - " +
                _desktopAuth.LocalBaseUrl +
                " (start LM Studio server)";
        }
        else
        {
            StatusText.Text = "Cloud AI";
        }
    }








    // BOTCONNECTOR_P5_5_AGENT_DIFF_REVIEW_CODE

    private async System.Threading.Tasks.Task<string>
        P55CurrentMainHeadAsync()
    {
        var result =
            await P52RunGitAsync(
                "rev-parse",
                "HEAD");

        if (
            result.ExitCode != 0
            ||
            string.IsNullOrWhiteSpace(
                result.Stdout))
        {
            throw new System.InvalidOperationException(
                "Cannot resolve main HEAD: "
                + result.Stderr.Trim());
        }

        return result.Stdout.Trim();
    }


    private async System.Threading.Tasks.Task
        P55VerifyWorktreeBaseAsync(
            P54AgentState state)
    {
        var result =
            await P52RunGitAsync(
                "-C",
                state.WorktreePath,
                "rev-parse",
                "HEAD");

        if (result.ExitCode != 0)
        {
            throw new System.InvalidOperationException(
                "Cannot resolve worktree HEAD: "
                + result.Stderr.Trim());
        }

        if (
            !string.Equals(
                result.Stdout.Trim(),
                state.BaseHead,
                System.StringComparison
                    .OrdinalIgnoreCase))
        {
            throw new System.InvalidOperationException(
                "Worktree HEAD differs from pinned BaseHead.");
        }
    }


    private P54AgentState?
        P55SelectedAgent()
    {
        int index=
            P54AgentList.SelectedIndex;

        if (
            index<0
            ||
            index>=_p54Agents.Count)
        {
            return null;
        }

        return _p54Agents[index];
    }


    private bool P55Busy(
        P54AgentState state)
    {
        return
            state.Status=="QUEUED"
            ||
            state.Status=="CREATING"
            ||
            state.Status=="READY"
            ||
            state.Status=="RUNNING";
    }


    private string P55SafePath(
        string root,
        string relative)
    {
        string normalized=
            relative.Replace(
                '/',
                System.IO.Path
                    .DirectorySeparatorChar);

        string fullRoot=
            System.IO.Path
                .GetFullPath(root)
                .TrimEnd(
                    System.IO.Path
                        .DirectorySeparatorChar,
                    System.IO.Path
                        .AltDirectorySeparatorChar);

        string target=
            System.IO.Path.GetFullPath(
                System.IO.Path.Combine(
                    fullRoot,
                    normalized));

        string prefix=
            fullRoot
            + System.IO.Path
                .DirectorySeparatorChar;

        if (
            !target.StartsWith(
                prefix,
                System.StringComparison
                    .OrdinalIgnoreCase))
        {
            throw new System.UnauthorizedAccessException(
                "Path escapes workspace: "
                + relative);
        }

        return target;
    }


    private async System.Threading.Tasks.Task<
        (
            string MainHead,
            string WorktreeHead,
            string Status,
            string Patch,
            System.Collections.Generic.List<string>
                Untracked
        )>
        P55CollectAsync(
            P54AgentState state)
    {
        string mainHead=
            await P55CurrentMainHeadAsync();

        var worktreeHead=
            await P52RunGitAsync(
                "-C",
                state.WorktreePath,
                "rev-parse",
                "HEAD");

        var status=
            await P52RunGitAsync(
                "-C",
                state.WorktreePath,
                "status",
                "--short");

        var patch=
            await P52RunGitAsync(
                "-C",
                state.WorktreePath,
                "diff",
                "--binary",
                "--full-index",
                state.BaseHead,
                "--");

        var untracked=
            await P52RunGitAsync(
                "-C",
                state.WorktreePath,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z");

        if (
            worktreeHead.ExitCode!=0
            ||
            status.ExitCode!=0
            ||
            patch.ExitCode!=0
            ||
            untracked.ExitCode!=0)
        {
            throw new System.InvalidOperationException(
                "Unable to collect isolated agent diff.");
        }

        var files=
            new System.Collections.Generic
                .List<string>();

        foreach (
            string item
            in untracked.Stdout.Split(
                '\0',
                System.StringSplitOptions
                    .RemoveEmptyEntries))
        {
            if (
                !string.IsNullOrWhiteSpace(
                    item))
            {
                files.Add(
                    item.Trim());
            }
        }

        return (
            mainHead,
            worktreeHead.Stdout.Trim(),
            status.Stdout,
            patch.Stdout,
            files);
    }


    private async System.Threading.Tasks.Task
        P55PreviewAsync()
    {
        var state=
            P55SelectedAgent();

        if (state is null)
        {
            P55DiffPreview.Text=
                "Select an agent first.";

            return;
        }

        try
        {
            var snapshot=
                await P55CollectAsync(
                    state);

            var text=
                new System.Text
                    .StringBuilder();

            text.AppendLine(
                "AGENT="+state.Id);

            text.AppendLine(
                "BRANCH="+state.Branch);

            text.AppendLine(
                "STATUS="+state.Status);

            text.AppendLine(
                "BASE_HEAD="+state.BaseHead);

            text.AppendLine(
                "MAIN_HEAD="+snapshot.MainHead);

            text.AppendLine(
                "WORKTREE_HEAD="
                +snapshot.WorktreeHead);

            if (
                !string.Equals(
                    state.BaseHead,
                    snapshot.MainHead,
                    System.StringComparison
                        .OrdinalIgnoreCase))
            {
                text.AppendLine();

                text.AppendLine(
                    "WARNING: MAIN HEAD CHANGED. APPLY BLOCKED.");
            }

            text.AppendLine();
            text.AppendLine(
                "===== STATUS =====");

            text.AppendLine(
                string.IsNullOrWhiteSpace(
                    snapshot.Status)
                    ? "(clean)"
                    : snapshot.Status.TrimEnd());

            text.AppendLine();
            text.AppendLine(
                "===== UNTRACKED =====");

            if (
                snapshot.Untracked.Count==0)
            {
                text.AppendLine("(none)");
            }
            else
            {
                foreach (
                    string file
                    in snapshot.Untracked)
                {
                    text.AppendLine(file);
                }
            }

            text.AppendLine();
            text.AppendLine(
                "===== PATCH =====");

            text.Append(
                string.IsNullOrWhiteSpace(
                    snapshot.Patch)
                    ? "(no tracked diff)"
                    : snapshot.Patch);

            string preview=
                text.ToString();

            if (preview.Length>240000)
            {
                preview=
                    preview.Substring(
                        0,
                        240000)
                    + System.Environment.NewLine
                    + "[preview truncated]";
            }

            P55DiffPreview.Text=
                preview;

            P55DiffPreview.ScrollToHome();

            P52AddActivity(
                "DIFF",
                "Reviewed "+state.Id);
        }
        catch (
            System.Exception ex)
        {
            P55DiffPreview.Text=
                "Preview failed: "
                +ex.Message;
        }
    }


    private async void
        P55_AgentSelectionChanged(
            object sender,
            System.Windows.Controls
                .SelectionChangedEventArgs e)
    {
        await P55PreviewAsync();
    }


    private async void
        P55_Preview_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        await P55PreviewAsync();
    }


    private async void
        P55_Apply_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        var state=
            P55SelectedAgent();

        if (state is null)
        {
            P55DiffPreview.Text=
                "Select an agent first.";

            return;
        }

        if (P55Busy(state))
        {
            P55DiffPreview.Text=
                "Agent is still active.";

            return;
        }

        string? patchFile=null;
        bool patchApplied=false;

        var copied=
            new System.Collections.Generic
                .List<string>();

        try
        {
            var snapshot=
                await P55CollectAsync(
                    state);

            if (
                !string.Equals(
                    snapshot.MainHead,
                    state.BaseHead,
                    System.StringComparison
                        .OrdinalIgnoreCase))
            {
                throw new System.InvalidOperationException(
                    "Main HEAD changed since agent creation. Apply blocked.");
            }

            if (
                string.IsNullOrWhiteSpace(
                    snapshot.Patch)
                &&
                snapshot.Untracked.Count==0)
            {
                P55DiffPreview.Text=
                    "No changes to apply.";

                return;
            }

            var copies=
                new System.Collections.Generic
                    .List<
                        (
                            string Source,
                            string Destination
                        )>();

            foreach (
                string relative
                in snapshot.Untracked)
            {
                string source=
                    P55SafePath(
                        state.WorktreePath,
                        relative);

                string destination=
                    P55SafePath(
                        _workspace
                            ?? throw new System.InvalidOperationException(
                                "No active workspace."),
                        relative);

                if (
                    !System.IO.File.Exists(
                        source))
                {
                    throw new System.IO
                        .FileNotFoundException(
                            source);
                }

                if (
                    System.IO.File.Exists(
                        destination)
                    ||
                    System.IO.Directory.Exists(
                        destination))
                {
                    throw new System.IO.IOException(
                        "Destination already exists: "
                        +relative);
                }

                var attr=
                    System.IO.File.GetAttributes(
                        source);

                if (
                    (
                        attr
                        &
                        System.IO.FileAttributes
                            .ReparsePoint
                    )!=0)
                {
                    throw new System.InvalidOperationException(
                        "Reparse point requires manual review: "
                        +relative);
                }

                copies.Add(
                    (
                        source,
                        destination
                    ));
            }

            if (
                !string.IsNullOrWhiteSpace(
                    snapshot.Patch))
            {
                patchFile=
                    System.IO.Path.Combine(
                        System.IO.Path
                            .GetTempPath(),
                        "bc-p55-"
                        +System.Guid.NewGuid()
                            .ToString("N")
                        +".patch");

                System.IO.File.WriteAllText(
                    patchFile,
                    snapshot.Patch,
                    new System.Text
                        .UTF8Encoding(false));

                var precheck=
                    await P52RunGitAsync(
                        "apply",
                        "--check",
                        "--whitespace=nowarn",
                        patchFile);

                if (precheck.ExitCode!=0)
                {
                    throw new System.InvalidOperationException(
                        "Patch does not apply cleanly."
                        + System.Environment.NewLine
                        + precheck.Stdout
                        + System.Environment.NewLine
                        + precheck.Stderr);
                }
            }

            var confirm=
                System.Windows.MessageBox.Show(
                    this,
                    "Apply changes from "
                    +state.Id
                    +" to the active workspace?"
                    +System.Environment.NewLine
                    +System.Environment.NewLine
                    +"No commit or merge will be created.",
                    "Apply agent changes",
                    System.Windows.MessageBoxButton
                        .YesNo,
                    System.Windows.MessageBoxImage
                        .Question);

            if (
                confirm
                !=
                System.Windows.MessageBoxResult.Yes)
            {
                return;
            }

            try
            {
                if (patchFile is not null)
                {
                    var apply=
                        await P52RunGitAsync(
                            "apply",
                            "--whitespace=nowarn",
                            patchFile);

                    if (apply.ExitCode!=0)
                    {
                        throw new System.InvalidOperationException(
                            "git apply failed."
                            +System.Environment.NewLine
                            +apply.Stdout
                            +System.Environment.NewLine
                            +apply.Stderr);
                    }

                    patchApplied=true;
                }

                foreach (
                    var item
                    in copies)
                {
                    string? parent=
                        System.IO.Path
                            .GetDirectoryName(
                                item.Destination);

                    if (
                        !string.IsNullOrWhiteSpace(
                            parent))
                    {
                        System.IO.Directory
                            .CreateDirectory(
                                parent);
                    }

                    System.IO.File.Copy(
                        item.Source,
                        item.Destination,
                        false);

                    copied.Add(
                        item.Destination);
                }

                var check=
                    await P52RunGitAsync(
                        "diff",
                        "--check");

                if (check.ExitCode!=0)
                {
                    throw new System.InvalidOperationException(
                        "Applied changes failed git diff --check."
                        +System.Environment.NewLine
                        +check.Stdout
                        +System.Environment.NewLine
                        +check.Stderr);
                }

                state.Status="APPLIED";

                P54RefreshAgentRow(state);

                P52AddActivity(
                    "APPLY",
                    state.Id
                    +" applied");

                RefreshFileTree();

                await P52RefreshReviewAsync();

                await P55PreviewAsync();
            }
            catch
            {
                for (
                    int i=copied.Count-1;
                    i>=0;
                    i--)
                {
                    try
                    {
                        if (
                            System.IO.File.Exists(
                                copied[i]))
                        {
                            System.IO.File.Delete(
                                copied[i]);
                        }
                    }
                    catch
                    {
                    }
                }

                if (
                    patchApplied
                    &&
                    patchFile is not null)
                {
                    var reverse=
                        await P52RunGitAsync(
                            "apply",
                            "-R",
                            "--whitespace=nowarn",
                            patchFile);

                    if (reverse.ExitCode!=0)
                    {
                        P54AppendOutput(
                            "WARNING: reverse patch failed."
                            +System.Environment.NewLine
                            +reverse.Stdout
                            +System.Environment.NewLine
                            +reverse.Stderr);
                    }
                }

                throw;
            }
        }
        catch (
            System.Exception ex)
        {
            P55DiffPreview.Text=
                "Apply failed: "
                +ex.Message;

            P52AddActivity(
                "ERROR",
                "Apply: "
                +ex.Message);
        }
        finally
        {
            if (patchFile is not null)
            {
                try
                {
                    System.IO.File.Delete(
                        patchFile);
                }
                catch
                {
                }
            }
        }
    }


    private async void
        P55_Discard_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        var state=
            P55SelectedAgent();

        if (state is null)
        {
            P55DiffPreview.Text=
                "Select an agent first.";

            return;
        }

        if (P55Busy(state))
        {
            P55DiffPreview.Text=
                "Agent is still active.";

            return;
        }

        if (
            string.IsNullOrWhiteSpace(
                state.WorktreePath)
            ||
            !System.IO.Directory.Exists(
                state.WorktreePath))
        {
            P55DiffPreview.Text=
                "Worktree no longer exists.";

            return;
        }

        try
        {
            string main=
                System.IO.Path
                    .GetFullPath(
                        _workspace
                            ?? throw new System.InvalidOperationException(
                                "No active workspace."))
                    .TrimEnd(
                        System.IO.Path
                            .DirectorySeparatorChar,
                        System.IO.Path
                            .AltDirectorySeparatorChar);

            string candidate=
                System.IO.Path
                    .GetFullPath(
                        state.WorktreePath)
                    .TrimEnd(
                        System.IO.Path
                            .DirectorySeparatorChar,
                        System.IO.Path
                            .AltDirectorySeparatorChar);

            if (
                string.Equals(
                    main,
                    candidate,
                    System.StringComparison
                        .OrdinalIgnoreCase))
            {
                throw new System.InvalidOperationException(
                    "Refusing to remove active workspace.");
            }

            var confirm=
                System.Windows.MessageBox.Show(
                    this,
                    "Discard "
                    +state.Id
                    +" isolated worktree?"
                    +System.Environment.NewLine
                    +System.Environment.NewLine
                    +"Uncommitted changes inside that worktree will be deleted.",
                    "Discard worktree",
                    System.Windows.MessageBoxButton
                        .YesNo,
                    System.Windows.MessageBoxImage
                        .Warning);

            if (
                confirm
                !=
                System.Windows.MessageBoxResult.Yes)
            {
                return;
            }

            var remove=
                await P52RunGitAsync(
                    "worktree",
                    "remove",
                    "--force",
                    state.WorktreePath);

            if (remove.ExitCode!=0)
            {
                throw new System.InvalidOperationException(
                    "Worktree removal failed."
                    +System.Environment.NewLine
                    +remove.Stdout
                    +System.Environment.NewLine
                    +remove.Stderr);
            }

            var branch=
                await P52RunGitAsync(
                    "branch",
                    "-D",
                    state.Branch);

            state.Status=
                branch.ExitCode==0
                    ? "DISCARDED"
                    : "DISCARDED_BRANCH_KEPT";

            state.WorktreePath="";

            P54RefreshAgentRow(state);

            P55DiffPreview.Text=
                branch.ExitCode==0
                    ? "Worktree and branch discarded."
                    : "Worktree discarded; branch retained.";

            P52AddActivity(
                "DISCARD",
                state.Id+" discarded");

            await P53RefreshWorktreesAsync();
        }
        catch (
            System.Exception ex)
        {
            P55DiffPreview.Text=
                "Discard failed: "
                +ex.Message;
        }
    }

    // BOTCONNECTOR_P5_4_ISOLATED_AGENTS_CODE
    private sealed class P54AgentState
    {
        public string Id { get; set; } = "";

        public string TaskText { get; set; } = "";

        public string Branch { get; set; } = "";

        public string WorktreePath { get; set; } = "";

        public string BaseHead { get; set; } = "";

        public string Status { get; set; } = "QUEUED";

        public string Result { get; set; } = "";
    }


    private sealed class P54WorktreeEntry
    {
        public string Path { get; set; } = "";

        public string Branch { get; set; } = "";
    }


    private System.Threading.CancellationTokenSource?
        _p54Cancellation;

    private readonly
        System.Collections.Generic.List<P54AgentState>
        _p54Agents =
            new();


    private string P54SafePrefix(
        string? value)
    {
        string source =
            string.IsNullOrWhiteSpace(value)
                ? "bc-agent"
                : value.Trim();

        var b =
            new System.Text.StringBuilder();

        foreach (char c in source)
        {
            if (
                char.IsLetterOrDigit(c)
                ||
                c == '-'
                ||
                c == '_')
            {
                b.Append(c);
            }
            else
            {
                b.Append('-');
            }
        }

        string result =
            b.ToString()
            .Trim('-','_');

        if (
            string.IsNullOrWhiteSpace(
                result))
        {
            result =
                "bc-agent";
        }

        if (result.Length > 30)
        {
            result =
                result.Substring(
                    0,
                    30);
        }

        return result;
    }


    private System.Collections.Generic.List<string>
        P54ReadTasks()
    {
        var result =
            new System.Collections.Generic
                .List<string>();

        string raw =
            P54TasksBox.Text ?? "";

        string[] lines =
            raw.Split(
                new[]
                {
                    '\r',
                    '\n'
                },
                System.StringSplitOptions
                    .RemoveEmptyEntries);

        foreach (string input in lines)
        {
            string task =
                input.Trim();

            if (
                string.IsNullOrWhiteSpace(
                    task))
            {
                continue;
            }

            result.Add(task);

            if (result.Count >= 4)
            {
                break;
            }
        }

        return result;
    }


    private System.Collections.Generic.List<P54WorktreeEntry>
        P54ParseWorktrees(
            string output)
    {
        var result =
            new System.Collections.Generic
                .List<P54WorktreeEntry>();

        P54WorktreeEntry? current =
            null;

        string[] lines =
            output.Split(
                new[]
                {
                    '\r',
                    '\n'
                },
                System.StringSplitOptions
                    .RemoveEmptyEntries);

        foreach (string raw in lines)
        {
            string line =
                raw.Trim();

            if (
                line.StartsWith(
                    "worktree ",
                    System.StringComparison
                        .Ordinal))
            {
                current =
                    new P54WorktreeEntry
                    {
                        Path =
                            line.Substring(
                                "worktree ".Length)
                            .Trim()
                    };

                result.Add(current);

                continue;
            }

            if (
                current is not null
                &&
                line.StartsWith(
                    "branch refs/heads/",
                    System.StringComparison
                        .Ordinal))
            {
                current.Branch =
                    line.Substring(
                        "branch refs/heads/"
                            .Length)
                    .Trim();
            }
        }

        return result;
    }


    private async System.Threading.Tasks.Task<string?>
        P54FindWorktreeAsync(
            string branch)
    {
        string output =
            await V3ExecuteGitActionAsync(
                "git_worktree_list",
                null,
                null);

        var entries =
            P54ParseWorktrees(
                output);

        foreach (
            P54WorktreeEntry entry
            in entries)
        {
            if (
                string.Equals(
                    entry.Branch,
                    branch,
                    System.StringComparison
                        .OrdinalIgnoreCase))
            {
                return entry.Path;
            }
        }

        return null;
    }


    private void P54RefreshAgentRow(
        P54AgentState state)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.Invoke(
                () =>
                    P54RefreshAgentRow(
                        state));

            return;
        }

        int index =
            _p54Agents.IndexOf(
                state);

        if (index < 0)
        {
            return;
        }

        string path =
            string.IsNullOrWhiteSpace(
                state.WorktreePath)
                ? "(no worktree)"
                : state.WorktreePath;

        string row =
            state.Status
            + " | "
            + state.Id
            + " | "
            + state.Branch
            + " | "
            + path;

        if (
            index <
            P54AgentList.Items.Count)
        {
            P54AgentList.Items[index] =
                row;
        }
        else
        {
            while (
                P54AgentList.Items.Count
                < index)
            {
                P54AgentList.Items.Add(
                    "");
            }

            P54AgentList.Items.Add(
                row);
        }
    }


    private void P54AppendOutput(
        string text)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.Invoke(
                () =>
                    P54AppendOutput(
                        text));

            return;
        }

        if (
            P54AgentOutput.Text.Length > 0)
        {
            P54AgentOutput.AppendText(
                System.Environment.NewLine);
        }

        P54AgentOutput.AppendText(
            text);

        P54AgentOutput.ScrollToEnd();
    }


    private string P54AgentPrompt(
        P54AgentState state)
    {
        var b =
            new System.Text.StringBuilder();

        b.AppendLine(
            "You are an isolated background coding agent inside BotConnector.");

        b.AppendLine(
            "AGENT ID: "
            + state.Id);

        b.AppendLine(
            "ACTIVE WORKTREE: "
            + state.WorktreePath);

        b.AppendLine(
            "ACTIVE BRANCH: "
            + state.Branch);

        b.AppendLine();

        b.AppendLine(
            "Complete the assigned coding task end-to-end.");

        b.AppendLine(
            "Use workspace_read, workspace_write, and local_shell as needed.");

        b.AppendLine(
            "Read the relevant project instructions and source before editing.");

        b.AppendLine(
            "Keep every filesystem mutation inside this active worktree.");

        b.AppendLine(
            "Do not modify the main worktree or another agent worktree.");

        b.AppendLine(
            "Do not run git push, force push, reset --hard, or destructive cleanup.");

        b.AppendLine(
            "Do not commit automatically.");

        b.AppendLine(
            "Run appropriate tests or build checks before finishing when practical.");

        b.AppendLine(
            "If a tool fails, diagnose it and continue only when the state is truthful.");

        b.AppendLine();

        b.AppendLine(
            "TASK:");

        b.AppendLine(
            state.TaskText);

        return b.ToString();
    }


    private async System.Threading.Tasks.Task
        P54RunOneAgentAsync(
            P54AgentState state,
            System.Threading.CancellationToken
                cancellationToken)
    {
        try
        {
            state.Status =
                "RUNNING";

            P54RefreshAgentRow(
                state);

            Dispatcher.Invoke(
                () =>
                    P52AddActivity(
                        "ISOLATED",
                        state.Id
                        + " running"));

            var host =
                new BotConnector.Desktop
                    .V4.Core.V4RuntimeHost();

            host.Runtime.Workspace
                .SetWorkspace(
                    state.WorktreePath,
                    _workspace,
                    state.Branch,
                    state.WorktreePath);

            host.Runtime.Workspace
                .SetActiveAgent(
                    state.Id);

            var brain =
                host.CreateCloudCodingBrain();

            var transcript =
                new System.Collections.Generic
                    .List<string>
                {
                    P54AgentPrompt(
                        state)
                };

            string result =
                await host.Agent.RunAsync(
                    brain,
                    transcript,
                    cancellationToken);

            state.Result =
                result;

            state.Status =
                "DONE";

            P54RefreshAgentRow(
                state);

            P54AppendOutput(
                "===== "
                + state.Id
                + " / "
                + state.Branch
                + " ====="
                + System.Environment.NewLine
                + result);

            Dispatcher.Invoke(
                () =>
                    P52AddActivity(
                        "ISOLATED",
                        state.Id
                        + " completed"));
        }
        catch (
            System.OperationCanceledException)
        {
            state.Status =
                "STOPPED";

            state.Result =
                "Cancelled";

            P54RefreshAgentRow(
                state);

            P54AppendOutput(
                state.Id
                + " stopped.");

            Dispatcher.Invoke(
                () =>
                    P52AddActivity(
                        "ISOLATED",
                        state.Id
                        + " stopped"));
        }
        catch (
            System.Exception ex)
        {
            state.Status =
                "FAILED";

            state.Result =
                ex.Message;

            P54RefreshAgentRow(
                state);

            P54AppendOutput(
                state.Id
                + " failed: "
                + ex.Message);

            Dispatcher.Invoke(
                () =>
                    P52AddActivity(
                        "ERROR",
                        state.Id
                        + ": "
                        + ex.Message));
        }
    }


    private async void P54_Start_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        if (_p54Cancellation is not null)
        {
            return;
        }

        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            P54AgentOutput.Text =
                "Open a workspace first.";

            return;
        }

        var tasks =
            P54ReadTasks();

        if (tasks.Count == 0)
        {
            P54AgentOutput.Text =
                "Enter at least one task. Use one task per line.";

            return;
        }

        var cancellation =
            new System.Threading
                .CancellationTokenSource();

        _p54Cancellation =
            cancellation;

        P54StartButton.IsEnabled =
            false;

        P54StopButton.IsEnabled =
            true;

        P54AgentOutput.Clear();

        P54AgentList.Items.Clear();

        _p54Agents.Clear();

        string prefix =
            P54SafePrefix(
                P54BranchPrefixBox.Text);

        string p55BatchBaseHead =
            await P55CurrentMainHeadAsync();

        string batch =
            System.DateTime.UtcNow
                .ToString(
                    "yyyyMMddHHmmss")
            + "-"
            + System.Guid.NewGuid()
                .ToString("N")
                .Substring(
                    0,
                    6);

        try
        {
            P52AddActivity(
                "ISOLATED",
                "Preparing "
                + tasks.Count
                    .ToString()
                + " worktrees");

            for (
                int i=0;
                i<tasks.Count;
                i++)
            {
                cancellation.Token
                    .ThrowIfCancellationRequested();

                string id =
                    "agent-"
                    + (i+1)
                        .ToString("00");

                string branch =
                    prefix
                    + "-"
                    + batch
                    + "-"
                    + (i+1)
                        .ToString("00");

                var state =
                    new P54AgentState
                    {
                        Id=id,
                        TaskText=tasks[i],
                        Branch=branch,
                        BaseHead=p55BatchBaseHead,
                        Status="CREATING"
                    };

                _p54Agents.Add(
                    state);

                P54AgentList.Items.Add(
                    "");

                P54RefreshAgentRow(
                    state);

                try
                {
                    string create =
                        await V3ExecuteGitActionAsync(
                            "git_worktree_create",
                            branch,
                            null);

                    P54AppendOutput(
                        "Created "
                        + branch
                        + System.Environment.NewLine
                        + create);

                    string? path =
                        await P54FindWorktreeAsync(
                            branch);

                    if (
                        string.IsNullOrWhiteSpace(
                            path))
                    {
                        throw new System
                            .InvalidOperationException(
                                "Created worktree could not be resolved for "
                                + branch);
                    }

                    state.WorktreePath =
                        path;

                    await P55VerifyWorktreeBaseAsync(
                        state);

                    state.Status =
                        "READY";

                    P54RefreshAgentRow(
                        state);
                }
                catch (
                    System.Exception ex)
                {
                    state.Status =
                        "FAILED";

                    state.Result =
                        ex.Message;

                    P54RefreshAgentRow(
                        state);

                    P54AppendOutput(
                        id
                        + " worktree creation failed: "
                        + ex.Message);
                }
            }

            var running =
                new System.Collections.Generic
                    .List<
                        System.Threading.Tasks.Task>();

            foreach (
                P54AgentState state
                in _p54Agents)
            {
                if (
                    state.Status !=
                    "READY")
                {
                    continue;
                }

                running.Add(
                    P54RunOneAgentAsync(
                        state,
                        cancellation.Token));
            }

            if (running.Count == 0)
            {
                P54AppendOutput(
                    "No isolated agent could be started.");

                return;
            }

            P52AddActivity(
                "ISOLATED",
                running.Count.ToString()
                + " coding agents running");

            await System.Threading.Tasks
                .Task.WhenAll(
                    running);

            P54AppendOutput(
                "===== BATCH COMPLETE =====");

            P54AppendOutput(
                "Agent worktrees are preserved for review.");

            await P53RefreshWorktreesAsync();

            P52AddActivity(
                "ISOLATED",
                "Background coding batch completed");
        }
        catch (
            System.OperationCanceledException)
        {
            P54AppendOutput(
                "Batch stopped.");

            P52AddActivity(
                "ISOLATED",
                "Batch stopped");
        }
        catch (
            System.Exception ex)
        {
            P54AppendOutput(
                "Batch failed: "
                + ex.Message);

            P52AddActivity(
                "ERROR",
                "Isolated batch: "
                + ex.Message);
        }
        finally
        {
            if (
                object.ReferenceEquals(
                    _p54Cancellation,
                    cancellation))
            {
                _p54Cancellation =
                    null;
            }

            cancellation.Dispose();

            P54StartButton.IsEnabled =
                true;

            P54StopButton.IsEnabled =
                false;

            await P53RefreshWorktreesAsync();
        }
    }


    private void P54_Stop_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        _p54Cancellation?.Cancel();

        P52AddActivity(
            "ISOLATED",
            "Stop requested");
    }

    // BOTCONNECTOR_P5_3_PARALLEL_WORKTREE_CODE
    private System.Threading.CancellationTokenSource?
        _p53ParallelCancellation;

    private readonly
        System.Collections.Generic.List<string>
        _p53WorktreePaths =
            new();


    private async void P53_RunParallel_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        if (_p53ParallelCancellation is not null)
        {
            return;
        }

        string task =
            (P53TaskBox.Text ?? "")
            .Trim();

        if (string.IsNullOrWhiteSpace(task))
        {
            P53ParallelResults.Text =
                "Enter a task first.";

            return;
        }

        var cancellation =
            new System.Threading
                .CancellationTokenSource();

        _p53ParallelCancellation =
            cancellation;

        P53RunParallelButton.IsEnabled =
            false;

        P53StopParallelButton.IsEnabled =
            true;

        P53ParallelResults.Text =
            "Planner, Coder-A, Reviewer, and Tester are running in parallel...";

        P52AddActivity(
            "PARALLEL",
            "Started Planner · Coder-A · Reviewer · Tester");

        try
        {
            string result =
                await V3RunParallelAdvisorsAsync(
                    task,
                    cancellation.Token);

            P53ParallelResults.Text =
                result;

            P52AddActivity(
                "PARALLEL",
                "Four advisor tasks completed");
        }
        catch (
            System.OperationCanceledException)
        {
            P53ParallelResults.Text =
                "Parallel task stopped.";

            P52AddActivity(
                "PARALLEL",
                "Stopped");
        }
        catch (
            System.Exception ex)
        {
            P53ParallelResults.Text =
                "Parallel task failed: "
                + ex.Message;

            P52AddActivity(
                "ERROR",
                "Parallel task: "
                + ex.Message);
        }
        finally
        {
            if (
                object.ReferenceEquals(
                    _p53ParallelCancellation,
                    cancellation))
            {
                _p53ParallelCancellation =
                    null;
            }

            cancellation.Dispose();

            P53RunParallelButton.IsEnabled =
                true;

            P53StopParallelButton.IsEnabled =
                false;
        }
    }


    private void P53_StopParallel_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        _p53ParallelCancellation?.Cancel();
    }


    private async void
        P53_RefreshWorktrees_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        await P53RefreshWorktreesAsync();
    }


    private async System.Threading.Tasks.Task
        P53RefreshWorktreesAsync()
    {
        try
        {
            string output =
                await V3ExecuteGitActionAsync(
                    "git_worktree_list",
                    null,
                    null);

            P53WorktreeOutput.Text =
                output;

            _p53WorktreePaths.Clear();

            P53WorktreeList.Items.Clear();

            string[] lines =
                output.Split(
                    new[]
                    {
                        '\r',
                        '\n'
                    },
                    System.StringSplitOptions
                        .RemoveEmptyEntries);

            foreach (
                string rawLine
                in lines)
            {
                string line =
                    rawLine.Trim();

                if (
                    !line.StartsWith(
                        "worktree ",
                        System.StringComparison
                            .Ordinal))
                {
                    continue;
                }

                string path =
                    line.Substring(
                        "worktree ".Length)
                    .Trim();

                if (
                    string.IsNullOrWhiteSpace(
                        path))
                {
                    continue;
                }

                _p53WorktreePaths.Add(
                    path);

                string normalized =
                    path.TrimEnd(
                        System.IO.Path
                            .DirectorySeparatorChar,
                        System.IO.Path
                            .AltDirectorySeparatorChar);

                string leaf =
                    System.IO.Path
                        .GetFileName(
                            normalized);

                if (
                    string.IsNullOrWhiteSpace(
                        leaf))
                {
                    leaf =
                        path;
                }

                P53WorktreeList.Items.Add(
                    leaf
                    + "  —  "
                    + path);
            }

            P52AddActivity(
                "WORKTREE",
                _p53WorktreePaths.Count
                    .ToString()
                + " worktree"
                + (
                    _p53WorktreePaths.Count == 1
                        ? ""
                        : "s"
                ));
        }
        catch (
            System.Exception ex)
        {
            P53WorktreeOutput.Text =
                "Worktree refresh failed: "
                + ex.Message;

            P52AddActivity(
                "ERROR",
                "Worktree refresh: "
                + ex.Message);
        }
    }


    private async void
        P53_CreateWorktree_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        string branch =
            (P53BranchBox.Text ?? "")
            .Trim();

        if (
            string.IsNullOrWhiteSpace(
                branch))
        {
            P53WorktreeOutput.Text =
                "Enter a branch name.";

            return;
        }

        try
        {
            string result =
                await V3ExecuteGitActionAsync(
                    "git_worktree_create",
                    branch,
                    null);

            P53WorktreeOutput.Text =
                result;

            P52AddActivity(
                "WORKTREE",
                "Create "
                + branch);

            await P53RefreshWorktreesAsync();
        }
        catch (
            System.Exception ex)
        {
            P53WorktreeOutput.Text =
                "Create failed: "
                + ex.Message;

            P52AddActivity(
                "ERROR",
                "Worktree create: "
                + ex.Message);
        }
    }


    private async void
        P53_RemoveWorktree_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        int index =
            P53WorktreeList.SelectedIndex;

        if (
            index < 0
            ||
            index >=
                _p53WorktreePaths.Count)
        {
            P53WorktreeOutput.Text =
                "Select a worktree first.";

            return;
        }

        string selected =
            _p53WorktreePaths[index];

        try
        {
            if (
                !string.IsNullOrWhiteSpace(
                    _workspace))
            {
                string current =
                    System.IO.Path.GetFullPath(
                        _workspace)
                    .TrimEnd(
                        System.IO.Path
                            .DirectorySeparatorChar,
                        System.IO.Path
                            .AltDirectorySeparatorChar);

                string candidate =
                    System.IO.Path.GetFullPath(
                        selected)
                    .TrimEnd(
                        System.IO.Path
                            .DirectorySeparatorChar,
                        System.IO.Path
                            .AltDirectorySeparatorChar);

                if (
                    string.Equals(
                        current,
                        candidate,
                        System.StringComparison
                            .OrdinalIgnoreCase))
                {
                    P53WorktreeOutput.Text =
                        "The active workspace cannot be removed.";

                    return;
                }
            }

            string normalized =
                selected.TrimEnd(
                    System.IO.Path
                        .DirectorySeparatorChar,
                    System.IO.Path
                        .AltDirectorySeparatorChar);

            string leaf =
                System.IO.Path.GetFileName(
                    normalized);

            if (
                string.IsNullOrWhiteSpace(
                    leaf))
            {
                P53WorktreeOutput.Text =
                    "Invalid worktree path.";

                return;
            }

            string result =
                await V3ExecuteGitActionAsync(
                    "git_worktree_remove",
                    leaf,
                    null);

            P53WorktreeOutput.Text =
                result;

            P52AddActivity(
                "WORKTREE",
                "Remove "
                + leaf);

            await P53RefreshWorktreesAsync();
        }
        catch (
            System.Exception ex)
        {
            P53WorktreeOutput.Text =
                "Remove failed: "
                + ex.Message;

            P52AddActivity(
                "ERROR",
                "Worktree remove: "
                + ex.Message);
        }
    }

    // BOTCONNECTOR_P5_2_ACTIVITY_REVIEW_CODE
    private readonly System.Collections.Generic.List<string>
        _p52ActivityEntries = new();

    private string _p52LastReviewFingerprint = "";


    private void P52AddActivity(
        string kind,
        string detail)
    {
        try
        {
            string normalized =
                (detail ?? "")
                .Replace("\r", " ")
                .Replace("\n", " ")
                .Trim();

            if (normalized.Length > 240)
            {
                normalized =
                    normalized.Substring(
                        0,
                        240)
                    + "...";
            }

            string line =
                System.DateTime.Now
                    .ToString("HH:mm:ss")
                + "  "
                + kind
                + "  "
                + normalized;

            _p52ActivityEntries.Add(line);

            const int maxEntries = 200;

            if (
                _p52ActivityEntries.Count
                > maxEntries)
            {
                _p52ActivityEntries.RemoveRange(
                    0,
                    _p52ActivityEntries.Count
                    - maxEntries);
            }

            P52ActivityTimeline.Text =
                string.Join(
                    System.Environment.NewLine,
                    _p52ActivityEntries);

            P52ActivityTimeline.ScrollToEnd();
        }
        catch
        {
            // UI telemetry may not break an agent run.
        }
    }


    private string P52SummarizeToolResults(
        string result)
    {
        if (
            string.IsNullOrWhiteSpace(
                result))
        {
            return "Tool actions completed";
        }

        string normalized =
            result
            .Replace("\r", " ")
            .Replace("\n", " ")
            .Trim();

        while (
            normalized.Contains(
                "  "))
        {
            normalized =
                normalized.Replace(
                    "  ",
                    " ");
        }

        if (normalized.Length > 220)
        {
            normalized =
                normalized.Substring(
                    0,
                    220)
                + "...";
        }

        return normalized;
    }


    private async System.Threading.Tasks.Task<
        (int ExitCode, string Stdout, string Stderr)>
        P52RunGitAsync(
            params string[] arguments)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            return (
                1,
                "",
                "No workspace");
        }

        var psi =
            new System.Diagnostics.ProcessStartInfo
            {
                FileName = "git",
                WorkingDirectory = _workspace,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

        foreach (
            string argument
            in arguments)
        {
            psi.ArgumentList.Add(
                argument);
        }

        using var process =
            new System.Diagnostics.Process
            {
                StartInfo = psi
            };

        process.Start();

        var stdoutTask =
            process.StandardOutput
                .ReadToEndAsync();

        var stderrTask =
            process.StandardError
                .ReadToEndAsync();

        await process.WaitForExitAsync();

        return (
            process.ExitCode,
            await stdoutTask,
            await stderrTask);
    }


    private string P52PathFromGitStatus(
        string line)
    {
        if (
            string.IsNullOrWhiteSpace(
                line))
        {
            return "";
        }

        string path =
            line.Length > 3
                ? line.Substring(3).Trim()
                : line.Trim();

        int rename =
            path.LastIndexOf(
                " -> ",
                System.StringComparison.Ordinal);

        if (rename >= 0)
        {
            path =
                path.Substring(
                    rename + 4)
                .Trim();
        }

        if (
            path.Length >= 2
            && path[0] == '"'
            && path[^1] == '"')
        {
            path =
                path.Substring(
                    1,
                    path.Length - 2);
        }

        return path;
    }


    private async System.Threading.Tasks.Task
        P52RefreshReviewAsync()
    {
        try
        {
            if (
                string.IsNullOrWhiteSpace(
                    _workspace)
                ||
                !System.IO.Directory.Exists(
                    _workspace))
            {
                P52ReviewSummary.Text =
                    "No workspace open";

                V2ChangedFiles.Items.Clear();

                return;
            }

            var status =
                await P52RunGitAsync(
                    "status",
                    "--short");

            if (status.ExitCode != 0)
            {
                P52ReviewSummary.Text =
                    "Git status failed: "
                    + status.Stderr.Trim();

                return;
            }

            var diff =
                await P52RunGitAsync(
                    "diff",
                    "--stat",
                    "HEAD");

            string[] statusLines =
                status.Stdout.Split(
                    new[]
                    {
                        '\r',
                        '\n'
                    },
                    System.StringSplitOptions
                        .RemoveEmptyEntries);

            V2ChangedFiles.Items.Clear();

            foreach (
                string statusLine
                in statusLines)
            {
                string path =
                    P52PathFromGitStatus(
                        statusLine);

                if (
                    !string.IsNullOrWhiteSpace(
                        path))
                {
                    V2ChangedFiles.Items.Add(
                        path);
                }
            }

            string stat =
                diff.ExitCode == 0
                    ? diff.Stdout.Trim()
                    : "";

            string summary =
                statusLines.Length.ToString()
                + " changed file"
                + (
                    statusLines.Length == 1
                        ? ""
                        : "s"
                );

            if (
                !string.IsNullOrWhiteSpace(
                    stat))
            {
                summary +=
                    System.Environment.NewLine
                    + stat;
            }
            else if (
                statusLines.Length == 0)
            {
                summary +=
                    System.Environment.NewLine
                    + "Working tree clean";
            }

            P52ReviewSummary.Text =
                summary;

            string fingerprint =
                status.Stdout
                + "\n"
                + stat;

            if (
                !string.Equals(
                    fingerprint,
                    _p52LastReviewFingerprint,
                    System.StringComparison.Ordinal))
            {
                _p52LastReviewFingerprint =
                    fingerprint;

                P52AddActivity(
                    "REVIEW",
                    statusLines.Length.ToString()
                    + " changed file"
                    + (
                        statusLines.Length == 1
                            ? ""
                            : "s"
                    ));
            }
        }
        catch (
            System.Exception ex)
        {
            P52ReviewSummary.Text =
                "Review refresh failed: "
                + ex.Message;

            P52AddActivity(
                "ERROR",
                "Review refresh: "
                + ex.Message);
        }
    }


    private async void
        P52_ReviewRefresh_Click(
            object sender,
            System.Windows.RoutedEventArgs e)
    {
        await P52RefreshReviewAsync();
    }

    // BOTCONNECTOR_MAIN_LLM_EDITOR_CODE_V1
    private string? _codexEditorFile;
    private bool _codexEditorLoading;
    private bool _codexEditorDirty;
    private string _codexEditorNewLine =
        System.Environment.NewLine;


    private void Codex_FileList_OpenEditor(
        object sender,
        System.Windows.Input.MouseButtonEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(_workspace) ||
            FileList.SelectedItem is not string item)
        {
            return;
        }

        Codex_OpenWorkspaceFile(item);

        e.Handled = true;
    }


    private void Codex_OpenWorkspaceFile(
        string item)
    {
        try
        {
            if (
                !Codex_TryResolveWorkspaceFile(
                    item,
                    out string file))
            {
                StatusText.Text =
                    "Blocked: file outside workspace";

                return;
            }

            if (!System.IO.File.Exists(file))
            {
                StatusText.Text =
                    "File not found";

                return;
            }

            var info =
                new System.IO.FileInfo(file);

            if (
                info.Length >
                2 * 1024 * 1024)
            {
                StatusText.Text =
                    "File too large for editor (>2 MB)";

                return;
            }

            byte[] raw =
                System.IO.File.ReadAllBytes(file);

            int previewLength =
                System.Math.Min(
                    raw.Length,
                    4096);

            for (
                int i = 0;
                i < previewLength;
                i++)
            {
                if (raw[i] == 0)
                {
                    StatusText.Text =
                        "Binary file cannot be opened in text editor";

                    return;
                }
            }

            string text =
                System.IO.File.ReadAllText(file);

            if (text.Contains("\r\n"))
            {
                _codexEditorNewLine =
                    "\r\n";
            }
            else if (text.Contains("\n"))
            {
                _codexEditorNewLine =
                    "\n";
            }
            else
            {
                _codexEditorNewLine =
                    System.Environment.NewLine;
            }

            _codexEditorLoading =
                true;

            try
            {
                CodeEditorText.Text =
                    text;

                _codexEditorFile =
                    file;

                CodeEditorPath.Text =
                    System.IO.Path.GetRelativePath(
                        _workspace!,
                        file);

                CodeEditorState.Text =
                    "Loaded";

                CodeEditorSaveButton.IsEnabled =
                    false;

                _codexEditorDirty =
                    false;
            }
            finally
            {
                _codexEditorLoading =
                    false;
            }

            InspectorTabs.SelectedItem =
                CodeEditorTab;

            StatusText.Text =
                "Editing "
                + CodeEditorPath.Text;

            AppendTerminal(
                "[editor] opened "
                + CodeEditorPath.Text);
        }
        catch (System.Exception ex)
        {
            AppendTerminal(
                "[editor] "
                + ex.Message);

            StatusText.Text =
                "Editor error";
        }
    }


    private bool Codex_TryResolveWorkspaceFile(
        string value,
        out string file)
    {
        file = "";

        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            return false;
        }

        string root =
            System.IO.Path
                .GetFullPath(_workspace)
                .TrimEnd(
                    System.IO.Path
                        .DirectorySeparatorChar,
                    System.IO.Path
                        .AltDirectorySeparatorChar);

        string candidate;

        if (
            System.IO.Path.IsPathRooted(
                value))
        {
            candidate =
                System.IO.Path.GetFullPath(
                    value);
        }
        else
        {
            candidate =
                System.IO.Path.GetFullPath(
                    System.IO.Path.Combine(
                        root,
                        value));
        }

        string prefix =
            root
            + System.IO.Path
                .DirectorySeparatorChar;

        if (
            !candidate.StartsWith(
                prefix,
                System.StringComparison
                    .OrdinalIgnoreCase))
        {
            return false;
        }

        file = candidate;

        return true;
    }


    private void Codex_EditorTextChanged(
        object sender,
        System.Windows.Controls
            .TextChangedEventArgs e)
    {
        if (
            _codexEditorLoading ||
            string.IsNullOrWhiteSpace(
                _codexEditorFile))
        {
            return;
        }

        _codexEditorDirty = true;

        CodeEditorState.Text =
            "Modified";

        CodeEditorSaveButton.IsEnabled =
            true;
    }


    private void Codex_EditorSave_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        Codex_SaveEditor();
    }


    private void Codex_SaveEditor()
    {
        if (
            string.IsNullOrWhiteSpace(
                _codexEditorFile))
        {
            return;
        }

        try
        {
            if (
                !Codex_TryResolveWorkspaceFile(
                    _codexEditorFile,
                    out string file))
            {
                StatusText.Text =
                    "Blocked: write outside workspace";

                return;
            }

            string text =
                CodeEditorText.Text
                ?? "";

            text =
                text.Replace(
                    "\r\n",
                    "\n")
                .Replace(
                    "\r",
                    "\n");

            if (
                _codexEditorNewLine
                != "\n")
            {
                text =
                    text.Replace(
                        "\n",
                        _codexEditorNewLine);
            }

            System.IO.File.WriteAllText(
                file,
                text,
                new System.Text.UTF8Encoding(
                    false));

            _codexEditorDirty =
                false;

            CodeEditorSaveButton.IsEnabled =
                false;

            CodeEditorState.Text =
                "Saved";

            StatusText.Text =
                "Saved "
                + CodeEditorPath.Text;

            AppendTerminal(
                "[editor] saved "
                + CodeEditorPath.Text);

            RefreshFileTree();

            P52AddActivity(
                "EDIT",
                "Saved "
                + CodeEditorPath.Text);

            _ =
                P52RefreshReviewAsync();
        }
        catch (System.Exception ex)
        {
            CodeEditorState.Text =
                "Save failed";

            AppendTerminal(
                "[editor] "
                + ex.Message);

            StatusText.Text =
                "Save failed";
        }
    }


    private void Codex_EditorReload_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        if (
            string.IsNullOrWhiteSpace(
                _codexEditorFile))
        {
            return;
        }

        if (_codexEditorDirty)
        {
            var result =
                System.Windows.MessageBox.Show(
                    "Discard unsaved editor changes?",
                    "BotConnector Editor",
                    System.Windows
                        .MessageBoxButton.YesNo,
                    System.Windows
                        .MessageBoxImage.Question);

            if (
                result !=
                System.Windows
                    .MessageBoxResult.Yes)
            {
                return;
            }
        }

        Codex_OpenWorkspaceFile(
            _codexEditorFile);
    }


    private void Codex_EditorKeyDown(
        object sender,
        System.Windows.Input.KeyEventArgs e)
    {
        bool control =
            (
                System.Windows.Input.Keyboard
                    .Modifiers
                &
                System.Windows.Input
                    .ModifierKeys.Control
            ) != 0;

        if (
            control
            &&
            e.Key ==
                System.Windows.Input.Key.S)
        {
            e.Handled = true;

            Codex_SaveEditor();
        }
    }

    private string
        BuildAgentPrompt(
            string userPrompt)
    {
        string workspace =
            string.IsNullOrWhiteSpace(
                _workspace)
                ? "(no workspace open)"
                : _workspace;

        string files =
            "";

        if (
            !string.IsNullOrWhiteSpace(
                _workspace) &&
            Directory.Exists(
                _workspace))
        {
            try
            {
                files =
                    string.Join(
                        "\n",
                        Directory
                            .EnumerateFiles(
                                _workspace,
                                "*",
                                SearchOption
                                    .AllDirectories)
                            .Take(250)
                            .Select(
                                x =>
                                    Path.GetRelativePath(
                                        _workspace,
                                        x)));
            }
            catch
            {
                files = "";
            }
        }

        return
            "You are BotConnector Desktop AI, " +
            "a coding agent working with the user's " +
            "approved Windows workspace." +
            "\n\nWorkspace:\n" +
            workspace +
            "\n\nKnown files:\n" +
            files +
            "\n\nUSER TASK:\n" +
            userPrompt +
            "\n\nLOCAL TOOL PROTOCOL:\n" +
            "When local workspace operations are needed, " +
            "append exactly one block in this format:\n" +
            "<botconnector_actions>\n" +
            "{\"actions\":[" +
            "{\"type\":\"search\",\"query\":\"regex or text\"}," +
            "{\"type\":\"read_file\",\"path\":\"relative/path\"}," +
            "{\"type\":\"edit_file\",\"path\":\"relative/path\",\"find\":\"exact unique snippet to replace\",\"replace\":\"new text\"}," +
            "{\"type\":\"write_file\",\"path\":\"relative/path\",\"content\":\"full file content\"}," +
            "{\"type\":\"run\",\"command\":\"command\"}" +
            "]}\n" +
            "</botconnector_actions>\n\n" +
            "Tool guidance:\n" +
            "- Use search to locate code, then read_file before editing.\n" +
            "- PREFER edit_file for changes to existing files: 'find' must be an " +
            "EXACT, UNIQUE snippet from the current file (copy it verbatim, including " +
            "whitespace); it is replaced by 'replace'. If the result says NO_MATCH or " +
            "AMBIGUOUS, re-read the file and use a longer unique snippet.\n" +
            "- Use write_file ONLY to create a new file or fully rewrite a small one.\n" +
            "- JSON must be strictly valid: escape every quote, newline and backslash " +
            "inside string values.\n" +
            "Only request actions actually needed. " +
            "Paths must be relative to the approved workspace. " +
            "Do not request writes to .git or .botconnector. " +
            "run commands require the user's approval and execute inside the existing " +
            "BotConnector sandbox. " +
            "After tool results are returned, continue until the task is complete.";
    }


    private static string
        ExtractAssistantText(
            System.Text.Json.JsonElement element)
    {
        string? value =
            FindText(element);

        if (
            !string.IsNullOrWhiteSpace(
                value))
        {
            return value;
        }

        return System.Text.Json
            .JsonSerializer.Serialize(
                element,
                new System.Text.Json
                    .JsonSerializerOptions
                {
                    WriteIndented = true
                });
    }


    private static string?
        FindText(
            System.Text.Json.JsonElement element)
    {
        if (
            element.ValueKind ==
            System.Text.Json.JsonValueKind.String)
        {
            return element.GetString();
        }

        if (
            element.ValueKind ==
            System.Text.Json.JsonValueKind.Object)
        {
            foreach (
                string name
                in new[]
                {
                    "content",
                    "text",
                    "answer",
                    "response",
                    "assistant",
                    "message",
                    "output"
                })
            {
                System.Text.Json.JsonElement child;

                if (
                    element.TryGetProperty(
                        name,
                        out child))
                {
                    string? found =
                        FindText(child);

                    if (
                        !string.IsNullOrWhiteSpace(
                            found))
                    {
                        return found;
                    }
                }
            }

            foreach (
                string container
                in new[]
                {
                    "result",
                    "data",
                    "assistant_message",
                    "assistant_response",
                    "completion",
                    "response_message"
                })
            {
                System.Text.Json.JsonElement child;

                if (
                    element.TryGetProperty(
                        container,
                        out child))
                {
                    string? found =
                        FindText(child);

                    if (
                        !string.IsNullOrWhiteSpace(
                            found))
                    {
                        return found;
                    }
                }
            }
        }

        if (
            element.ValueKind ==
            System.Text.Json.JsonValueKind.Array)
        {
            foreach (
                var child
                in element.EnumerateArray())
            {
                string? found =
                    FindText(child);

                if (
                    !string.IsNullOrWhiteSpace(
                        found))
                {
                    return found;
                }
            }
        }

        return null;
    }


    private static System.Collections.Generic.List<AgentAction>?
        ExtractAgentActions(
            string text)
    {
        const string begin =
            "<botconnector_actions>";

        const string end =
            "</botconnector_actions>";

        int a =
            text.IndexOf(
                begin,
                System.StringComparison.Ordinal);

        if (a < 0)
            return null;

        int b =
            text.IndexOf(
                end,
                a,
                System.StringComparison.Ordinal);

        if (b < 0)
            return null;

        int start =
            a + begin.Length;

        string json =
            text.Substring(
                start,
                b - start)
            .Trim();

        // Tolerate models that wrap the JSON in a markdown code fence
        // (```json ... ```), a very common formatting mistake.
        if (json.StartsWith("```"))
        {
            int nl = json.IndexOf('\n');
            if (nl >= 0)
                json = json.Substring(nl + 1);
        }
        if (json.EndsWith("```"))
        {
            json = json.Substring(0, json.Length - 3);
        }
        json = json.Trim();

        var options =
            new System.Text.Json.JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
                AllowTrailingCommas = true,
                ReadCommentHandling =
                    System.Text.Json.JsonCommentHandling.Skip
            };

        try
        {
            AgentActionEnvelope? envelope =
                System.Text.Json.JsonSerializer
                    .Deserialize<AgentActionEnvelope>(
                        json,
                        options);

            return envelope?.actions;
        }
        catch
        {
            return null;
        }
    }


    private static string
        RemoveActionBlock(
            string text)
    {
        const string begin =
            "<botconnector_actions>";

        const string end =
            "</botconnector_actions>";

        int a =
            text.IndexOf(
                begin,
                System.StringComparison.Ordinal);

        if (a < 0)
            return text.Trim();

        int b =
            text.IndexOf(
                end,
                a,
                System.StringComparison.Ordinal);

        if (b < 0)
            return text
                .Substring(0,a)
                .Trim();

        return (
            text.Substring(0,a) +
            text.Substring(
                b + end.Length)
        ).Trim();
    }


    private string
        ResolveAgentPath(
            string relative)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            throw new InvalidOperationException(
                "Open a workspace first.");
        }

        if (
            string.IsNullOrWhiteSpace(
                relative) ||
            Path.IsPathRooted(
                relative))
        {
            throw new InvalidOperationException(
                "Invalid workspace path.");
        }

        string root =
            Path.GetFullPath(
                _workspace)
            .TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);

        string full =
            Path.GetFullPath(
                Path.Combine(
                    root,
                    relative));

        string prefix =
            root +
            Path.DirectorySeparatorChar;

        if (
            !full.StartsWith(
                prefix,
                System.StringComparison
                    .OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "Path escaped workspace.");
        }

        string rel =
            Path.GetRelativePath(
                root,
                full)
            .Replace(
                Path.AltDirectorySeparatorChar,
                Path.DirectorySeparatorChar);

        if (
            rel.Equals(
                ".git",
                System.StringComparison
                    .OrdinalIgnoreCase) ||
            rel.StartsWith(
                ".git" +
                Path.DirectorySeparatorChar,
                System.StringComparison
                    .OrdinalIgnoreCase) ||
            rel.Equals(
                ".botconnector",
                System.StringComparison
                    .OrdinalIgnoreCase) ||
            rel.StartsWith(
                ".botconnector" +
                Path.DirectorySeparatorChar,
                System.StringComparison
                    .OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "Protected workspace metadata.");
        }

        return full;
    }


    private async System.Threading.Tasks.Task<string>
        ExecuteAgentActionsAsync(
            System.Collections.Generic.List<AgentAction>
                actions)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            return "ERROR: no workspace open";
        }

        var report =
            new System.Text.StringBuilder();

        foreach (
            AgentAction action
            in actions.Take(8))
        {
            string type =
                action.type?.Trim()
                .ToLowerInvariant()
                ?? "";

            try
            {
                if (type == "read_file")
                {
                    SetAgentActivity(
                        "Reading " +
                        action.path);
                    string full =
                        ResolveAgentPath(
                            action.path ?? "");

                    if (!File.Exists(full))
                    {
                        report.AppendLine(
                            "read_file: missing " +
                            action.path);

                        continue;
                    }

                    FileInfo info =
                        new FileInfo(full);

                    if (
                        info.Length >
                        512 * 1024)
                    {
                        report.AppendLine(
                            "read_file: too large " +
                            action.path);

                        continue;
                    }

                    string content =
                        File.ReadAllText(full);

                    report.AppendLine(
                        "read_file " +
                        action.path +
                        ":");

                    report.AppendLine(
                        content);

                    continue;
                }

                if (type == "write_file")
                {
                    StatusText.Text =
                        "Editing " +
                        action.path;

                    string full =
                        ResolveAgentPath(
                            action.path ?? "");

                    string content =
                        action.content ?? "";

                    long beforeBytes =
                        File.Exists(full)
                            ? new FileInfo(full).Length
                            : 0;

                    string path64 =
                        Convert.ToBase64String(
                            Encoding.UTF8.GetBytes(
                                full));

                    string content64 =
                        Convert.ToBase64String(
                            Encoding.UTF8.GetBytes(
                                content));

                    string helperName =
                        ".bc-agent-write-" +
                        Guid.NewGuid().ToString("N") +
                        ".ps1";

                    string helperPath =
                        Path.Combine(
                            _workspace,
                            helperName);

                    string helperScript =
                        "$ErrorActionPreference='Stop';" +
                        "$p=[Text.Encoding]::UTF8.GetString(" +
                        "[Convert]::FromBase64String('" +
                        path64 +
                        "'));" +
                        "$c=[Text.Encoding]::UTF8.GetString(" +
                        "[Convert]::FromBase64String('" +
                        content64 +
                        "'));" +
                        "$d=[IO.Path]::GetDirectoryName($p);" +
                        "if($d){" +
                        "[IO.Directory]::CreateDirectory($d)|Out-Null};" +
                        "[IO.File]::WriteAllText(" +
                        "$p,$c,[Text.UTF8Encoding]::new($false));";

                    File.WriteAllText(
                        helperPath,
                        helperScript,
                        new UTF8Encoding(false));

                    try
                    {
                        string powerShellExe =
                            Path.Combine(
                                Environment.GetFolderPath(
                                    Environment.SpecialFolder.Windows),
                                "System32",
                                "WindowsPowerShell",
                                "v1.0",
                                "powershell.exe");

                        string cmdArgs =
                            "/d /s /c " +
                            "\"\"" +
                            powerShellExe +
                            "\" " +
                            "-NoLogo " +
                            "-NoProfile " +
                            "-NonInteractive " +
                            "-ExecutionPolicy Bypass " +
                            "-File \"" +
                            helperPath +
                            "\"\"";

                        string args64 =
                            Convert.ToBase64String(
                                Encoding.UTF8.GetBytes(
                                    cmdArgs));

                        AppendTerminal(
                            "[Agent] Editing " +
                            action.path);

                        string output =
                            await RunPowerShellAsync(
                                new[]
                                {
                                    "-NoProfile",
                                    "-ExecutionPolicy",
                                    "Bypass",
                                    "-File",
                                    BrokerPath,
                                    "run",
                                    "-Workspace",
                                    _workspace,
                                    "-Mode",
                                    "offline",
                                    "-Exe",
                                    Path.Combine(
                                        Environment.GetFolderPath(
                                            Environment.SpecialFolder.Windows),
                                        "System32",
                                        "cmd.exe"),
                                    "-ArgumentsB64",
                                    args64
                                });

                        AppendTerminal(
                            output);
                    }
                    finally
                    {
                        try
                        {
                            if (
                                File.Exists(
                                    helperPath))
                            {
                                File.Delete(
                                    helperPath);
                            }
                        }
                        catch
                        {
                        }
                    }

                    long afterBytes =
                        File.Exists(full)
                            ? new FileInfo(full).Length
                            : 0;

                    AppendTerminal(
                        "~ " +
                        action.path +
                        "  " +
                        beforeBytes +
                        " -> " +
                        afterBytes +
                        " bytes");

                    report.AppendLine(
                        "write_file " +
                        action.path +
                        ":");

                    if (!File.Exists(full))
                    {
                        report.AppendLine(
                            "write_file VERIFY=FILE_MISSING");
                    }
                    else
                    {
                        string verify =
                            File.ReadAllText(
                                full);

                        if (
                            string.Equals(
                                verify,
                                content,
                                StringComparison.Ordinal))
                        {
                            report.AppendLine(
                                "write_file VERIFY=PASS");
                        }
                        else
                        {
                            report.AppendLine(
                                "write_file VERIFY=CONTENT_MISMATCH");
                        }
                    }

                    continue;
                }

                if (type == "edit_file")
                {
                    SetAgentActivity(
                        "Editing " + action.path);

                    string full =
                        ResolveAgentPath(
                            action.path ?? "");

                    if (!File.Exists(full))
                    {
                        report.AppendLine(
                            "edit_file: missing " +
                            action.path +
                            " (use write_file to create it)");

                        continue;
                    }

                    string find =
                        action.find ?? "";

                    string replaceWith =
                        action.replace ?? "";

                    if (string.IsNullOrEmpty(find))
                    {
                        report.AppendLine(
                            "edit_file ERROR: empty 'find' anchor for " +
                            action.path);

                        continue;
                    }

                    string original =
                        File.ReadAllText(full);

                    int occurrences =
                        CountOccurrences(
                            original,
                            find);

                    if (occurrences == 0)
                    {
                        report.AppendLine(
                            "edit_file NO_MATCH: anchor not found in " +
                            action.path +
                            ". Re-read the file and copy an exact snippet.");

                        continue;
                    }

                    if (occurrences > 1)
                    {
                        report.AppendLine(
                            "edit_file AMBIGUOUS: anchor appears " +
                            occurrences +
                            " times in " +
                            action.path +
                            ". Provide a longer unique 'find' snippet.");

                        continue;
                    }

                    int idx =
                        original.IndexOf(
                            find,
                            StringComparison.Ordinal);

                    string updated =
                        original.Substring(0, idx) +
                        replaceWith +
                        original.Substring(
                            idx + find.Length);

                    File.WriteAllText(
                        full,
                        updated,
                        new UTF8Encoding(false));

                    AppendTerminal(
                        "~ edit " +
                        action.path +
                        "  " +
                        original.Length +
                        " -> " +
                        updated.Length +
                        " chars");

                    report.AppendLine(
                        "edit_file OK: " +
                        action.path);

                    continue;
                }

                if (type == "search")
                {
                    SetAgentActivity(
                        "Searching...");

                    string q =
                        action.query ??
                        action.content ??
                        "";

                    if (
                        string.IsNullOrWhiteSpace(q))
                    {
                        report.AppendLine(
                            "search ERROR: empty query");

                        continue;
                    }

                    string searchResult =
                        SearchWorkspace(q);

                    report.AppendLine(
                        "search '" + q + "':");

                    report.AppendLine(
                        searchResult);

                    continue;
                }

                if (
                    type == "git_status" ||
                    type == "git_diff" ||
                    type == "git_commit" ||
                    type == "git_worktree_list" ||
                    type == "git_worktree_create" ||
                    type == "git_worktree_remove")
                {
                    string gitResult =
                        await V3ExecuteGitActionAsync(
                            type,
                            action.path,
                            action.content);

                    AppendTerminal(
                        "[V3 " +
                        type +
                        "]");

                    AppendTerminal(
                        gitResult);

                    report.AppendLine(
                        type +
                        ":");

                    report.AppendLine(
                        gitResult);

                    continue;
                }


                if (type == "validate")
                {
                    string validation =
                        await V3RunAutoValidationAsync();

                    AppendTerminal(
                        "[V3 validate]");

                    AppendTerminal(
                        validation);

                    report.AppendLine(
                        "validate:");

                    report.AppendLine(
                        validation);

                    continue;
                }

                if (type == "run")
                {
                    SetAgentActivity(
                        "Running command...");
                    string command =
                        action.command?.Trim()
                        ?? "";

                    if (
                        string.IsNullOrWhiteSpace(
                            command))
                    {
                        continue;
                    }

                    if (!ConfirmRunCommand(command))
                    {
                        AppendTerminal(
                            "> DENIED (user): " +
                            command);

                        report.AppendLine(
                            "run: DENIED_BY_USER - command not executed: " +
                            command);

                        continue;
                    }

                    string mode =
                        ModeBox.SelectedIndex == 1
                            ? "online"
                            : "offline";

                    string cmdArgs =
                        "/d /c " +
                        command;

                    string b64 =
                        Convert.ToBase64String(
                            Encoding.UTF8.GetBytes(
                                cmdArgs));

                    AppendTerminal(
                        "> AI: " +
                        command);

                    string output =
                        await RunPowerShellAsync(
                            new[]
                            {
                                "-NoProfile",
                                "-ExecutionPolicy",
                                "Bypass",
                                "-File",
                                BrokerPath,
                                "run",
                                "-Workspace",
                                _workspace,
                                "-Mode",
                                mode,
                                "-Exe",
                                Path.Combine(
                                    Environment.GetFolderPath(
                                        Environment.SpecialFolder
                                            .Windows),
                                    "System32",
                                    "cmd.exe"),
                                "-ArgumentsB64",
                                b64
                            });

                    AppendTerminal(output);

                    report.AppendLine(
                        "run:");

                    report.AppendLine(
                        output);

                    continue;
                }

                report.AppendLine(
                    "Unsupported action: " +
                    type);
            }
            catch (
                System.Exception ex)
            {
                report.AppendLine(
                    type +
                    " ERROR: " +
                    ex.Message);
            }
        }

        return report.ToString();
    }


    // Per-session: once the user picks "allow all", stop prompting for run.
    private bool _runAutoApprove;

    private bool ConfirmRunCommand(
        string command)
    {
        if (_runAutoApprove)
        {
            return true;
        }

        System.Windows.MessageBoxResult result =
            System.Windows.MessageBox.Show(
                "The AI wants to run this command in your workspace:\n\n" +
                command +
                "\n\n[Yes] Run once   " +
                "[No] Skip   " +
                "[Cancel] Allow all for this session",
                "Approve command",
                System.Windows.MessageBoxButton.YesNoCancel,
                System.Windows.MessageBoxImage.Warning);

        if (result == System.Windows.MessageBoxResult.Cancel)
        {
            _runAutoApprove = true;
            return true;
        }

        return result == System.Windows.MessageBoxResult.Yes;
    }

    private static int CountOccurrences(
        string haystack,
        string needle)
    {
        if (string.IsNullOrEmpty(needle))
        {
            return 0;
        }

        int count = 0;
        int i = 0;

        while (
            (i = haystack.IndexOf(
                needle,
                i,
                StringComparison.Ordinal)) >= 0)
        {
            count++;
            i += needle.Length;
        }

        return count;
    }

    private string SearchWorkspace(
        string query)
    {
        if (
            string.IsNullOrWhiteSpace(_workspace) ||
            !Directory.Exists(_workspace))
        {
            return "(no workspace open)";
        }

        var sb =
            new System.Text.StringBuilder();

        int hits = 0;
        const int maxHits = 100;

        System.Text.RegularExpressions.Regex? rx = null;

        try
        {
            rx = new System.Text.RegularExpressions.Regex(
                query,
                System.Text.RegularExpressions.RegexOptions
                    .IgnoreCase);
        }
        catch
        {
            rx = null; // fall back to plain substring
        }

        foreach (
            string file
            in Directory.EnumerateFiles(
                _workspace,
                "*",
                SearchOption.AllDirectories))
        {
            string rel =
                Path.GetRelativePath(
                    _workspace,
                    file);

            if (
                rel.Contains(".git" + Path.DirectorySeparatorChar) ||
                rel.Contains(".botconnector" + Path.DirectorySeparatorChar) ||
                rel.Contains("bin" + Path.DirectorySeparatorChar) ||
                rel.Contains("obj" + Path.DirectorySeparatorChar) ||
                rel.Contains("node_modules"))
            {
                continue;
            }

            FileInfo fi;

            try
            {
                fi = new FileInfo(file);
            }
            catch
            {
                continue;
            }

            if (fi.Length > 1024 * 1024)
            {
                continue; // skip files > 1 MB
            }

            string[] lines;

            try
            {
                lines = File.ReadAllLines(file);
            }
            catch
            {
                continue; // binary / unreadable
            }

            for (int n = 0; n < lines.Length; n++)
            {
                bool match =
                    rx != null
                        ? rx.IsMatch(lines[n])
                        : lines[n].IndexOf(
                            query,
                            StringComparison.OrdinalIgnoreCase) >= 0;

                if (match)
                {
                    sb.AppendLine(
                        rel +
                        ":" +
                        (n + 1) +
                        ": " +
                        lines[n].Trim());

                    hits++;

                    if (hits >= maxHits)
                    {
                        sb.AppendLine(
                            "... (truncated at " +
                            maxHits +
                            " matches)");

                        return sb.ToString();
                    }
                }
            }
        }

        return hits == 0
            ? "(no matches)"
            : sb.ToString();
    }

            private void CommandBox_PreviewKeyDown(
        object sender,
        System.Windows.Input.KeyEventArgs e)
    {
        if (
            e.Key !=
            System.Windows.Input.Key.Enter)
        {
            return;
        }

        if (
            (
                System.Windows.Input.Keyboard.Modifiers &
                System.Windows.Input.ModifierKeys.Shift
            ) ==
            System.Windows.Input.ModifierKeys.Shift)
        {
            return;
        }

        e.Handled =
            true;

        V4_Send_Click(sender, e);
    }


    private void AppendConversation(
        string role,
        string text)
    {
        if (
            string.IsNullOrWhiteSpace(
                text))
        {
            return;
        }

        // Feed the structured (visible) conversation renderer.
        V5AppendConversationCard(role, text);

        // Legacy compat surface (hidden TextBox) kept in sync below.
        string existing =
            AssistantText.Text ?? "";

        if (
            existing ==
            "BotConnector siap. Buka folder project untuk mulai.")
        {
            existing = "";
        }

        string label =
            role switch
            {
                "You" => "YOU",
                "Assistant" => "BOTCONNECTOR",
                "System" => "SYSTEM",
                "Error" => "ERROR",
                _ => role.ToUpperInvariant()
            };

        if (
            !string.IsNullOrWhiteSpace(
                existing))
        {
            existing +=
                System.Environment.NewLine +
                System.Environment.NewLine;
        }

        AssistantText.Text =
            existing +
            "--------------------------------" +
            System.Environment.NewLine +
            label +
            System.Environment.NewLine +
            System.Environment.NewLine +
            text.Trim();

        CapTextBoxTail(AssistantText, 500_000);

        AssistantText.ScrollToEnd();

        SaveChatHistory();
    }

    private void SaveChatHistory()
    {
        try
        {
            string? directory =
                System.IO.Path.GetDirectoryName(
                    _chatHistoryPath);

            if (
                !string.IsNullOrWhiteSpace(
                    directory))
            {
                System.IO.Directory.CreateDirectory(
                    directory);
            }

            System.IO.File.WriteAllText(
                _chatHistoryPath,
                AssistantText.Text ?? "",
                new System.Text.UTF8Encoding(false));
        }
        catch
        {
        }
    }


    private void LoadChatHistory()
    {
        try
        {
            if (
                !System.IO.File.Exists(
                    _chatHistoryPath))
            {
                return;
            }

            string history =
                System.IO.File.ReadAllText(
                    _chatHistoryPath);

            if (
                !string.IsNullOrWhiteSpace(
                    history))
            {
                AssistantText.Text =
                    history;

                AssistantText.ScrollToEnd();
            }
        }
        catch
        {
        }
    }


    private void SetAgentActivity(
        string activity)
    {
        P52AddActivity("STATE", activity);
        StatusText.Text =
            activity;

        if (
            !string.IsNullOrWhiteSpace(
                activity) &&
            !string.Equals(
                activity,
                "Ready",
                System.StringComparison.Ordinal))
        {
            AppendTerminal(
                "[Agent] " +
                activity);
        }
    }

    private void InsertButton_Click(
        object sender,
        RoutedEventArgs e)
    {
        var menu =
            new System.Windows.Controls.ContextMenu();

        AddAttachmentMenu(
            menu,
            "File",
            "Semua file|*.*");

        AddAttachmentMenu(
            menu,
            "Dokumen",
            "Dokumen|*.txt;*.md;*.docx;*.rtf");

        AddAttachmentMenu(
            menu,
            "PDF",
            "PDF|*.pdf");

        AddAttachmentMenu(
            menu,
            "Spreadsheet",
            "Spreadsheet|*.csv;*.xlsx");

        AddAttachmentMenu(
            menu,
            "Presentasi",
            "Presentasi|*.pptx");

        AddAttachmentMenu(
            menu,
            "Code",
            "Code|*.cs;*.ps1;*.py;*.js;*.ts;*.json;*.xml;*.xaml;*.html;*.css;*.sql;*.sh;*.yml;*.yaml");

        menu.PlacementTarget =
            InsertButton;

        menu.IsOpen =
            true;
    }


    private void AddAttachmentMenu(
        System.Windows.Controls.ContextMenu menu,
        string title,
        string filter)
    {
        var item =
            new System.Windows.Controls.MenuItem
            {
                Header = title
            };

        item.Click +=
            (_, _) =>
            {
                var dialog =
                    new Microsoft.Win32.OpenFileDialog
                    {
                        Title =
                            "Tambah " +
                            title,

                        Filter =
                            filter +
                            "|Semua file|*.*",

                        Multiselect =
                            true,

                        CheckFileExists =
                            true
                    };

                if (
                    dialog.ShowDialog(
                        this) != true)
                {
                    return;
                }

                foreach (
                    string file in
                    dialog.FileNames)
                {
                    string full =
                        System.IO.Path.GetFullPath(
                            file);

                    if (
                        !_composerAttachments.Exists(
                            p =>
                                string.Equals(
                                    p,
                                    full,
                                    System.StringComparison.OrdinalIgnoreCase)))
                    {
                        _composerAttachments.Add(
                            full);
                    }
                }

                RefreshAttachmentBar();
            };

        menu.Items.Add(
            item);
    }


    private void RefreshAttachmentBar()
    {
        if (
            _composerAttachments.Count == 0)
        {
            AttachmentText.Text =
                "";

            AttachmentBar.Visibility =
                Visibility.Collapsed;

            return;
        }

        AttachmentText.Text =
            "Attached: " +
            string.Join(
                "  -  ",
                _composerAttachments.ConvertAll(
                    p =>
                        System.IO.Path.GetFileName(
                            p)));

        AttachmentBar.Visibility =
            Visibility.Visible;
    }


    private void ClearAttachments_Click(
        object sender,
        RoutedEventArgs e)
    {
        _composerAttachments.Clear();

        RefreshAttachmentBar();
    }


    private string BuildAttachmentPrompt(
        string originalPrompt)
    {
        var result =
            new System.Text.StringBuilder();

        result.AppendLine(
            originalPrompt);

        result.AppendLine();
        result.AppendLine(
            "LOCAL ATTACHMENTS:");

        const int maxTotalChars =
            180000;

        const int maxPerFileChars =
            60000;

        int used =
            0;

        foreach (
            string file in
            _composerAttachments)
        {
            result.AppendLine();
            result.AppendLine(
                "===== " +
                System.IO.Path.GetFileName(
                    file) +
                " =====");

            try
            {
                string extracted =
                    ExtractLocalAttachment(
                        file);

                if (
                    extracted.Length >
                    maxPerFileChars)
                {
                    extracted =
                        extracted.Substring(
                            0,
                            maxPerFileChars) +
                        System.Environment.NewLine +
                        "[TRUNCATED]";
                }

                if (
                    used +
                    extracted.Length >
                    maxTotalChars)
                {
                    result.AppendLine(
                        "[Attachment context limit reached]");

                    break;
                }

                result.AppendLine(
                    extracted);

                used +=
                    extracted.Length;
            }
            catch (
                System.Exception ex)
            {
                result.AppendLine(
                    "[Tidak dapat membaca lokal: " +
                    ex.Message +
                    "]");
            }
        }

        return result.ToString();
    }


    private string ExtractLocalAttachment(
        string file)
    {
        string ext =
            System.IO.Path.GetExtension(
                file).ToLowerInvariant();

        switch (ext)
        {
            case ".txt":
            case ".md":
            case ".csv":
            case ".log":
            case ".json":
            case ".xml":
            case ".xaml":
            case ".cs":
            case ".ps1":
            case ".py":
            case ".js":
            case ".ts":
            case ".html":
            case ".css":
            case ".sql":
            case ".sh":
            case ".yml":
            case ".yaml":
            case ".ini":
            case ".toml":
            case ".rtf":
                return
                    System.IO.File.ReadAllText(
                        file);

            case ".docx":
                return
                    ExtractDocx(
                        file);

            case ".xlsx":
                return
                    ExtractXlsx(
                        file);

            case ".pptx":
                return
                    ExtractPptx(
                        file);

            case ".pdf":
                return
                    ExtractPdfLocal(
                        file);

            default:
                throw new System.InvalidOperationException(
                    "format belum didukung: " +
                    ext);
        }
    }


    private string ExtractDocx(
        string file)
    {
        using var archive =
            System.IO.Compression.ZipFile.OpenRead(
                file);

        var entry =
            archive.GetEntry(
                "word/document.xml");

        if (entry == null)
        {
            throw new System.InvalidOperationException(
                "word/document.xml tidak ada");
        }

        using var stream =
            entry.Open();

        var doc =
            System.Xml.Linq.XDocument.Load(
                stream);

        System.Xml.Linq.XNamespace w =
            "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

        var sb =
            new System.Text.StringBuilder();

        foreach (
            var paragraph in
            doc.Descendants(
                w + "p"))
        {
            foreach (
                var text in
                paragraph.Descendants(
                    w + "t"))
            {
                sb.Append(
                    text.Value);
            }

            sb.AppendLine();
        }

        return sb.ToString();
    }


    private string ExtractXlsx(
        string file)
    {
        using var archive =
            System.IO.Compression.ZipFile.OpenRead(
                file);

        var shared =
            new System.Collections.Generic.List<string>();

        var sharedEntry =
            archive.GetEntry(
                "xl/sharedStrings.xml");

        if (sharedEntry != null)
        {
            using var stream =
                sharedEntry.Open();

            var document =
                System.Xml.Linq.XDocument.Load(
                    stream);

            foreach (
                var item in
                document.Descendants())
            {
                if (
                    item.Name.LocalName ==
                    "si")
                {
                    var text =
                        new System.Text.StringBuilder();

                    foreach (
                        var node in
                        item.Descendants())
                    {
                        if (
                            node.Name.LocalName ==
                            "t")
                        {
                            text.Append(
                                node.Value);
                        }
                    }

                    shared.Add(
                        text.ToString());
                }
            }
        }

        var sb =
            new System.Text.StringBuilder();

        foreach (
            var entry in
            archive.Entries)
        {
            if (
                !entry.FullName.StartsWith(
                    "xl/worksheets/sheet",
                    System.StringComparison.OrdinalIgnoreCase) ||
                !entry.FullName.EndsWith(
                    ".xml",
                    System.StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            sb.AppendLine();
            sb.AppendLine(
                "[" +
                entry.Name +
                "]");

            using var stream =
                entry.Open();

            var document =
                System.Xml.Linq.XDocument.Load(
                    stream);

            foreach (
                var row in
                document.Descendants())
            {
                if (
                    row.Name.LocalName !=
                    "row")
                {
                    continue;
                }

                bool first =
                    true;

                foreach (
                    var cell in
                    row.Elements())
                {
                    if (
                        cell.Name.LocalName !=
                        "c")
                    {
                        continue;
                    }

                    if (!first)
                    {
                        sb.Append('\t');
                    }

                    first =
                        false;

                    string type =
                        cell.Attribute(
                            "t")?.Value ?? "";

                    string value =
                        "";

                    foreach (
                        var child in
                        cell.Elements())
                    {
                        if (
                            child.Name.LocalName ==
                            "v")
                        {
                            value =
                                child.Value;

                            break;
                        }
                    }

                    if (
                        type == "s" &&
                        int.TryParse(
                            value,
                            out int index) &&
                        index >= 0 &&
                        index < shared.Count)
                    {
                        value =
                            shared[index];
                    }

                    sb.Append(
                        value);
                }

                sb.AppendLine();
            }
        }

        return sb.ToString();
    }


    private string ExtractPptx(
        string file)
    {
        using var archive =
            System.IO.Compression.ZipFile.OpenRead(
                file);

        var entries =
            new System.Collections.Generic.List<System.IO.Compression.ZipArchiveEntry>();

        foreach (
            var entry in
            archive.Entries)
        {
            if (
                entry.FullName.StartsWith(
                    "ppt/slides/slide",
                    System.StringComparison.OrdinalIgnoreCase) &&
                entry.FullName.EndsWith(
                    ".xml",
                    System.StringComparison.OrdinalIgnoreCase))
            {
                entries.Add(
                    entry);
            }
        }

        entries.Sort(
            (a,b) =>
                string.Compare(
                    a.FullName,
                    b.FullName,
                    System.StringComparison.OrdinalIgnoreCase));

        var sb =
            new System.Text.StringBuilder();

        foreach (
            var entry in
            entries)
        {
            sb.AppendLine();
            sb.AppendLine(
                "[" +
                entry.Name +
                "]");

            using var stream =
                entry.Open();

            var document =
                System.Xml.Linq.XDocument.Load(
                    stream);

            foreach (
                var node in
                document.Descendants())
            {
                if (
                    node.Name.LocalName ==
                    "t")
                {
                    sb.AppendLine(
                        node.Value);
                }
            }
        }

        return sb.ToString();
    }


    private string ExtractPdfLocal(
        string file)
    {
        string? tool =
            FindExecutable(
                "pdftotext.exe");

        if (
            string.IsNullOrWhiteSpace(
                tool))
        {
            return
                "[PDF terpasang sebagai attachment lokal. " +
                "pdftotext.exe belum tersedia di laptop, " +
                "jadi teks PDF belum diekstrak.]";
        }

        string temp =
            System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                "botconnector-pdf-" +
                System.Guid.NewGuid().ToString("N") +
                ".txt");

        try
        {
            var psi =
                new System.Diagnostics.ProcessStartInfo
                {
                    FileName =
                        tool,

                    Arguments =
                        "\"" +
                        file +
                        "\" \"" +
                        temp +
                        "\"",

                    UseShellExecute =
                        false,

                    CreateNoWindow =
                        true
                };

            using var process =
                System.Diagnostics.Process.Start(
                    psi);

            if (process == null)
            {
                throw new System.InvalidOperationException(
                    "pdftotext gagal start");
            }

            process.WaitForExit(
                30000);

            if (
                process.ExitCode != 0 ||
                !System.IO.File.Exists(
                    temp))
            {
                throw new System.InvalidOperationException(
                    "pdftotext gagal");
            }

            return
                System.IO.File.ReadAllText(
                    temp);
        }
        finally
        {
            try
            {
                if (
                    System.IO.File.Exists(
                        temp))
                {
                    System.IO.File.Delete(
                        temp);
                }
            }
            catch
            {
            }
        }
    }


    private string? FindExecutable(
        string name)
    {
        string? path =
            System.Environment.GetEnvironmentVariable(
                "PATH");

        if (
            string.IsNullOrWhiteSpace(
                path))
        {
            return null;
        }

        foreach (
            string folder in
            path.Split(
                System.IO.Path.PathSeparator))
        {
            try
            {
                string candidate =
                    System.IO.Path.Combine(
                        folder.Trim(),
                        name);

                if (
                    System.IO.File.Exists(
                        candidate))
                {
                    return candidate;
                }
            }
            catch
            {
            }
        }

        return null;
    }
}



















