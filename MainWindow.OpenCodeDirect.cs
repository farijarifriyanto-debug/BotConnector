using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;

namespace BotConnector.Desktop;

// V6 OpenCode Direct route (candidate, no production cutover).
//
// Direct path: BotConnector Desktop -> OpenCode Server (opencode serve) ->
// configured model/provider. This route deliberately does NOT touch Hermes,
// the Cloud Adapter, the old AI Orchestrator, the ModelRouter, LiteLLM or any
// other provider router. When OpenCodeDirectEnabled is off, old behavior is
// preserved exactly (the hooks below early-return only when enabled).
//
// Native OpenCode endpoints used:
//   POST /session                        create session
//   POST /session/{id}/message           send a prompt, wait for the turn
//   GET  /event                          SSE event stream (server-sent events)
//   GET  /session/{id}/message           read final messages
//   GET  /session/{id}/diff              read session file diff
//   POST /session/{id}/abort             stop a running session (Stop button)
//   POST /session/{id}/permissions/{permissionID}  native permission replies
public partial class MainWindow
{
    // ---- Configuration (env vars with candidate defaults). ----------------
    // OpenCodeDirectEnabled=false  preserves old routing exactly.

    private const string OpenCodeDirectEnabledEnv =
        "BOTCONNECTOR_OPENCODE_DIRECT_ENABLED";

    private const string OpenCodeBaseUrlEnv =
        "BOTCONNECTOR_OPENCODE_BASE_URL";

    private const string OpenCodeProviderIDEnv =
        "BOTCONNECTOR_OPENCODE_PROVIDER_ID";

    private const string OpenCodeModelIDEnv =
        "BOTCONNECTOR_OPENCODE_MODEL_ID";

    // Optional: ask (default) | allow | always | deny.
    private const string OpenCodePermissionModeEnv =
        "BOTCONNECTOR_OPENCODE_PERMISSION";

    private const string OpenCodeBaseUrlDefault =
        "http://127.0.0.1:18411";

    private const string OpenCodeProviderIDDefault =
        "deepseek";

    private const string OpenCodeModelIDDefault =
        "deepseek-v4-flash";

    private static string? V6Env(string name)
    {
        try
        {
            return Environment.GetEnvironmentVariable(name);
        }
        catch
        {
            return null;
        }
    }

