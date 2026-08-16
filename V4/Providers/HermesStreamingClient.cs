using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Providers;

public sealed record HermesStreamEvent(
    string Type,
    string? Text = null,
    string? Raw = null);

public sealed class HermesStreamingClient
{
    private readonly HttpClient _http =
        new()
        {
            Timeout = Timeout.InfiniteTimeSpan
        };

    private string BaseUrl =>
        (
            Environment.GetEnvironmentVariable(
                "BOTCONNECTOR_HERMES_BASE_URL")
            ?? "http://127.0.0.1:18642/v1"
        ).TrimEnd('/');

    private string Model =>
        Environment.GetEnvironmentVariable(
            "BOTCONNECTOR_HERMES_MODEL")
        ?? "hermes-agent";

    private string ApiKey =>
        Environment.GetEnvironmentVariable(
            "BOTCONNECTOR_HERMES_API_KEY")
        ?? throw new InvalidOperationException(
            "BOTCONNECTOR_HERMES_API_KEY is not configured.");

    public async Task<string> StreamChatAsync(
        IReadOnlyList<HermesMessage> messages,
        string sessionKey,
        Func<HermesStreamEvent, Task>? onEvent,
        CancellationToken cancellationToken)
    {
        string webMode =
            NormalizeBotConnectorWebMode(
                Environment.GetEnvironmentVariable(
                    "BOTCONNECTOR_WEB_MODE"));

        JsonNode? serializedMessages =
            JsonSerializer.SerializeToNode(
                messages);

        if (serializedMessages is not JsonArray wireMessages)
        {
            throw new InvalidOperationException(
                "Hermes message serialization did not produce an array.");
        }

        wireMessages.Insert(
            0,
            new JsonObject
            {
                ["role"] =
                    "system",

                ["content"] =
                    BuildBotConnectorWebPolicy(
                        webMode)
            });

        var payload =
            JsonSerializer.Serialize(
                new
                {
                    model = Model,
                    messages = wireMessages,
                    stream = true
                });

        using var request =
            new HttpRequestMessage(
                HttpMethod.Post,
                BaseUrl + "/chat/completions");

        request.Headers.Authorization =
            new AuthenticationHeaderValue(
                "Bearer",
                ApiKey);

        request.Headers.Accept.Add(
            new MediaTypeWithQualityHeaderValue(
                "text/event-stream"));

        // Stable memory/channel scope only.
        // Transcript continuity is owned locally by BotConnector.
        request.Headers.TryAddWithoutValidation(
            "X-Hermes-Session-Key",
            sessionKey);

        request.Headers.TryAddWithoutValidation(
            "X-BotConnector-Web-Mode",
            webMode);

        request.Content =
            new StringContent(
                payload,
                Encoding.UTF8,
                "application/json");

        using var response =
            await _http.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            string error =
                await response.Content
                    .ReadAsStringAsync(
                        cancellationToken);

            throw new InvalidOperationException(
                $"Hermes HTTP {(int)response.StatusCode}: {error}");
        }

        if (onEvent is not null)
        {
            await onEvent(
                new HermesStreamEvent(
                    "stream.started"));
        }

        await using var stream =
            await response.Content
                .ReadAsStreamAsync(
                    cancellationToken);

        using var reader =
            new StreamReader(
                stream,
                Encoding.UTF8,
                detectEncodingFromByteOrderMarks: true);

        var assistant =
            new StringBuilder();

        string currentEvent =
            "message";

        var dataBuffer =
            new StringBuilder();

