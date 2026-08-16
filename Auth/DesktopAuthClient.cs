using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Auth;

public sealed class DesktopAuthClient
{
    private const string BaseUrl =
        "https://botconnector.id/desktop-ai/v1";

    private readonly HttpClient _http =
        new HttpClient
        {
            Timeout =
                TimeSpan.FromSeconds(30)
        };

    private readonly TokenStore _store =
        new();

    private readonly SemaphoreSlim _authGate =
        new SemaphoreSlim(1, 1);

    private string? _verifiedAccessToken;

    // ---- Local model mode (LM Studio / any OpenAI-compatible server) ----
    public bool UseLocalModel { get; set; }

    public string LocalBaseUrl { get; set; } =
        "http://localhost:1234/v1";

    // Empty = let the local server use whatever model is loaded.
    public string LocalModel { get; set; } = "";

    private readonly HttpClient _localHttp =
        new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(10)
        };

    private sealed class LocalMsg
    {
        public string role { get; set; } = "user";
        public string content { get; set; } = "";
    }

    private readonly System.Collections.Generic.Dictionary<
        string,
        System.Collections.Generic.List<LocalMsg>>
        _localConversations = new();


    public AuthTokenPair? Current
    {
        get;
        private set;
    }

    public bool HasStoredToken =>
        _store.Exists;

    public void LoadStored()
    {
        try
        {
            Current =
                _store.Load();
        }
        catch
        {
            _store.Clear();
            Current = null;
        }
    }

    public async Task<AuthTokenPair>
        SignInAsync(
            string deviceName,
            CancellationToken
                cancellationToken = default)
    {
        var deviceId =
            CreateDeviceId();

        var verifier =
            Base64Url(
                RandomNumberGenerator
                    .GetBytes(64));

        var challenge =
            Base64Url(
                SHA256.HashData(
                    Encoding.ASCII.GetBytes(
                        verifier)));

        var state =
            Base64Url(
                RandomNumberGenerator
                    .GetBytes(32));

        using var listener =
            new TcpListener(
                IPAddress.Loopback,
                0);

        listener.Start();

        var endpoint =
            (IPEndPoint)
            listener.LocalEndpoint;

        var callback =
            $"http://127.0.0.1:{endpoint.Port}/callback";

        var authorize =
            BaseUrl
            + "/auth/authorize"
            + "?device_id="
            + Uri.EscapeDataString(
                deviceId)
            + "&device_name="
            + Uri.EscapeDataString(
                deviceName)
            + "&code_challenge="
            + Uri.EscapeDataString(
                challenge)
            + "&redirect_uri="
            + Uri.EscapeDataString(
                callback)
            + "&state="
            + Uri.EscapeDataString(
                state);

        Process.Start(
            new ProcessStartInfo
            {
                FileName =
                    authorize,
                UseShellExecute =
                    true
            });

        using var client =
            await listener.AcceptTcpClientAsync(
                cancellationToken);

        using var stream =
            client.GetStream();

        using var reader =
            new StreamReader(
                stream,
                Encoding.ASCII,
                false,
                4096,
                leaveOpen: true);

        var requestLine =
            await reader.ReadLineAsync(
                cancellationToken);

        if (
            string.IsNullOrWhiteSpace(
                requestLine))
        {
            throw new
                InvalidOperationException(
                    "Empty login callback.");
        }

        string? headerLine;

        do
        {
            headerLine =
                await reader.ReadLineAsync(
                    cancellationToken);
        }
        while (
            headerLine is not null &&
            headerLine.Length != 0);

        var parts =
            requestLine.Split(' ');

        if (parts.Length < 2)
        {
            throw new
                InvalidOperationException(
                    "Invalid login callback.");
        }

        var target =
            parts[1];

        var callbackUri =
            new Uri(
                "http://127.0.0.1"
                + target);

        if (
            callbackUri.AbsolutePath
            != "/callback")
        {
            throw new
                InvalidOperationException(
                    "Unexpected callback path.");
        }

        var query =
            ParseQuery(
                callbackUri.Query);

        query.TryGetValue(
            "code",
            out var code);

        query.TryGetValue(
            "state",
            out var returnedState);

        var html =
            "<!doctype html>"
            + "<html><head>"
            + "<meta charset='utf-8'>"
            + "<title>BotConnector</title>"
            + "</head>"
            + "<body style='font-family:Segoe UI,"
            + "Arial;padding:32px'>"
            + "<h2>BotConnector</h2>"
            + "<p>Login selesai. "
            + "Anda boleh menutup tab ini.</p>"
            + "</body></html>";

        var bodyBytes =
            Encoding.UTF8.GetBytes(
                html);

        var responseHeader =
            "HTTP/1.1 200 OK\r\n"
            + "Content-Type: text/html; "
            + "charset=utf-8\r\n"
            + "Cache-Control: no-store\r\n"
            + "Connection: close\r\n"
            + "Content-Length: "
            + bodyBytes.Length
            + "\r\n\r\n";

        var headerBytes =
            Encoding.ASCII.GetBytes(
                responseHeader);

        await stream.WriteAsync(
            headerBytes,
            cancellationToken);

        await stream.WriteAsync(
            bodyBytes,
            cancellationToken);

        await stream.FlushAsync(
            cancellationToken);

        listener.Stop();

        if (
            string.IsNullOrWhiteSpace(
                code))
        {
            throw new
                InvalidOperationException(
                    "Authorization code missing.");
        }

        if (
            !string.Equals(
                state,
                returnedState,
                StringComparison.Ordinal))
        {
            throw new
                InvalidOperationException(
                    "Authorization state mismatch.");
        }

        var payload =
            JsonSerializer.Serialize(
                new
                {
                    code,
                    verifier,
                    state,
                    redirect_uri =
                        callback
                });

        using var response =
            await _http.PostAsync(
                BaseUrl
                    + "/auth/token",
                new StringContent(
                    payload,
                    Encoding.UTF8,
                    "application/json"),
                cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new
                InvalidOperationException(
                    "Token exchange failed: "
                    + "HTTP "
                    + (int)
                        response.StatusCode);
        }

        var json =
            await response.Content
                .ReadAsStringAsync(
                    cancellationToken);

        var pair =
            JsonSerializer
                .Deserialize<AuthTokenPair>(
                    json)
            ?? throw new
                InvalidOperationException(
                    "Invalid token response.");

        if (
            string.IsNullOrWhiteSpace(
                pair.access_token)
            ||
            string.IsNullOrWhiteSpace(
                pair.refresh_token))
        {
            throw new
                InvalidOperationException(
                    "Token response incomplete.");
        }

        Current = pair;

        _store.Save(pair);

        return pair;
    }

    public async Task<bool>
        VerifyAsync(
            CancellationToken cancellationToken = default)
    {
        await _authGate.WaitAsync(
            cancellationToken);

        try
        {
            if (Current is null)
            {
                return false;
            }

            bool valid =
                await VerifyCurrentCoreAsync(
                    cancellationToken);

            _verifiedAccessToken =
                valid
                    ? Current.access_token
                    : null;

            return valid;
        }
        finally
        {
            _authGate.Release();
        }
    }

    public async Task<bool>
        RefreshAsync(
            CancellationToken cancellationToken = default)
    {
        await _authGate.WaitAsync(
            cancellationToken);

        try
        {
            if (Current is null)
            {
                LoadStored();
            }

            if (Current is null)
            {
                return false;
            }

            bool refreshed =
                await RefreshCoreAsync(
                    cancellationToken);

            if (!refreshed)
            {
                return false;
            }

            bool valid =
                await VerifyCurrentCoreAsync(
                    cancellationToken);

            _verifiedAccessToken =
                valid
                    ? Current?.access_token
                    : null;

            return valid;
        }
        finally
        {
            _authGate.Release();
        }
    }

    public sealed class ChatResponse
    {
        public bool ok { get; set; }

        public string conversation_id
        {
            get;
            set;
        } = "";

        public System.Text.Json.JsonElement result
        {
            get;
            set;
        }
    }


    public async Task<ChatResponse>
        SendChatAsync(
            string content,
            string? conversationId,
            CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            throw new ArgumentException(
                "Chat content is required.",
                nameof(content));
        }

        if (UseLocalModel)
        {
            return await SendLocalChatAsync(
                content,
                conversationId,
                cancellationToken);
        }

        string accessToken =
            await GetUsableAccessTokenAsync(
                cancellationToken);

        using HttpResponseMessage response =
            await SendChatRequestAsync(
                content,
                conversationId,
                accessToken,
                cancellationToken);

        if (
            response.StatusCode !=
            HttpStatusCode.Unauthorized)
        {
            return
                await ReadChatResponseAsync(
                    response,
                    cancellationToken);
        }

        string? retryToken =
            await RefreshAfterUnauthorizedAsync(
                accessToken,
                cancellationToken);

        if (
            string.IsNullOrWhiteSpace(
                retryToken))
        {
            throw new InvalidOperationException(
                "Authentication needs renewal. Sign in again if this persists.");
        }

        using HttpResponseMessage retry =
            await SendChatRequestAsync(
                content,
                conversationId,
                retryToken,
                cancellationToken);

        if (
            retry.StatusCode ==
            HttpStatusCode.Unauthorized)
        {
            throw new InvalidOperationException(
                "Authentication failed after one retry. Sign in again.");
        }

        return
            await ReadChatResponseAsync(
                retry,
                cancellationToken);
    }


    private async Task<ChatResponse>
        SendLocalChatAsync(
            string content,
            string? conversationId,
            CancellationToken cancellationToken)
    {
        string id =
            string.IsNullOrWhiteSpace(conversationId)
                ? Guid.NewGuid().ToString("N")
                : conversationId;

        if (!_localConversations.TryGetValue(
                id,
                out var history))
        {
            history =
                new System.Collections.Generic.List<LocalMsg>();
            _localConversations[id] = history;
        }

        history.Add(
            new LocalMsg { role = "user", content = content });

        var payload =
            new
            {
                model =
                    string.IsNullOrWhiteSpace(LocalModel)
                        ? "local-model"
                        : LocalModel,
                messages = history,
                temperature = 0.2,
                stream = false
            };

        string json =
            JsonSerializer.Serialize(payload);

        string url =
            LocalBaseUrl.TrimEnd('/') + "/chat/completions";

        using var request =
            new HttpRequestMessage(
                HttpMethod.Post,
                url);

        request.Content =
            new StringContent(
                json,
                Encoding.UTF8,
                "application/json");

        HttpResponseMessage response;

        try
        {
            response =
                await _localHttp.SendAsync(
                    request,
                    HttpCompletionOption.ResponseContentRead,
                    cancellationToken);
        }
        catch (HttpRequestException ex)
        {
            throw new InvalidOperationException(
                "Local AI not reachable at " +
                url +
                ". Start the LM Studio local server first. (" +
                ex.Message +
                ")");
        }

        using (response)
        {
            string body =
                await response.Content.ReadAsStringAsync(
                    cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                throw new InvalidOperationException(
                    "Local AI HTTP " +
                    ((int)response.StatusCode) +
                    ": " +
                    body);
            }

            string reply =
                ExtractOpenAiContent(body);

            history.Add(
                new LocalMsg
                {
                    role = "assistant",
                    content = reply
                });

            using var doc =
                JsonDocument.Parse(
                    JsonSerializer.Serialize(reply));

            return new ChatResponse
            {
                ok = true,
                conversation_id = id,
                result = doc.RootElement.Clone()
            };
        }
    }


    private static string ExtractOpenAiContent(
        string body)
    {
        try
        {
            using var doc =
                JsonDocument.Parse(body);

            var root = doc.RootElement;

            if (
                root.TryGetProperty("choices", out var choices) &&
                choices.ValueKind == JsonValueKind.Array &&
                choices.GetArrayLength() > 0)
            {
                var first = choices[0];

                if (
                    first.TryGetProperty("message", out var msg) &&
                    msg.TryGetProperty("content", out var c))
                {
                    return c.GetString() ?? "";
                }

                if (first.TryGetProperty("text", out var t))
                {
                    return t.GetString() ?? "";
                }
            }

            if (root.TryGetProperty("error", out var err))
            {
                return "Local AI error: " + err.ToString();
            }
        }
        catch
        {
        }

        return body;
    }


    private async Task<HttpResponseMessage>
        SendChatRequestAsync(
            string content,
            string? conversationId,
            string accessToken,
            CancellationToken cancellationToken)
    {
        string json =
            JsonSerializer.Serialize(
                new
                {
                    content,
                    conversation_id =
                        string.IsNullOrWhiteSpace(
                            conversationId)
                        ? null
                        : conversationId
                });

        using var request =
            new HttpRequestMessage(
                HttpMethod.Post,
                BaseUrl + "/chat");

        request.Headers.Authorization =
            new AuthenticationHeaderValue(
                "Bearer",
                accessToken);

        request.Content =
            new StringContent(
                json,
                Encoding.UTF8,
                "application/json");

        return
            await _http.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
    }


    private static async System.Threading.Tasks.Task<ChatResponse>
        ReadChatResponseAsync(
            System.Net.Http.HttpResponseMessage response,
            System.Threading.CancellationToken cancellationToken)
    {
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException(
                "AI HTTP " +
                ((int)response.StatusCode));
        }

        string json =
            await response.Content.ReadAsStringAsync(
                cancellationToken);

        ChatResponse? result =
            System.Text.Json.JsonSerializer
                .Deserialize<ChatResponse>(
                    json);

        if (
            result is null ||
            !result.ok ||
            string.IsNullOrWhiteSpace(
                result.conversation_id))
        {
            throw new InvalidOperationException(
                "Invalid AI response.");
        }

        return result;
    }

    private async Task<bool>
        VerifyCurrentCoreAsync(
            CancellationToken cancellationToken)
    {
        if (
            Current is null ||
            string.IsNullOrWhiteSpace(
                Current.access_token))
        {
            return false;
        }

        string accessToken =
            Current.access_token;

        using var request =
            new HttpRequestMessage(
                HttpMethod.Get,
                BaseUrl + "/auth/verify");

        request.Headers.Authorization =
            new AuthenticationHeaderValue(
                "Bearer",
                accessToken);

        using var response =
            await _http.SendAsync(
                request,
                cancellationToken);

        return response.IsSuccessStatusCode;
    }


    private async Task<bool>
        RefreshCoreAsync(
            CancellationToken cancellationToken)
    {
        if (
            Current is null ||
            string.IsNullOrWhiteSpace(
                Current.refresh_token))
        {
            return false;
        }

        string refreshToken =
            Current.refresh_token;

        string payload =
            JsonSerializer.Serialize(
                new
                {
                    refresh_token =
                        refreshToken
                });

        using var response =
            await _http.PostAsync(
                BaseUrl + "/auth/refresh",
                new StringContent(
                    payload,
                    Encoding.UTF8,
                    "application/json"),
                cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            return false;
        }

        string json =
            await response.Content
                .ReadAsStringAsync(
                    cancellationToken);

        AuthTokenPair? pair =
            JsonSerializer
                .Deserialize<AuthTokenPair>(
                    json);

        if (
            pair is null ||
            string.IsNullOrWhiteSpace(
                pair.access_token) ||
            string.IsNullOrWhiteSpace(
                pair.refresh_token))
        {
            return false;
        }

        Current =
            pair;

        _verifiedAccessToken =
            null;

        _store.Save(
            pair);

        return true;
    }


    private async Task<string>
        GetUsableAccessTokenAsync(
            CancellationToken cancellationToken)
    {
        await _authGate.WaitAsync(
            cancellationToken);

        try
        {
            if (Current is null)
            {
                LoadStored();
            }

            if (Current is null)
            {
                throw new InvalidOperationException(
                    "Sign in is required.");
            }

            if (
                !string.IsNullOrWhiteSpace(
                    _verifiedAccessToken) &&
                string.Equals(
                    _verifiedAccessToken,
                    Current.access_token,
                    StringComparison.Ordinal))
            {
                return Current.access_token;
            }

            bool valid =
                await VerifyCurrentCoreAsync(
                    cancellationToken);

            if (!valid)
            {
                bool refreshed =
                    await RefreshCoreAsync(
                        cancellationToken);

                if (!refreshed)
                {
                    throw new InvalidOperationException(
                        "Authentication needs renewal. Sign in again if this persists.");
                }

                valid =
                    await VerifyCurrentCoreAsync(
                        cancellationToken);

                if (!valid)
                {
                    throw new InvalidOperationException(
                        "Authentication could not be verified.");
                }
            }

            if (Current is null)
            {
                throw new InvalidOperationException(
                    "Authentication state unavailable.");
            }

            _verifiedAccessToken =
                Current.access_token;

            return Current.access_token;
        }
        finally
        {
            _authGate.Release();
        }
    }


    private async Task<string?>
        RefreshAfterUnauthorizedAsync(
            string failedAccessToken,
            CancellationToken cancellationToken)
    {
        await _authGate.WaitAsync(
            cancellationToken);

        try
        {
            if (Current is null)
            {
                LoadStored();
            }

            if (Current is null)
            {
                return null;
            }

            if (
                !string.Equals(
                    Current.access_token,
                    failedAccessToken,
                    StringComparison.Ordinal))
            {
                _verifiedAccessToken =
                    Current.access_token;

                return Current.access_token;
            }

            _verifiedAccessToken =
                null;

            bool refreshed =
                await RefreshCoreAsync(
                    cancellationToken);

            if (!refreshed)
            {
                return null;
            }

            bool valid =
                await VerifyCurrentCoreAsync(
                    cancellationToken);

            if (
                !valid ||
                Current is null)
            {
                return null;
            }

            _verifiedAccessToken =
                Current.access_token;

            return Current.access_token;
        }
        finally
        {
            _authGate.Release();
        }
    }

    public void SignOutLocal()
    {
        _verifiedAccessToken =
            null;

        Current =
            null;

        _store.Clear();
    }

    private static string
        CreateDeviceId()
    {
        var source =
            Environment.UserName
            + "|"
            + Environment.MachineName;

        var hash =
            SHA256.HashData(
                Encoding.UTF8.GetBytes(
                    source));

        return "win-"
            + Convert.ToHexString(hash)
                .ToLowerInvariant()
                .Substring(0, 32);
    }

    private static string Base64Url(
        byte[] raw)
    {
        return Convert
            .ToBase64String(raw)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
    }

    private static
        System.Collections.Generic
            .Dictionary<string,string>
        ParseQuery(
            string query)
    {
        var result =
            new System.Collections.Generic
                .Dictionary<string,string>(
                    StringComparer.Ordinal);

        var raw =
            query.TrimStart('?');

        if (raw.Length == 0)
            return result;

        foreach (
            var part
            in raw.Split('&',
                StringSplitOptions
                    .RemoveEmptyEntries))
        {
            var pair =
                part.Split(
                    '=',
                    2);

            var key =
                Uri.UnescapeDataString(
                    pair[0]
                    .Replace("+", " "));

            var value =
                pair.Length == 2
                    ? Uri.UnescapeDataString(
                        pair[1]
                        .Replace("+", " "))
                    : "";

            result[key] =
                value;
        }

        return result;
    }
}