    private static bool V6OpenCodeDirectEnabled()
    {
        string? value = V6Env(OpenCodeDirectEnabledEnv);
        return string.Equals(value, "1", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(value, "true", StringComparison.OrdinalIgnoreCase) ||
               string.Equals(value, "yes", StringComparison.OrdinalIgnoreCase);
    }

    private static string V6OpenCodeBaseUrl()
    {
        string? value = V6Env(OpenCodeBaseUrlEnv);
        return string.IsNullOrWhiteSpace(value)
            ? OpenCodeBaseUrlDefault
            : value.Trim().TrimEnd('/');
    }

    private static string V6OpenCodeProviderID()
    {
        string? value = V6Env(OpenCodeProviderIDEnv);
        return string.IsNullOrWhiteSpace(value)
            ? OpenCodeProviderIDDefault
            : value.Trim();
    }

    private static string V6OpenCodeModelID()
    {
        string? value = V6Env(OpenCodeModelIDEnv);
        return string.IsNullOrWhiteSpace(value)
            ? OpenCodeModelIDDefault
            : value.Trim();
    }

    private static string V6OpenCodePermissionMode()
    {
        string? value = V6Env(OpenCodePermissionModeEnv);
        string normalized = (value ?? "ask").Trim().ToLowerInvariant();
        return normalized switch
        {
            "allow" => "allow",
            "always" => "always",
            "deny" or "reject" => "deny",
            _ => "ask"
        };
    }

    // ---- Client state. ----------------------------------------------------
    // App-lifetime client (like the other HttpClients in this project); the
    // blocking message call needs an effectively unlimited timeout and relies
    // on cancellation tokens for Stop.
    private readonly HttpClient _v6OpenCodeHttp =
        new HttpClient
        {
            Timeout = System.Threading.Timeout.InfiniteTimeSpan
        };

    private readonly object _v6OpenCodeLock = new object();
    private bool _v6OpenCodeBusy;
    private string? _v6OpenCodeSessionId;
    private string? _currentProviderId;
    private static readonly ProviderHealthCache HealthCache = new ProviderHealthCache();
    private readonly HashSet<string> _v6OpenCodeRepliedPermissions = new();
    private readonly StringBuilder _v6OpenCodeLiveText = new();

private readonly TaskCompletionSource<bool> _readinessTcs = new(TaskCreationOptions.RunContinuationsAsynchronously);

    private void V6OpenCodeSetActivity(string activity)
    {
        V6Ui(() =>
        {
            try
            {
                SetAgentActivity(activity);
            }
            catch
            {
            }
        });
    }

    private void V6OpenCodeLog(string line)
    {
        V6Ui(() =>
        {
            try
            {
                AppendTerminal(line);
            }
            catch
            {
            }
        });
    }

    // Marshal work to the WPF UI thread; never block the UI thread here.
    private void V6Ui(Action action)
    {
        if (action is null)
            return;

        if (Dispatcher.CheckAccess())
        {
            action();
            return;
        }

        try
        {
            Dispatcher.BeginInvoke(action);
        }
        catch
        {
        }
    }

    private string V6OpenCodeDirectory()
    {
        if (string.IsNullOrWhiteSpace(_workspace))
            return "";
        return Path.GetFullPath(_workspace);
    }

    private static string V6OpenCodeUri(string baseUrl, string path, string? directory)
    {
        string url = baseUrl + path;
        if (!string.IsNullOrWhiteSpace(directory))
        {
            url += (path.Contains('?') ? "&" : "?") +
                   "directory=" +
                   Uri.EscapeDataString(directory);
        }
        return url;
    }

    // -----------------------------------------------------------------------
    // Entry point: BotConnector -> OpenCode server -> model/provider.
    // Runs entirely asynchronously; the WPF UI thread is never blocked.
    // -----------------------------------------------------------------------
    private async Task V6OpenCodeDirectSendAsync()
    {
        if (_v6OpenCodeBusy)
            return;

        string prompt = CommandBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(prompt))
            return;

        string directory = V6OpenCodeDirectory();
        if (string.IsNullOrWhiteSpace(directory) ||
            !Directory.Exists(directory))
        {
            V6Ui(() =>
                AppendConversation(
                    "System",
                    "Select an existing workspace folder before sending an OpenCode Direct request."));
            return;
        }

        _v6OpenCodeBusy = true;

        using var cts = new CancellationTokenSource();
        _agentCancellation = cts;

        var sseCts = CancellationTokenSource.CreateLinkedTokenSource(cts.Token);
        Task? sseTask = null;
        string? sessionId = null;

        try
        {
            V6Ui(() =>
            {
                SendButton.IsEnabled = false;
                StopButton.IsEnabled = true;
                CommandBox.IsEnabled = false;
                CommandBox.Clear();
                AppendConversation("You", prompt);
            });

            V6OpenCodeSetActivity("OpenCode direct...");

            string baseUrl = V6OpenCodeBaseUrl();
            string providerId = V6OpenCodeProviderID();
            string modelId = V6OpenCodeModelID();

            // 1) Create a native session.
            sessionId = await V6OpenCodeCreateSessionAsync(
                baseUrl,
                directory,
                cts.Token);

            lock (_v6OpenCodeLock)
            {
                _v6OpenCodeSessionId = sessionId;
            }

            // 2) Consume the SSE event stream, filtered to this session.
            sseTask = V6OpenCodeSseLoopAsync(
                baseUrl,
                directory,
                sessionId,
                sseCts.Token);

            // 3) Send the prompt; this call waits for the agent turn to finish.
            V6OpenCodeSetActivity("OpenCode working...");

            string responseBody =
                await V6OpenCodeSendMessageAsync(
                    baseUrl,
                    directory,
                    sessionId,
                    providerId,
                    modelId,
                    prompt,
                    cts.Token);

            // 4) Final assistant answer from the response parts.
            string answer =
                V6OpenCodeExtractAnswer(responseBody);

            V6OpenCodeSetActivity("OpenCode completed");

            // 5) Diff summary for the session.
            string diffSummary =
                await V6OpenCodeFetchDiffAsync(
                    baseUrl,
                    directory,
                    sessionId,
                    cts.Token);

            // 6) Message history for the session (native endpoint).
            string history =
                await V6OpenCodeFetchMessagesAsync(
                    baseUrl,
                    directory,
                    sessionId,
                    cts.Token);

            V6Ui(() =>
            {
                if (!string.IsNullOrWhiteSpace(answer))
                {
                    AppendConversation("Assistant", answer);
                }

                if (!string.IsNullOrWhiteSpace(diffSummary))
                {
                    AppendTerminal("[OpenCode diff]\n" + diffSummary);
                }

                if (!string.IsNullOrWhiteSpace(history))
                {
                    AppendTerminal("[OpenCode session history]\n" + history);
                }

                StatusText.Text = "Ready";
                RefreshFileTree();
                SaveChatHistory();
            });
        }
        catch (OperationCanceledException)
        {
            V6Ui(() =>
            {
                AppendConversation("System", "Request stopped.");
                StatusText.Text = "Stopped";
            });
        }
        catch (Exception ex)
        {
            V6Ui(() =>
            {
                AppendConversation("Error", V6OpenCodeFriendlyError(ex));
                StatusText.Text = "OpenCode direct error";
            });
        }
        finally
        {
            lock (_v6OpenCodeLock)
            {
                _v6OpenCodeSessionId = null;
            }

            try
            {
                sseCts.Cancel();
                if (sseTask is not null)
                {
                    try
                    {
                        await sseTask;
                    }
                    catch
                    {
                    }
                }
            }
            catch
            {
            }

            sseCts.Dispose();

            if (_agentCancellation is not null)
            {
                _agentCancellation.Dispose();
                _agentCancellation = null;
            }

            _v6OpenCodeLiveText.Clear();

            V6Ui(() =>
            {
                SendButton.IsEnabled = true;
                StopButton.IsEnabled = false;
                CommandBox.IsEnabled = true;
                CommandBox.Focus();
                SetAgentActivity("Ready");
                SaveChatHistory();
            });

            _v6OpenCodeBusy = false;
        }
    }