        async Task FlushAsync()
        {
            if (dataBuffer.Length == 0)
                return;

            string data =
                dataBuffer
                    .ToString()
                    .TrimEnd('\n');

            dataBuffer.Clear();

            if (data == "[DONE]")
                return;

            if (
                currentEvent.Equals(
                    "hermes.tool.progress",
                    StringComparison.OrdinalIgnoreCase)
            )
            {
                if (onEvent is not null)
                {
                    await onEvent(
                        new HermesStreamEvent(
                            "hermes.tool.progress",
                            Raw: data));
                }

                return;
            }

            try
            {
                using var doc =
                    JsonDocument.Parse(data);

                var root =
                    doc.RootElement;

                if (
                    root.TryGetProperty(
                        "choices",
                        out var choices)
                    &&
                    choices.ValueKind ==
                        JsonValueKind.Array
                    &&
                    choices.GetArrayLength() > 0
                )
                {
                    var choice =
                        choices[0];

                    if (
                        choice.TryGetProperty(
                            "delta",
                            out var delta)
                        &&
                        delta.ValueKind ==
                            JsonValueKind.Object
                        &&
                        delta.TryGetProperty(
                            "content",
                            out var content)
                        &&
                        content.ValueKind ==
                            JsonValueKind.String
                    )
                    {
                        string text =
                            content.GetString()
                            ?? string.Empty;

                        if (text.Length > 0)
                        {
                            assistant.Append(text);

                            if (onEvent is not null)
                            {
                                await onEvent(
                                    new HermesStreamEvent(
                                        "assistant.delta",
                                        Text: text));
                            }
                        }
                    }
                }
                else if (onEvent is not null)
                {
                    await onEvent(
                        new HermesStreamEvent(
                            currentEvent,
                            Raw: data));
                }
            }
            catch
            {
                if (onEvent is not null)
                {
                    await onEvent(
                        new HermesStreamEvent(
                            currentEvent,
                            Raw: data));
                }
            }
        }

        while (!reader.EndOfStream)
        {
            cancellationToken
                .ThrowIfCancellationRequested();

            string? line =
                await reader.ReadLineAsync(
                    cancellationToken);

            if (line is null)
                break;

            if (line.Length == 0)
            {
                await FlushAsync();
                currentEvent = "message";
                continue;
            }

            if (
                line.StartsWith(
                    "event:",
                    StringComparison.OrdinalIgnoreCase)
            )
            {
                currentEvent =
                    line.Substring(6).Trim();

                continue;
            }

            if (
                line.StartsWith(
                    "data:",
                    StringComparison.OrdinalIgnoreCase)
            )
            {
                if (dataBuffer.Length > 0)
                    dataBuffer.Append('\n');

                dataBuffer.Append(
                    line.Substring(5).TrimStart());
            }
        }

        await FlushAsync();

        if (onEvent is not null)
        {
            await onEvent(
                new HermesStreamEvent(
                    "stream.completed"));
        }

        return assistant.ToString();
    }

    private static string NormalizeBotConnectorWebMode(
        string? mode)
    {
        string value =
            (mode ?? "")
            .Trim()
            .ToLowerInvariant();

        return value switch
        {
            "off" =>
                "off",

            "search" =>
                "search",

            "deep_research" =>
                "deep_research",

            "url_docs" =>
                "url_docs",

            _ =>
                "auto"
        };
    }

    private static string BuildBotConnectorWebPolicy(
        string mode)
    {
        const string approvalBoundary =
            "Public web search and public page/document reading may be used " +
            "when this mode allows it. Login, form submission, outbound upload, " +
            "purchase, account changes, or other external side effects require " +
            "explicit user approval. Do not treat web research permission as " +
            "permission for external side effects.";

        return mode switch
        {
            "off" =>
                "BOTCONNECTOR WEB POLICY: OFF. " +
                "Do not use internet/web research tools for this turn. " +
                "Use only user-provided content, local workspace context, " +
                "and already-available internal context. " +
                approvalBoundary,

            "search" =>
                "BOTCONNECTOR WEB POLICY: SEARCH. " +
                "You may use public web search and read public pages when useful. " +
                "Prefer authoritative/current sources and report sources used. " +
                approvalBoundary,

            "deep_research" =>
                "BOTCONNECTOR WEB POLICY: DEEP RESEARCH. " +
                "Perform multi-source public-web research when relevant, compare " +
                "important sources, reconcile disagreements explicitly, and " +
                "report the sources used. " +
                approvalBoundary,

            "url_docs" =>
                "BOTCONNECTOR WEB POLICY: URL/DOCS. " +
                "Prioritize URLs, documentation, PDFs, and public technical " +
                "references supplied by the user or directly relevant to the task. " +
                "Avoid broad web searching unless needed to resolve the supplied " +
                "material. " +
                approvalBoundary,

            _ =>
                "BOTCONNECTOR WEB POLICY: AUTO. " +
                "Decide whether public web research is needed. Use it for " +
                "fresh/current/external facts or documentation when helpful; " +
                "skip it when local/user-provided context is sufficient. " +
                "Prefer authoritative/current sources and report sources used. " +
                approvalBoundary
        };
    }}