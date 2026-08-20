using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

using BotConnector.Desktop.V4.Providers;
using BotConnector.Desktop.V4.Tools;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private readonly HermesOpenAiClient
        _v4Hermes = new();

    private readonly List<HermesMessage>
        _v4HermesMessages = new();

    private bool
        _v4CommandCenterInitialized;

    // Truthful Hermes connection state (never derived from config alone).
    private bool _v4HermesReachable;
    private bool _v4HermesProbing;
    private DateTime _v4LastHermesProbeUtc = DateTime.MinValue;

    // Cloud Coding transcript and workspace state
    private readonly List<string>
        _v4CloudCodingTranscript = new();

    private string?
        _v4CloudCodingWorkspace;

    private async void
        V4InitializeCommandCenter()
    {
        if (_v4CommandCenterInitialized)
            return;

        _v4CommandCenterInitialized = true;

        Title = "BotConnector - AI Agent Command Center";

        ModeBox.Items.Clear();

        ModeBox.Items.Add(
            new ComboBoxItem
            {
                Content = "Auto",
                Tag = "auto"
            });

        ModeBox.Items.Add(
            new ComboBoxItem
            {
                Content = "Hermes",
                Tag = "hermes"
            });

        ModeBox.Items.Add(
            new ComboBoxItem
            {
                Content = "Local AI",
                Tag = "local"
            });

        ModeBox.Items.Add(
            new ComboBoxItem
            {
                Content = "Coding",
                Tag = "coding"
            });

        ModeBox.SelectedIndex = 0;

        if (!string.IsNullOrWhiteSpace(_workspace))
        {
            try
            {
                V4SetWorkspace(_workspace);
            }
            catch
            {
            }
        }

        // Truthful startup health: probe async, no false "connected".
        await V4RefreshHermesStatusAsync(force: true);

        AssistantText.ScrollToEnd();
        TerminalText.ScrollToEnd();
    }

    // Fast, event-driven Hermes health. No always-on poller; called at init,
    // on mode change, and immediately before each Hermes send. Debounced so
    // rapid triggers don't cause probe storms.
    private async Task<bool> V4RefreshHermesStatusAsync(
        bool force = false)
    {
        if (!force &&
            (DateTime.UtcNow - _v4LastHermesProbeUtc)
                < TimeSpan.FromSeconds(5))
        {
            return _v4HermesReachable;
        }

        if (_v4HermesProbing)
            return _v4HermesReachable;

        _v4HermesProbing = true;

        try
        {
            V2ActivityText.Text = "Checking Hermes...";
            V4SetHermesDot("#94A3B8");
            HermesStateText.Text = "Checking Hermes...";

            bool listenerUp =
                await V4HermesListenerUpAsync();

            if (!listenerUp)
            {
                // Auto-heal: start the local Hermes SSH bridge if it is down.
                await V5EnsureHermesBridgeAsync();
                listenerUp = await V4HermesListenerUpAsync();
            }

            bool reachable = false;

            if (listenerUp)
            {
                try
                {
                    using var cts =
                        new CancellationTokenSource(
                            TimeSpan.FromSeconds(2));

                    reachable =
                        await _v4Hermes.ProbeAsync(cts.Token);
                }
                catch
                {
                }
            }

            _v4HermesReachable = reachable;
            _v4LastHermesProbeUtc = DateTime.UtcNow;

            if (reachable)
            {
                V2ActivityText.Text = "Hermes reachable";
                StatusText.Text =
                    $"Auto -> Hermes - {_v4Hermes.BaseUrl}";
                V4SetHermesDot("#22C55E");
                HermesStateText.Text = "Hermes reachable";
                HermesStateSub.Text = _v4Hermes.BaseUrl;
            }
            else if (!listenerUp)
            {
                V2ActivityText.Text = "Hermes unavailable";
                StatusText.Text =
                    "Hermes unavailable: local bridge " +
                    V4HermesEndpointLabel() +
                    " is not listening.";
                V4SetHermesDot("#EF4444");
                HermesStateText.Text = "Hermes unavailable";
                HermesStateSub.Text =
                    "bridge " + V4HermesEndpointLabel() + " not listening";
            }
            else
            {
                V2ActivityText.Text = "Hermes degraded";
                StatusText.Text =
                    "Hermes bridge reachable but not responding at " +
                    _v4Hermes.BaseUrl;
                V4SetHermesDot("#F59E0B");
                HermesStateText.Text = "Hermes degraded";
                HermesStateSub.Text = _v4Hermes.BaseUrl;
            }

            return reachable;
        }
        finally
        {
            _v4HermesProbing = false;
        }
    }

    private void V4SetHermesDot(string hex)
    {
        try
        {
            HermesStateDot.Fill =
                new System.Windows.Media.SolidColorBrush(
                    (System.Windows.Media.Color)
                        System.Windows.Media.ColorConverter
                            .ConvertFromString(hex));
        }
        catch
        {
        }
    }

    private async Task<bool> V4HermesListenerUpAsync()
    {
        try
        {
            var uri = new Uri(_v4Hermes.BaseUrl);

            using var client = new TcpClient();

            var connect =
                client.ConnectAsync(uri.Host, uri.Port);

            var finished =
                await Task.WhenAny(
                    connect,
                    Task.Delay(800));

            return finished == connect &&
                   client.Connected;
        }
        catch
        {
            return false;
        }
    }

    private string V4HermesEndpointLabel()
    {
        try
        {
            var u = new Uri(_v4Hermes.BaseUrl);
            return u.Host + ":" + u.Port;
        }
        catch
        {
            return "127.0.0.1:18642";
        }
    }

    private string V4FriendlyHermesError(Exception ex)
    {
        string msg = ex.Message ?? "";

        bool connectionRefused =
            ex is SocketException ||
            ex is System.Net.Http.HttpRequestException ||
            msg.IndexOf("refused", StringComparison.OrdinalIgnoreCase) >= 0 ||
            msg.IndexOf("target machine", StringComparison.OrdinalIgnoreCase) >= 0 ||
            msg.IndexOf("No connection", StringComparison.OrdinalIgnoreCase) >= 0;

        if (connectionRefused)
        {
            return
                "Hermes unavailable: the local BotConnector bridge at " +
                V4HermesEndpointLabel() +
                " is not listening. Start the bridge and press Send again.\n\n" +
                "Details: " + msg;
        }

        return "Hermes error: " + msg;
    }

    private void
        V4_ModeChanged(
            object sender,
            SelectionChangedEventArgs e)
    {
        if (!_v4CommandCenterInitialized)
            return;

        string mode =
            V4SelectedMode();

        if (mode == "local")
        {
            LocalAiCheck.IsChecked =
                true;

            // Local AI is legacy/local-compat only (no cloud dependency).
            StatusText.Text =
                "Local AI · legacy local provider";

            return;
        }

        if (mode == "coding")
        {
            LocalAiCheck.IsChecked = false;
            StatusText.Text = "Coding · Cloud Orchestrator";
            return;
        }

        LocalAiCheck.IsChecked =
            false;

        // Never claim a connection from config alone — verify it.
        _ = V4RefreshHermesStatusAsync(force: true);
    }

    private string
        V4SelectedMode()
    {
        if (
            ModeBox.SelectedItem
            is ComboBoxItem item
            &&
            item.Tag is string mode)
        {
            return mode;
        }

        return "auto";
    }

    private async void
        V4_Send_Click(
            object sender,
            RoutedEventArgs e)
    {
        // V6 OpenCode Direct: when enabled, sends go straight to the native
        // OpenCode server (never through Hermes, Cloud Adapter, the old AI
        // Orchestrator, or the ModelRouter). When disabled, old behavior is
        // preserved exactly below.
        if (V6OpenCodeDirectEnabled())
        {
            await V6OpenCodeDirectSendAsync();
            return;
        }

        string mode =
            V4SelectedMode();

        // Preserve proven V2/V3 path for Auto and Local.
        if (mode == "local")
        {
            V2_Send_Click(
                sender,
                e);

            return;
        }

        if (mode == "coding")
        {
            await V4SendCloudCodingAsync();
            return;
        }

        await V4SendHermesAsync();
    }

    private async Task V4SendCloudCodingAsync()
    {
        string userPrompt = CommandBox.Text.Trim();

        if (string.IsNullOrWhiteSpace(userPrompt))
            return;

        if (_agentCancellation is not null)
            return;

        if (string.IsNullOrWhiteSpace(_workspace))
        {
            AppendConversation(
                "System",
                "Select a Windows workspace before using Coding mode.");
            SetAgentActivity("");
            return;
        }

        string normalizedWorkspace;
        try
        {
            normalizedWorkspace = Path.GetFullPath(_workspace);
            V4SetWorkspace(normalizedWorkspace);
        }
        catch
        {
            AppendConversation(
                "Error",
                "Unable to activate the selected Windows workspace.");
            return;
        }

        if (!string.IsNullOrWhiteSpace(_v4CloudCodingWorkspace) &&
            string.Equals(normalizedWorkspace, _v4CloudCodingWorkspace, StringComparison.OrdinalIgnoreCase))
        {
        }
        else
        {
            _v4CloudCodingTranscript.Clear();
            _v4CloudCodingWorkspace = normalizedWorkspace;
        }

        _agentCancellation = new CancellationTokenSource();

        SendButton.IsEnabled = false;
        StopButton.IsEnabled = true;
        CommandBox.IsEnabled = false;
        CommandBox.Clear();

        int transcriptStart = _v4CloudCodingTranscript.Count;

        try
        {
            AppendConversation("You", userPrompt);

            _v4CloudCodingTranscript.Add("USER: " + userPrompt);

            var brain = V4.CreateCloudCodingBrain();

            SetAgentActivity("Cloud coding...");

            string answer = await V4.Agent.RunAsync(
                brain,
                _v4CloudCodingTranscript,
                _agentCancellation.Token);

            for (int i = transcriptStart; i < _v4CloudCodingTranscript.Count; i++)
            {
                if (_v4CloudCodingTranscript[i].StartsWith("TOOL_RESULT ", StringComparison.Ordinal))
                {
                    _v4CloudCodingTranscript.RemoveAt(i);
                    i--;
                }
            }

            _v4CloudCodingTranscript.Add("ASSISTANT: " + answer);

            AppendConversation("BotConnector", answer);
            SetAgentActivity("");
            SaveChatHistory();
        }
        catch (OperationCanceledException)
        {
            while (_v4CloudCodingTranscript.Count > transcriptStart)
            {
                _v4CloudCodingTranscript.RemoveAt(transcriptStart);
            }

            AppendConversation("System", "Request stopped.");
        }
        catch (Exception ex)
        {
            while (_v4CloudCodingTranscript.Count > transcriptStart)
            {
                _v4CloudCodingTranscript.RemoveAt(transcriptStart);
            }

            AppendConversation("Error", ex.Message);
            StatusText.Text = "Coding error";
        }
        finally
        {
            _agentCancellation?.Dispose();
            _agentCancellation = null;

            SendButton.IsEnabled = true;
            StopButton.IsEnabled = false;
            CommandBox.IsEnabled = true;
            CommandBox.Focus();

            SetAgentActivity("");
            SaveChatHistory();
        }
    }

    private async Task
        V4SendHermesAsync()
    {
        string userPrompt =
            CommandBox.Text.Trim();

        if (string.IsNullOrWhiteSpace(userPrompt))
            return;

        if (_agentCancellation is not null)
            return;

        if (!string.IsNullOrWhiteSpace(_workspace))
        {
            try
            {
                V4SetWorkspace(_workspace);
            }
            catch
            {
            }
        }

        _agentCancellation =
            new CancellationTokenSource();

        SendButton.IsEnabled =
            false;

        StopButton.IsEnabled =
            true;

        CommandBox.IsEnabled =
            false;

        CommandBox.Clear();

        try
        {
            AppendConversation(
                "You",
                userPrompt);

            // Immediate truthful check; fail fast with an actionable message
            // instead of letting the request surface a raw connection error.
            bool hermesUp =
                await V4RefreshHermesStatusAsync(force: true);

            if (!hermesUp)
            {
                AppendConversation(
                    "System",
                    "Hermes is unavailable because the local BotConnector bridge at " +
                    V4HermesEndpointLabel() +
                    " is not listening. Start the bridge, then press Send again.");

                SetAgentActivity("");
                return;
            }

            SetAgentActivity(
                "Hermes reasoning...");

            string enriched =
                BuildAgentPrompt(
                    V3AugmentUserPrompt(
                        V5AgentModeDirective() + userPrompt));

            V41EnsureSessionForCurrentWorkspace();
            V4EnsureHermesBrainContract();


            _v4HermesMessages.Add(
                new HermesMessage(
                    "user",
                    enriched));

            // Max local-hands rounds.
            for (int round = 0; round < 4; round++)
            {
                string answer =
                    await V41SendHermesStreamingAsync(
                        _v4HermesMessages,
                        _agentCancellation.Token);

                if (
                    (
                        V4LooksLikeRemoteExecutionLeak(answer)
                        ||
                        V41RemoteToolViolation()
                    )
                    &&
                    V4ExtractActions(answer) is null)
                {
                    AppendTerminal(
                        "[V4.1.1 Policy] Remote Hermes execution blocked for this Desktop turn.");

                    AppendConversation(
                        "System",
                        "Hermes attempted remote execution. " +
                        "This Desktop session requires Windows local hands. " +
                        "No VPS-only tool result was accepted.");

                    SetAgentActivity(
                        "Remote execution blocked");

                    V41PersistSession();

                    return;
                }

                _v4HermesMessages.Add(
                    new HermesMessage(
                        "assistant",
                        answer));

                string? actions =
                    V4ExtractActions(answer);

                if (actions is null)
                {
                    AppendConversation(
                        "BotConnector",
                        V4RemoveActions(answer));

                    V41PersistSession();

            SetAgentActivity("");
            SaveChatHistory();
                    return;
                }

                string visible =
                    V4RemoveActions(answer);

                if (!string.IsNullOrWhiteSpace(visible))
                {
                    AppendConversation(
                        "BotConnector",
                        visible);
                }

                SetAgentActivity("Executing reviewed local tools...");

                string toolResult =
                    await V4ExecuteActionsAsync(
                        actions,
                        _agentCancellation.Token);

                _v4HermesMessages.Add(
                    new HermesMessage(
                        "user",
                        "LOCAL TOOL RESULTS:\n" +
                        toolResult +
                        "\nContinue the task. " +
                        "If more local operations are needed, " +
                        "return another <botconnector_actions> block."));
            }

            AppendConversation(
                "System",
                "Hermes local-tool loop reached the 4-round safety guard.");
        }
        catch (OperationCanceledException)
        {
            AppendConversation(
                "System",
                "Request stopped.");
        }
        catch (Exception ex)
        {
            AppendConversation(
                "Error",
                V4FriendlyHermesError(ex));

            StatusText.Text =
                "Hermes error";

            // Refresh truthful state so the header reflects reality.
            _ = V4RefreshHermesStatusAsync(force: true);
        }
        finally
        {
            _agentCancellation?.Dispose();
            _agentCancellation = null;

            SendButton.IsEnabled =
                true;

            StopButton.IsEnabled =
                false;

            CommandBox.IsEnabled =
                true;

            CommandBox.Focus();

            V41PersistSession();

            SetAgentActivity("");
            SaveChatHistory();
        }
    }

    private static string?
        V4ExtractActions(
            string text)
    {
        const string start =
            "<botconnector_actions>";

        const string end =
            "</botconnector_actions>";

        int a =
            text.IndexOf(
                start,
                StringComparison.OrdinalIgnoreCase);

        if (a < 0)
            return null;

        int b =
            text.IndexOf(
                end,
                a + start.Length,
                StringComparison.OrdinalIgnoreCase);

        if (b < 0)
            return null;

        return text.Substring(
            a + start.Length,
            b - (a + start.Length))
            .Trim();
    }

    private static string
        V4RemoveActions(
            string text)
    {
        const string start =
            "<botconnector_actions>";

        const string end =
            "</botconnector_actions>";

        int a =
            text.IndexOf(
                start,
                StringComparison.OrdinalIgnoreCase);

        if (a < 0)
            return text.Trim();

        int b =
            text.IndexOf(
                end,
                a + start.Length,
                StringComparison.OrdinalIgnoreCase);

        if (b < 0)
            return text.Substring(
                0,
                a).Trim();

        return (
            text.Substring(0, a) +
            text.Substring(
                b + end.Length)
        ).Trim();
    }

    private string
        V4ResolvePath(
            string path)
    {
        if (Path.IsPathRooted(path))
            return Path.GetFullPath(path);

        if (!string.IsNullOrWhiteSpace(_workspace))
        {
            return Path.GetFullPath(
                Path.Combine(
                    _workspace,
                    path));
        }

        return Path.GetFullPath(path);
    }

    private async Task<string>
        V4ExecuteActionsAsync(
            string json,
            CancellationToken cancellationToken)
    {
        using var doc =
            JsonDocument.Parse(json);

        if (
            !doc.RootElement.TryGetProperty(
                "actions",
                out var actions)
            ||
            actions.ValueKind !=
                JsonValueKind.Array)
        {
            return "Invalid actions payload.";
        }

        var results =
            new List<string>();

        foreach (var action in
                 actions.EnumerateArray())
        {
            cancellationToken
                .ThrowIfCancellationRequested();

            string type =
                action.TryGetProperty(
                    "type",
                    out var t)
                ? t.GetString() ?? ""
                : "";

            try
            {
                ToolResult result;

                if (
                    type == "read_file" ||
                    type == "workspace_read")
                {
                    string path =
                        action.GetProperty(
                            "path").GetString()
                        ?? "";

                    result =
                        await V4.Tools.ExecuteAsync(
                            new ToolRequest(
                                "workspace_read",
                                new Dictionary<string,string>
                                {
                                    ["path"] =
                                        V4ResolvePath(path)
                                }),
                            cancellationToken);
                }
                else if (
                    type == "write_file" ||
                    type == "workspace_write")
                {
                    string path =
                        action.GetProperty(
                            "path").GetString()
                        ?? "";

                    string content =
                        action.TryGetProperty(
                            "content",
                            out var c)
                        ? c.GetString() ?? ""
                        : "";

                    result =
                        await V4.Tools.ExecuteAsync(
                            new ToolRequest(
                                "workspace_write",
                                new Dictionary<string,string>
                                {
                                    ["path"] =
                                        V4ResolvePath(path),

                                    ["content"] =
                                        content
                                }),
                            cancellationToken);
                }
                else if (type == "edit_file")
                {
                    string path =
                        V4ResolvePath(
                            action.GetProperty(
                                "path").GetString()
                            ?? "");

                    string find =
                        action.TryGetProperty(
                            "find",
                            out var f)
                        ? f.GetString() ?? ""
                        : "";

                    string replace =
                        action.TryGetProperty(
                            "replace",
                            out var r)
                        ? r.GetString() ?? ""
                        : "";

                    var read =
                        await V4.Tools.ExecuteAsync(
                            new ToolRequest(
                                "workspace_read",
                                new Dictionary<string,string>
                                {
                                    ["path"] = path
                                }),
                            cancellationToken);

                    if (!read.Success)
                    {
                        result = read;
                    }
                    else if (
                        string.IsNullOrEmpty(find) ||
                        !read.Output.Contains(
                            find,
                            StringComparison.Ordinal))
                    {
                        result =
                            new ToolResult(
                                false,
                                "",
                                "edit_file find snippet not found or empty");
                    }
                    else
                    {
                        string changed =
                            read.Output.Replace(
                                find,
                                replace,
                                StringComparison.Ordinal);

                        result =
                            await V4.Tools.ExecuteAsync(
                                new ToolRequest(
                                    "workspace_write",
                                    new Dictionary<string,string>
                                    {
                                        ["path"] = path,
                                        ["content"] = changed
                                    }),
                                cancellationToken);
                    }
                }
                else if (
                    type == "run" ||
                    type == "shell" ||
                    type == "local_shell")
                {
                    string command =
                        action.TryGetProperty(
                            "command",
                            out var c)
                        ? c.GetString() ?? ""
                        : "";

                    result =
                        await V4.Tools.ExecuteAsync(
                            new ToolRequest(
                                "local_shell",
                                new Dictionary<string,string>
                                {
                                    ["command"] =
                                        command,

                                    ["cwd"] =
                                        string.IsNullOrWhiteSpace(_workspace)
                                            ? Environment.CurrentDirectory
                                            : _workspace
                                }),
                            cancellationToken);
                }
                else if (
                    type == "ssh" ||
                    type == "ssh_command")
                {
                    string destination =
                        action.TryGetProperty(
                            "destination",
                            out var d)
                        ? d.GetString() ?? ""
                        : "";

                    string command =
                        action.TryGetProperty(
                            "command",
                            out var c)
                        ? c.GetString() ?? ""
                        : "";

                    result =
                        await V4.Tools.ExecuteAsync(
                            new ToolRequest(
                                "ssh_command",
                                new Dictionary<string,string>
                                {
                                    ["destination"] =
                                        destination,

                                    ["command"] =
                                        command
                                }),
                            cancellationToken);
                }
                else
                {
                    result =
                        new ToolResult(
                            false,
                            "",
                            "Unknown V4 action: " + type);
                }

                results.Add(
                    $"[{type}] success={result.Success}\n" +
                    result.Output +
                    (
                        string.IsNullOrWhiteSpace(result.Error)
                        ? ""
                        : "\nERROR=" + result.Error
                    ));

                AppendTerminal(
                    $"[V4 {type}]\n" +
                    (
                        result.Success
                        ? result.Output
                        : result.Error ?? "failed"
                    ));
            }
            catch (Exception ex)
            {
                results.Add(
                    $"[{type}] ERROR={ex.Message}");
            }
        }

        RefreshFileTree();

        return string.Join(
            "\n\n",
            results);
    }
}