    // Stop hook: the native abort endpoint is called by V6OpenCodeDirectAbort()
    // (invoked from Stop_Click), then the local tokens are cancelled so the
    // awaiting HTTP calls unwind.
    private void V6OpenCodeDirectAbort()
    {
        string? sessionId;
        string directory = V6OpenCodeDirectory();

        lock (_v6OpenCodeLock)
        {
            sessionId = _v6OpenCodeSessionId;
        }

        if (string.IsNullOrWhiteSpace(sessionId))
            return;

        _ = Task.Run(async () =>
        {
            try
            {
                using var response =
                    await _v6OpenCodeHttp.PostAsync(
                        V6OpenCodeUri(
                            V6OpenCodeBaseUrl(),
                            "/session/" +
                            Uri.EscapeDataString(sessionId) +
                            "/abort",
                            directory),
                        new StringContent("{}", Encoding.UTF8, "application/json"));
            }
            catch
            {
            }
        });
    }

    // -----------------------------------------------------------------------
    // POST /session
    // -----------------------------------------------------------------------
    private async Task<string> V6OpenCodeCreateSessionAsync(
        string baseUrl,
        string directory,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            V6OpenCodeUri(baseUrl, "/session", directory))
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json")
        };

        using HttpResponseMessage response =
            await _v6OpenCodeHttp.SendAsync(
                request,
                cancellationToken);

        string body =
            await response.Content.ReadAsStringAsync(cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                "OpenCode create session failed (" +
                (int)response.StatusCode +
                "): " +
                V6OpenCodeTrim(body));
        }

        using JsonDocument document = JsonDocument.Parse(body);
        JsonElement root = document.RootElement;

        if (root.TryGetProperty("id", out JsonElement idElement) &&
            idElement.ValueKind == JsonValueKind.String)
        {
            string id = idElement.GetString() ?? "";
            if (!string.IsNullOrWhiteSpace(id))
                return id;
        }

        throw new InvalidOperationException(
            "OpenCode create session returned no session id.");
    }

    // -----------------------------------------------------------------------
    // POST /session/{id}/message  (waits for the full turn)
    // -----------------------------------------------------------------------
    private async Task<string> V6OpenCodeSendMessageAsync(
        string baseUrl,
        string directory,
        string sessionId,
        string providerId,
        string modelId,
        string prompt,
        CancellationToken cancellationToken)
    {
        var payload = new Dictionary<string, object?>
        {
            ["model"] = new Dictionary<string, string>
            {
                ["providerID"] = providerId,
                ["modelID"] = modelId
            },
            ["parts"] = new object[]
            {
                new Dictionary<string, string>
                {
                    ["type"] = "text",
                    ["text"] = prompt
                }
            }
        };

        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            V6OpenCodeUri(
                baseUrl,
                "/session/" +
                Uri.EscapeDataString(sessionId) +
                "/message",
                directory))
        {
            Content = new StringContent(
                JsonSerializer.Serialize(payload),
                Encoding.UTF8,
                "application/json")
        };

        using HttpResponseMessage response =
            await _v6OpenCodeHttp.SendAsync(
                request,
                cancellationToken);

        string body =
            await response.Content.ReadAsStringAsync(cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                "OpenCode message failed (" +
                (int)response.StatusCode +
                "): " +
                V6OpenCodeTrim(body));
        }

        return body;
    }

    // Extract the assistant text answer from the message response
    // { info, parts: Part[] }.
    private string V6OpenCodeExtractAnswer(string responseBody)
    {
        using JsonDocument document = JsonDocument.Parse(responseBody);
        JsonElement root = document.RootElement;

        string? errorNote = null;

        if (root.TryGetProperty("info", out JsonElement info) &&
            info.TryGetProperty("error", out JsonElement error) &&
            error.ValueKind == JsonValueKind.Object)
        {
            errorNote = V6OpenCodeErrorText(error);
        }

        var builder = new StringBuilder();

        if (root.TryGetProperty("parts", out JsonElement parts) &&
            parts.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement part in parts.EnumerateArray())
            {
                if (!part.TryGetProperty("type", out JsonElement typeElement))
                    continue;

string type = typeElement.GetString() ?? "";
// Complete readiness for server.connected events before filtering.
if (type == "server.connected")
{
    _readinessTcs.TrySetResult(true);
}

                if (type != "text")
                    continue;

                if (part.TryGetProperty("text", out JsonElement textElement) &&
                    textElement.ValueKind == JsonValueKind.String)
                {
                    builder.Append(textElement.GetString());
                    builder.Append('\n');
                }
            }
        }

        string answer = builder.ToString().Trim();

        if (!string.IsNullOrEmpty(errorNote))
        {
            answer = (answer.Length > 0
                ? answer + "\n\n"
                : "") + errorNote;
        }

        return answer;
    }

    // -----------------------------------------------------------------------
    // GET /session/{id}/diff
    // -----------------------------------------------------------------------
    private async Task<string> V6OpenCodeFetchDiffAsync(
        string baseUrl,
        string directory,
        string sessionId,
        CancellationToken cancellationToken)
    {
        try
        {
            using var response =
                await _v6OpenCodeHttp.GetAsync(
                    V6OpenCodeUri(
                        baseUrl,
                        "/session/" +
                        Uri.EscapeDataString(sessionId) +
                        "/diff",
                        directory),
                    cancellationToken);

            string body =
                await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
                return "";

            using JsonDocument document = JsonDocument.Parse(body);

            if (!document.RootElement.TryGetProperty(
                    "diff",
                    out JsonElement diff) ||
                diff.ValueKind != JsonValueKind.Array)
            {
                if (document.RootElement.ValueKind != JsonValueKind.Array)
                    return "";

                diff = document.RootElement;
            }

            var lines = new List<string>();

            foreach (JsonElement item in diff.EnumerateArray())
            {
                string file =
                    item.TryGetProperty("file", out JsonElement f)
                        ? f.GetString() ?? ""
                        : item.TryGetProperty("path", out JsonElement p)
                            ? p.GetString() ?? ""
                            : "";

                int additions =
                    item.TryGetProperty("additions", out JsonElement a) &&
                    a.ValueKind == JsonValueKind.Number
                        ? a.GetInt32()
                        : 0;

                int deletions =
                    item.TryGetProperty("deletions", out JsonElement d) &&
                    d.ValueKind == JsonValueKind.Number
                        ? d.GetInt32()
                        : 0;

                if (string.IsNullOrWhiteSpace(file))
                    continue;

                lines.Add(
                    file +
                    "  (+" +
                    additions +
                    "/-" +
                    deletions +
                    ")");
            }

            return string.Join("\n", lines);
        }
        catch
        {
            return "";
        }
    }

    // -----------------------------------------------------------------------
    // GET /session/{id}/message  (session message history)
    // -----------------------------------------------------------------------
    private async Task<string> V6OpenCodeFetchMessagesAsync(
        string baseUrl,
        string directory,
        string sessionId,
        CancellationToken cancellationToken)
    {
        try
        {
            using var response =
                await _v6OpenCodeHttp.GetAsync(
                    V6OpenCodeUri(
                        baseUrl,
                        "/session/" +
                        Uri.EscapeDataString(sessionId) +
                        "/message?limit=20",
                        directory),
                    cancellationToken);

            string body =
                await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
                return "";

            using JsonDocument document = JsonDocument.Parse(body);

            if (document.RootElement.ValueKind != JsonValueKind.Array)
                return "";

            var lines = new List<string>();

            foreach (JsonElement item in document.RootElement.EnumerateArray())
            {
                if (!item.TryGetProperty("info", out JsonElement info) ||
                    info.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }

                string role =
                    info.TryGetProperty("role", out JsonElement roleElement)
                        ? roleElement.GetString() ?? ""
                        : "";

                string? textPart = null;

                if (item.TryGetProperty("parts", out JsonElement parts) &&
                    parts.ValueKind == JsonValueKind.Array)
                {
                    foreach (JsonElement part in parts.EnumerateArray())
                    {
                        if (!part.TryGetProperty("type", out JsonElement typeElement))
                            continue;

                        if (typeElement.GetString() != "text")
                            continue;

                        if (part.TryGetProperty("text", out JsonElement textElement) &&
                            textElement.ValueKind == JsonValueKind.String)
                        {
                            string? t = textElement.GetString();
                            if (!string.IsNullOrWhiteSpace(t))
                            {
                                textPart = t.Trim();
                                break;
                            }
                        }
                    }
                }

                if (string.IsNullOrWhiteSpace(textPart))
                    continue;

                lines.Add(
                    "[" +
                    (string.IsNullOrWhiteSpace(role) ? "message" : role) +
                    "] " +
                    textPart.Replace("\r", " ").Replace("\n", " ").Trim());
            }

            return string.Join("\n", lines);
        }
        catch
        {
            return "";
        }
    }

    // -----------------------------------------------------------------------
    // GET /event  (SSE stream) - consumed on a background task.
    // -----------------------------------------------------------------------
    private async Task V6OpenCodeSseLoopAsync(
        string baseUrl,
        string directory,
        string sessionId,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            V6OpenCodeUri(baseUrl, "/event", directory));

        using HttpResponseMessage response =
            await _v6OpenCodeHttp.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            V6OpenCodeLog(
                "[OpenCode] event stream unavailable (" +
                (int)response.StatusCode +
                "). Live status/permissions disabled for this turn.");
            return;
        }

        using Stream stream =
            await response.Content.ReadAsStreamAsync(cancellationToken);

        using var reader = new StreamReader(stream, Encoding.UTF8);

        string? eventName = null;
        var dataBuilder = new StringBuilder();

        while (!cancellationToken.IsCancellationRequested)
        {
            string? line;

            try
            {
                line = await reader.ReadLineAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (IOException)
            {
                break;
            }
            catch (ObjectDisposedException)
            {
                break;
            }

            if (line is null)
                break;

            if (line.StartsWith("event:", StringComparison.Ordinal))
            {
                eventName = line.Substring("event:".Length).Trim();
            }
            else if (line.StartsWith("data:", StringComparison.Ordinal))
            {
                string data = line.Substring("data:".Length);
                if (data.StartsWith(" ", StringComparison.Ordinal) &&
                    data.Length > 1)
                {
                    data = data.Substring(1);
                }
                dataBuilder.Append(data);
            }
            else if (line.Length == 0)
            {
                if (dataBuilder.Length > 0)
                {
                    await V6OpenCodeDispatchEventAsync(
                        sessionId,
                        eventName,
                        dataBuilder.ToString(),
                        cancellationToken);
                }

                eventName = null;
                dataBuilder.Clear();
            }
        }
    }

    // -----------------------------------------------------------------------
    // SSE event dispatch. Filters to the active OpenCode session and maps the
    // raw events to UI status for:
    //   working/thinking, read, edit, tool execution, build/test,
    //   permission request, completion, error.
    // -----------------------------------------------------------------------
    private async Task V6OpenCodeDispatchEventAsync(
        string sessionId,
        string? eventName,
        string data,
        CancellationToken cancellationToken)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(data);
            JsonElement root = document.RootElement;

            if (!root.TryGetProperty("type", out JsonElement typeElement) ||
                typeElement.ValueKind != JsonValueKind.String)
            {
                return;
            }

            string type = typeElement.GetString() ?? "";

            JsonElement props = root.TryGetProperty("properties", out JsonElement p)
                ? p
                : default;

            if (!V6OpenCodeMatchesSession(sessionId, type, props))
                return;

            switch (type)
            {
                case "message.part.updated":
                    V6OpenCodeHandlePartUpdated(props, cancellationToken);
                    break;

                case "message.updated":
                    V6OpenCodeHandleMessageUpdated(props);
                    break;

                case "session.status":
                case "session.idle":
                case "session.status.updated":
                    V6OpenCodeHandleSessionStatus(type, props);
                    break;

                case "session.error":
                    V6OpenCodeHandleSessionError(props);
                    break;

                case "permission.asked":
                case "permission.updated":
                case "permission.request":
                    await V6OpenCodeHandlePermissionAsync(
                        props,
                        cancellationToken);
                    break;

                case "permission.replied":
                    break;
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            // Malformed or unknown events are ignored so the stream never dies
            // on a single bad frame.
        }
    }

    private static bool V6OpenCodeMatchesSession(
        string sessionId,
        string type,
        JsonElement props)
    {
        if (props.ValueKind != JsonValueKind.Object)
            return false;

        switch (type)
        {
            case "message.part.updated":
                if (props.TryGetProperty("part", out JsonElement part) &&
                    part.ValueKind == JsonValueKind.Object &&
                    part.TryGetProperty("sessionID", out JsonElement partSession) &&
                    partSession.ValueKind == JsonValueKind.String)
                {
                    return string.Equals(
                        partSession.GetString(),
                        sessionId,
                        StringComparison.Ordinal);
                }
                break;

            case "message.updated":
                if (props.TryGetProperty("info", out JsonElement info) &&
                    info.ValueKind == JsonValueKind.Object &&
                    info.TryGetProperty("sessionID", out JsonElement infoSession) &&
                    infoSession.ValueKind == JsonValueKind.String)
                {
                    return string.Equals(
                        infoSession.GetString(),
                        sessionId,
                        StringComparison.Ordinal);
                }
                break;
        }

        if (props.TryGetProperty("sessionID", out JsonElement sessionElement) &&
            sessionElement.ValueKind == JsonValueKind.String)
        {
            return string.Equals(
                sessionElement.GetString(),
                sessionId,
                StringComparison.Ordinal);
        }

        return false;
    }

    private void V6OpenCodeHandlePartUpdated(
        JsonElement props,
        CancellationToken cancellationToken)
    {
        if (!props.TryGetProperty("part", out JsonElement part) ||
            part.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        if (!part.TryGetProperty("type", out JsonElement typeElement) ||
            typeElement.ValueKind != JsonValueKind.String)
        {
            return;
        }

        string partType = typeElement.GetString() ?? "";
        string partId = part.TryGetProperty("id", out JsonElement idElement) &&
                        idElement.ValueKind == JsonValueKind.String
            ? idElement.GetString() ?? ""
            : "";

        switch (partType)
        {
            case "reasoning":
                V6OpenCodeSetActivity("Thinking...");
                break;

            case "step-start":
            case "step-finish":
                V6OpenCodeSetActivity("OpenCode working...");
                break;

            case "agent":
                string? agentName = part.TryGetProperty("name", out JsonElement n) &&
                                    n.ValueKind == JsonValueKind.String
                    ? n.GetString()
                    : null;

                V6OpenCodeSetActivity(
                    "Agent: " +
                    (string.IsNullOrWhiteSpace(agentName) ? "build" : agentName));
                break;

            case "text":
                V6OpenCodeHandleTextPart(props, part);
                break;

            case "tool":
                V6OpenCodeHandleToolPart(part);
                break;
        }
    }

    private void V6OpenCodeHandleTextPart(
        JsonElement props,
        JsonElement part)
    {
        string? delta = props.TryGetProperty("delta", out JsonElement deltaElement) &&
                        deltaElement.ValueKind == JsonValueKind.String
            ? deltaElement.GetString()
            : null;

        string? fullText = part.TryGetProperty("text", out JsonElement textElement) &&
                           textElement.ValueKind == JsonValueKind.String
            ? textElement.GetString()
            : null;

        if (!string.IsNullOrEmpty(fullText))
        {
            _v6OpenCodeLiveText.Clear();
            _v6OpenCodeLiveText.Append(fullText);
        }

        if (!string.IsNullOrEmpty(delta))
        {
            _v6OpenCodeLiveText.Append(delta);

            V6OpenCodeLog(delta);
        }
    }

    private void V6OpenCodeHandleToolPart(JsonElement part)
    {
        string tool = part.TryGetProperty("tool", out JsonElement toolElement) &&
                      toolElement.ValueKind == JsonValueKind.String
            ? toolElement.GetString() ?? ""
            : "";

        if (!part.TryGetProperty("state", out JsonElement state) ||
            state.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        string status = state.TryGetProperty("status", out JsonElement statusElement) &&
                        statusElement.ValueKind == JsonValueKind.String
            ? statusElement.GetString() ?? ""
            : "";

        string title = state.TryGetProperty("title", out JsonElement titleElement) &&
                       titleElement.ValueKind == JsonValueKind.String
            ? titleElement.GetString() ?? ""
            : "";

        switch (status)
        {
            case "pending":
                V6OpenCodeSetActivity("Queueing tool: " + tool);
                break;

            case "running":
                V6OpenCodeSetActivity(V6OpenCodeToolActivity(tool, title));
                break;

            case "completed":
                string? output = state.TryGetProperty("output", out JsonElement outputElement) &&
                                 outputElement.ValueKind == JsonValueKind.String
                    ? outputElement.GetString()
                    : null;

                string completedLabel =
                    string.IsNullOrWhiteSpace(title)
                        ? tool
                        : title;

                V6OpenCodeSetActivity("Tool done: " + completedLabel);
                V6OpenCodeLog(
                    "[OpenCode " + tool + "]\n" +
                    V6OpenCodeTrim(output ?? "(no output)"));
                break;

            case "error":
                string? error = state.TryGetProperty("error", out JsonElement errorElement) &&
                                errorElement.ValueKind == JsonValueKind.String
                    ? errorElement.GetString()
                    : "";

                V6OpenCodeSetActivity("Tool error: " + tool);
                V6OpenCodeLog(
                    "[OpenCode " + tool + " error]\n" +
                    V6OpenCodeTrim(error ?? "unknown tool error"));
                break;
        }
    }

    // Map a running tool to a human label. Recognizes build/test commands.
    private static string V6OpenCodeToolActivity(
        string tool,
        string title)
    {
        string label = string.IsNullOrWhiteSpace(title) ? tool : title;

        if (tool == "read")
            return "Reading files...";

        if (tool == "glob" || tool == "grep")
            return "Searching workspace...";

        if (tool == "edit" || tool == "patch")
            return "Editing: " + label;

        if (tool == "webfetch")
            return "Fetching: " + label;

        if (tool == "bash")
        {
            return V6IsBuildTestCommand(label)
                ? "Build/Test: " + label
                : "Shell: " + label;
        }

        return "Tool: " + label;
    }

    private static bool V6IsBuildTestCommand(string command)
    {
        string c = (command ?? "").ToLowerInvariant();

        return c.Contains("dotnet build", StringComparison.Ordinal) ||
               c.Contains("dotnet test", StringComparison.Ordinal) ||
               c.Contains("npm run build", StringComparison.Ordinal) ||
               c.Contains("npm test", StringComparison.Ordinal) ||
               c.Contains("pnpm run build", StringComparison.Ordinal) ||
               c.Contains("pnpm test", StringComparison.Ordinal) ||
               c.Contains("yarn build", StringComparison.Ordinal) ||
               c.Contains("yarn test", StringComparison.Ordinal) ||
               c.Contains("go build", StringComparison.Ordinal) ||
               c.Contains("go test", StringComparison.Ordinal) ||
               c.Contains("cargo build", StringComparison.Ordinal) ||
               c.Contains("cargo test", StringComparison.Ordinal) ||
               c.Contains("pytest", StringComparison.Ordinal) ||
               c.Contains("python -m unittest", StringComparison.Ordinal) ||
               c.Contains("mvn test", StringComparison.Ordinal) ||
               c.Contains("gradle test", StringComparison.Ordinal) ||
               c.Contains("ctest", StringComparison.Ordinal);
    }

    private void V6OpenCodeHandleMessageUpdated(JsonElement props)
    {
        if (!props.TryGetProperty("info", out JsonElement info) ||
            info.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        bool finished =
            info.TryGetProperty("finish", out JsonElement finish) &&
            finish.ValueKind == JsonValueKind.String &&
            !string.IsNullOrEmpty(finish.GetString());

        if (finished)
        {
            V6OpenCodeSetActivity("OpenCode completed");
        }

        if (info.TryGetProperty("error", out JsonElement error) &&
            error.ValueKind == JsonValueKind.Object)
        {
            V6OpenCodeSetActivity("OpenCode error");
            V6OpenCodeLog(
                "[OpenCode error]\n" +
                V6OpenCodeErrorText(error));
        }
    }

    private void V6OpenCodeHandleSessionStatus(
        string type,
        JsonElement props)
    {
        if (type == "session.idle")
        {
            V6OpenCodeSetActivity("OpenCode completed");
            return;
        }

        if (props.TryGetProperty("status", out JsonElement status) &&
            status.ValueKind == JsonValueKind.Object)
        {
            string? statusType = status.TryGetProperty("type", out JsonElement statusTypeElement)
                ? statusTypeElement.GetString()
                : null;

            if (string.Equals(statusType, "busy", StringComparison.Ordinal))
            {
                V6OpenCodeSetActivity("OpenCode working...");
            }
            else if (string.Equals(statusType, "idle", StringComparison.Ordinal))
            {
                V6OpenCodeSetActivity("OpenCode completed");
            }
        }
    }

    private void V6OpenCodeHandleSessionError(JsonElement props)
    {
        string message = "OpenCode session error.";

        if (props.TryGetProperty("error", out JsonElement error) &&
            error.ValueKind == JsonValueKind.Object)
        {
            message = V6OpenCodeErrorText(error);
        }

        V6OpenCodeSetActivity("OpenCode error");
        V6OpenCodeLog("[OpenCode error]\n" + message);
    }

    // -----------------------------------------------------------------------
    // Native permission request/response. No second permission broker.
    // -----------------------------------------------------------------------
    private async Task V6OpenCodeHandlePermissionAsync(
        JsonElement props,
        CancellationToken cancellationToken)
    {
        string permissionId =
            props.TryGetProperty("id", out JsonElement idElement) &&
            idElement.ValueKind == JsonValueKind.String
                ? idElement.GetString() ?? ""
                : "";

        if (string.IsNullOrWhiteSpace(permissionId))
            return;

        bool alreadyReplied;

        lock (_v6OpenCodeLock)
        {
            alreadyReplied = _v6OpenCodeRepliedPermissions.Contains(permissionId);
        }

        if (alreadyReplied)
            return;

        string permission =
            props.TryGetProperty("permission", out JsonElement permElement) &&
            permElement.ValueKind == JsonValueKind.String
                ? permElement.GetString() ?? ""
                : props.TryGetProperty("title", out JsonElement titleElement) &&
                  titleElement.ValueKind == JsonValueKind.String
                    ? titleElement.GetString() ?? ""
                    : "tool";

        string detail = V6OpenCodePermissionDetail(props);

        string reply;

        switch (V6OpenCodePermissionMode())
        {
            case "allow":
                reply = "once";
                break;
            case "always":
                reply = "always";
                break;
            case "deny":
                reply = "reject";
                break;
            default:
                reply = await V6OpenCodePermissionPromptAsync(
                    permission,
                    detail,
                    cancellationToken);
                break;
        }

        lock (_v6OpenCodeLock)
        {
            _v6OpenCodeRepliedPermissions.Add(permissionId);
        }

        await V6OpenCodeReplyPermissionAsync(
            permissionId,
            reply,
            cancellationToken);
    }

    private static string V6OpenCodePermissionDetail(JsonElement props)
    {
        var parts = new List<string>();

        if (props.TryGetProperty("patterns", out JsonElement patterns) &&
            patterns.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement pattern in patterns.EnumerateArray())
            {
                if (pattern.ValueKind == JsonValueKind.String)
                    parts.Add(pattern.GetString() ?? "");
            }
        }

        if (parts.Count == 0 &&
            props.TryGetProperty("pattern", out JsonElement patternElement) &&
            patternElement.ValueKind == JsonValueKind.String)
        {
            parts.Add(patternElement.GetString() ?? "");
        }

        if (props.TryGetProperty("metadata", out JsonElement metadata) &&
            metadata.ValueKind == JsonValueKind.Object)
        {
            foreach (string key in new[] { "command", "path", "url" })
            {
                if (metadata.TryGetProperty(key, out JsonElement value) &&
                    value.ValueKind == JsonValueKind.String)
                {
                    parts.Add(value.GetString() ?? "");
                }
            }
        }

        return parts.Count == 0
            ? "(no detail)"
            : string.Join("\n", parts);
    }

    private async Task<string> V6OpenCodePermissionPromptAsync(
        string permission,
        string detail,
        CancellationToken cancellationToken)
    {
        var tcs = new TaskCompletionSource<string>(
            TaskCreationOptions.RunContinuationsAsynchronously);

        _ =         _ = Dispatcher.BeginInvoke(new Action(() =>
        {
            try
            {
                var window = new Window
                {
                    Title = "OpenCode permission request",
                    Width = 520,
                    Height = 300,
                    WindowStartupLocation = WindowStartupLocation.CenterOwner,
                    Owner = this,
                    ResizeMode = ResizeMode.NoResize,
                    WindowStyle = WindowStyle.ToolWindow,
                    Background = new SolidColorBrush(
                        System.Windows.Media.Color.FromRgb(11, 16, 24)),
                    Foreground = new SolidColorBrush(
                        System.Windows.Media.Color.FromRgb(213, 222, 235))
                };

                var root = new System.Windows.Controls.StackPanel
                {
                    Margin = new Thickness(16)
                };

                root.Children.Add(
                    new System.Windows.Controls.TextBlock
                    {
                        Text = "OpenCode wants permission",
                        FontSize = 15,
                        FontWeight = FontWeights.SemiBold,
                        Foreground = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(226, 232, 240)),
                        Margin = new Thickness(0, 0, 0, 4)
                    });

                root.Children.Add(
                    new System.Windows.Controls.TextBlock
                    {
                        Text = permission,
                        FontSize = 13,
                        TextWrapping = TextWrapping.Wrap,
                        Foreground = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(47, 111, 237)),
                        Margin = new Thickness(0, 0, 0, 10)
                    });

                if (!string.IsNullOrWhiteSpace(detail))
                {
                    var detailBox = new System.Windows.Controls.TextBox
                    {
                        Text = detail,
                        IsReadOnly = true,
                        TextWrapping = TextWrapping.Wrap,
                        MinHeight = 90,
                        MaxHeight = 140,
                        VerticalScrollBarVisibility =
                            System.Windows.Controls.ScrollBarVisibility.Auto,
                        Background = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(15, 22, 32)),
                        Foreground = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(213, 222, 235)),
                        BorderBrush = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(40, 50, 63)),
                        BorderThickness = new Thickness(1),
                        Margin = new Thickness(0, 0, 0, 12),
                        Padding = new Thickness(8)
                    };

                    root.Children.Add(detailBox);
                }

                var buttons = new System.Windows.Controls.StackPanel
                {
                    Orientation = System.Windows.Controls.Orientation.Horizontal
                };

                void AddButton(string text, string reply, SolidColorBrush? background)
                {
                    var button = new System.Windows.Controls.Button
                    {
                        Content = text,
                        Padding = new Thickness(12, 6, 12, 6),
                        Margin = new Thickness(0, 0, 8, 0),
                        Background = background ??
                                     new SolidColorBrush(
                                         System.Windows.Media.Color.FromRgb(30, 41, 59)),
                        Foreground = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(226, 232, 240)),
                        BorderBrush = new SolidColorBrush(
                            System.Windows.Media.Color.FromRgb(51, 65, 85)),
                        BorderThickness = new Thickness(1)
                    };

                    button.Click += (_, _) =>
                    {
                        tcs.TrySetResult(reply);
                        window.Close();
                    };

                    buttons.Children.Add(button);
                }

                AddButton(
                    "Allow once",
                    "once",
                    new SolidColorBrush(System.Windows.Media.Color.FromRgb(47, 111, 237)));

                AddButton("Always allow", "always", null);

                AddButton(
                    "Deny",
                    "reject",
                    new SolidColorBrush(System.Windows.Media.Color.FromRgb(120, 53, 15)));

                root.Children.Add(buttons);

                window.Content = root;

                using CancellationTokenRegistration registration =
                    cancellationToken.Register(() =>
                        Dispatcher.BeginInvoke(new Action(() =>
                        {
                            try
                            {
                                if (window.IsVisible)
                                {
                                    window.Close();
                                }
                            }
                            catch
                            {
                            }
                        })));

                window.Closed += (_, _) =>
                {
                    if (!tcs.Task.IsCompleted)
                    {
                        tcs.TrySetResult("reject");
                    }
                };

                window.ShowDialog();
            }
            catch
            {
                if (!tcs.Task.IsCompleted)
                {
                    tcs.TrySetResult("reject");
                }
            }
        }));

        return await tcs.Task;
    }

    // POST /session/{id}/permissions/{permissionID}
    private async Task V6OpenCodeReplyPermissionAsync(
        string permissionId,
        string reply,
        CancellationToken cancellationToken)
    {
        string? sessionId;

        lock (_v6OpenCodeLock)
        {
            sessionId = _v6OpenCodeSessionId;
        }

        if (string.IsNullOrWhiteSpace(sessionId))
            return;

        try
        {
            var payload = new Dictionary<string, string>
            {
                ["response"] = reply
            };

            using var request = new HttpRequestMessage(
                HttpMethod.Post,
                V6OpenCodeUri(
                    V6OpenCodeBaseUrl(),
                    "/session/" +
                    Uri.EscapeDataString(sessionId) +
                    "/permissions/" +
                    Uri.EscapeDataString(permissionId),
                    V6OpenCodeDirectory()))
            {
                Content = new StringContent(
                    JsonSerializer.Serialize(payload),
                    Encoding.UTF8,
                    "application/json")
            };

            using HttpResponseMessage response =
                await _v6OpenCodeHttp.SendAsync(
                    request,
                    cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                string body =
                    await response.Content.ReadAsStringAsync(cancellationToken);

                V6OpenCodeLog(
                    "[OpenCode] permission reply rejected (" +
                    (int)response.StatusCode +
                    "): " +
                    V6OpenCodeTrim(body));
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            V6OpenCodeLog(
                "[OpenCode] permission reply failed: " +
                ex.Message);
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------
    private static string V6OpenCodeErrorText(JsonElement error)
    {
        if (error.TryGetProperty("data", out JsonElement data) &&
            data.ValueKind == JsonValueKind.Object &&
            data.TryGetProperty("message", out JsonElement message) &&
            message.ValueKind == JsonValueKind.String)
        {
            return message.GetString() ?? "OpenCode error.";
        }

        if (error.TryGetProperty("message", out JsonElement messageElement) &&
            messageElement.ValueKind == JsonValueKind.String)
        {
            return messageElement.GetString() ?? "OpenCode error.";
        }

        string? name = error.TryGetProperty("name", out JsonElement nameElement)
            ? nameElement.GetString()
            : null;

        return string.IsNullOrWhiteSpace(name)
            ? "OpenCode error."
            : name;
    }

    private static string V6OpenCodeTrim(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";

        if (text.Length <= 4000)
            return text;

        return text.Substring(0, 4000) +
               "\n[... truncated ...]";
    }

    private static string V6OpenCodeFriendlyError(Exception ex)
    {
        string message = ex.Message ?? "";

        if (message.IndexOf("refused", StringComparison.OrdinalIgnoreCase) >= 0 ||
            message.IndexOf("target machine", StringComparison.OrdinalIgnoreCase) >= 0 ||
            message.IndexOf("No connection", StringComparison.OrdinalIgnoreCase) >= 0 ||
            message.IndexOf("Couldn't connect", StringComparison.OrdinalIgnoreCase) >= 0)
        {
            return
                "OpenCode server unavailable at " +
                V6OpenCodeBaseUrl() +
                ". Start it with 'opencode serve' (or point " +
                OpenCodeBaseUrlEnv +
                " at the running server), then press Send again.\n\nDetails: " +
                message;
        }

        return "OpenCode direct error: " + message;
    }
}
