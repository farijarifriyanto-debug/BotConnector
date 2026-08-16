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

                RefreshFileTree();

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



















