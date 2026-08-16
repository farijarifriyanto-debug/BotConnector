using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Providers;

public sealed record HermesMessage(
    string role,
    string content);

public sealed class HermesOpenAiClient
{
    private readonly HttpClient _http =
        new()
        {
            Timeout = TimeSpan.FromMinutes(10)
        };

    private readonly bool _explicitBase;

    public string BaseUrl { get; private set; }

    public string Model =>
        Environment.GetEnvironmentVariable(
            "BOTCONNECTOR_HERMES_MODEL")
        ?? "hermes-agent";

    public HermesOpenAiClient()
    {
        var configured =
            Environment.GetEnvironmentVariable(
                "BOTCONNECTOR_HERMES_BASE_URL");

        _explicitBase =
            !string.IsNullOrWhiteSpace(configured);

        BaseUrl =
            configured?.TrimEnd('/')
            ?? "http://127.0.0.1:18642/v1";
    }

    private string? ApiKey =>
        Environment.GetEnvironmentVariable(
            "BOTCONNECTOR_HERMES_API_KEY");

    private HttpRequestMessage Request(
        HttpMethod method,
        string url)
    {
        var request =
            new HttpRequestMessage(
                method,
                url);

        var key = ApiKey;

        if (!string.IsNullOrWhiteSpace(key))
        {
            request.Headers.Authorization =
                new AuthenticationHeaderValue(
                    "Bearer",
                    key);
        }

        return request;
    }

    public async Task<bool> ProbeAsync(
        CancellationToken cancellationToken)
    {
        var candidates =
            _explicitBase
            ? new[] { BaseUrl }
            : new[]
            {
                BaseUrl,
                "http://127.0.0.1:8642/v1"
            };

        foreach (var candidate in candidates)
        {
            try
            {
                using var request =
                    Request(
                        HttpMethod.Get,
                        candidate + "/models");

                using var response =
                    await _http.SendAsync(
                        request,
                        cancellationToken);

                // 200 = configured/authenticated.
                // 401/403 = Hermes reachable but key missing/wrong.
                if (
                    response.IsSuccessStatusCode ||
                    (int)response.StatusCode == 401 ||
                    (int)response.StatusCode == 403)
                {
                    BaseUrl = candidate;
                    return true;
                }
            }
            catch
            {
            }
        }

        return false;
    }

    public async Task<string> SendAsync(
        IReadOnlyList<HermesMessage> messages,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(ApiKey))
        {
            throw new InvalidOperationException(
                "BOTCONNECTOR_HERMES_API_KEY belum dikonfigurasi.");
        }

        var body =
            JsonSerializer.Serialize(
                new
                {
                    model = Model,
                    messages,
                    stream = false
                });

        using var request =
            Request(
                HttpMethod.Post,
                BaseUrl + "/chat/completions");

        request.Content =
            new StringContent(
                body,
                Encoding.UTF8,
                "application/json");

        using var response =
            await _http.SendAsync(
                request,
                cancellationToken);

        var json =
            await response.Content
                .ReadAsStringAsync(
                    cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                $"Hermes HTTP {(int)response.StatusCode}: {json}");
        }

        using var doc =
            JsonDocument.Parse(json);

        return doc
            .RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString()
            ?? "";
    }
}