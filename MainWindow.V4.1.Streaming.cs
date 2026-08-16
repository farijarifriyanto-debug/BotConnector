using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

using BotConnector.Desktop.V4.Providers;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private sealed class V41PersistentState
    {
        public string SessionKey { get; set; } =
            "bc:" +
            Guid.NewGuid().ToString("N");

        public List<HermesMessage> Messages { get; set; } =
            new();

        public DateTimeOffset UpdatedAt { get; set; } =
            DateTimeOffset.UtcNow;
    }

    private readonly HermesStreamingClient
        _v41Streaming = new();

    private string
        _v41SessionKey = string.Empty;

    private string
        _v41SessionPath = string.Empty;

    private string
        _v41WorkspaceIdentity = string.Empty;

    private string
        _v41LivePreview = string.Empty;

    private bool
        _v41RemoteToolObserved;

    private bool
        _v411RemoteToolSignalLogged;

    private void V41EnsureSessionForCurrentWorkspace()
    {
        string workspaceIdentity =
            string.IsNullOrWhiteSpace(_workspace)
                ? "no-workspace"
                : Path.GetFullPath(_workspace)
                    .ToLowerInvariant();

        if (
            string.Equals(
                workspaceIdentity,
                _v41WorkspaceIdentity,
                StringComparison.Ordinal)
            &&
            !string.IsNullOrWhiteSpace(
                _v41SessionPath)
        )
        {
            return;
        }

        _v41WorkspaceIdentity =
            workspaceIdentity;

        string stateRoot =
            Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData),
                "BotConnector",
                "Sessions");

        Directory.CreateDirectory(
            stateRoot);

        string hash;

        using (var sha = SHA256.Create())
        {
            hash =
                Convert.ToHexString(
                    sha.ComputeHash(
                        Encoding.UTF8.GetBytes(
                            workspaceIdentity)))
                .ToLowerInvariant();
        }

        _v41SessionPath =
            Path.Combine(
                stateRoot,
                $"workspace-{hash[..16]}.json");

        V41PersistentState state;

        try
        {
            if (File.Exists(_v41SessionPath))
            {
                state =
                    JsonSerializer.Deserialize<V41PersistentState>(
                        File.ReadAllText(
                            _v41SessionPath,
                            Encoding.UTF8))
                    ?? new V41PersistentState();
            }
            else
            {
                state =
                    new V41PersistentState();
            }
        }
        catch
        {
            state =
                new V41PersistentState();
        }

        _v41SessionKey =
            string.IsNullOrWhiteSpace(
                state.SessionKey)
                ? "bc:" +
                  Guid.NewGuid().ToString("N")
                : state.SessionKey;

        _v4HermesMessages.Clear();

        foreach (
            var message in state.Messages
                .Where(
                    m =>
                        !string.Equals(
                            m.role,
                            "system",
                            StringComparison.OrdinalIgnoreCase))
                .TakeLast(80)
        )
        {
            _v4HermesMessages.Add(
                message);
        }

        V41PersistSession();

        AppendTerminal(
            "[V4.1 Session] Windows-local session restored.");

        SetAgentActivity(
            "Hermes ready \u2022 session restored");
    }

    private void V41PersistSession()
    {
        if (
            string.IsNullOrWhiteSpace(
                _v41SessionPath)
        )
        {
            return;
        }

        try
        {
            var state =
                new V41PersistentState
                {
                    SessionKey =
                        _v41SessionKey,

                    Messages =
                        _v4HermesMessages
                            .Where(
                                m =>
                                    !string.Equals(
                                        m.role,
                                        "system",
                                        StringComparison.OrdinalIgnoreCase))
                            .TakeLast(80)
                            .ToList(),

                    UpdatedAt =
                        DateTimeOffset.UtcNow
                };

            string json =
                JsonSerializer.Serialize(
                    state,
                    new JsonSerializerOptions
                    {
                        WriteIndented = true
                    });

            File.WriteAllText(
                _v41SessionPath,
                json,
                new UTF8Encoding(false));
        }
        catch (Exception ex)
        {
            AppendTerminal(
                "[V4.1 Session] Persistence warning: " +
                ex.Message);
        }
    }

    private async Task<string> V41SendHermesStreamingAsync(
        IReadOnlyList<HermesMessage> messages,
        CancellationToken cancellationToken)
    {
        V41EnsureSessionForCurrentWorkspace();

        _v41LivePreview =
            string.Empty;

        _v41RemoteToolObserved =
            false;

        _v411RemoteToolSignalLogged =
            false;

        return await _v41Streaming.StreamChatAsync(
            messages,
            _v41SessionKey,
            V41HandleStreamEventAsync,
            cancellationToken);
    }

    private Task V41HandleStreamEventAsync(
        HermesStreamEvent evt)
    {
        return Dispatcher.InvokeAsync(
            () =>
            {
                switch (evt.Type)
                {
                    case "stream.started":

                        SetAgentActivity(
                            "Hermes \u2022 streaming\u2026");

                        AppendTerminal(
                            "[Hermes] Stream started.");

                        break;

                    case "assistant.delta":

                        if (!string.IsNullOrEmpty(evt.Text))
                        {
                            _v41LivePreview +=
                                evt.Text;

                            if (_v41LivePreview.Length > 180)
                            {
                                _v41LivePreview =
                                    _v41LivePreview[^180..];
                            }

                            string preview =
                                _v41LivePreview
                                    .Replace("\r", " ")
                                    .Replace("\n", " ")
                                    .Trim();

                            SetAgentActivity(
                                string.IsNullOrWhiteSpace(preview)
                                    ? "Hermes \u2022 reasoning\u2026"
                                    : "Hermes \u2022 " + preview);
                        }

                        break;

                    case "hermes.tool.progress":

                        _v41RemoteToolObserved =
                            true;

                        if (!_v411RemoteToolSignalLogged)
                        {
                            _v411RemoteToolSignalLogged =
                                true;

                            AppendTerminal(
                                "[Hermes Remote Tool] " +
                                "Detected once. Desktop will not accept VPS-only execution.");

                            SetAgentActivity(
                                "Remote Hermes tool detected - evaluating policy");
                        }

                        break;

                    case "stream.completed":

                        SetAgentActivity(
                            "Hermes \u2022 reviewing result\u2026");

                        AppendTerminal(
                            "[Hermes] Stream completed.");

                        break;

                    default:

                        if (
                            !string.IsNullOrWhiteSpace(
                                evt.Type)
                            &&
                            evt.Type != "message"
                        )
                        {
                            AppendTerminal(
                                "[Hermes Event] " +
                                evt.Type);
                        }

                        break;
                }
            }
        ).Task;
    }

    private bool V41RemoteToolViolation()
    {
        bool observed =
            _v41RemoteToolObserved;

        _v41RemoteToolObserved =
            false;

        return observed;
    }
}