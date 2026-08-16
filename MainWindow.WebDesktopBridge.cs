using System;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private const string DesktopJobBaseUrl =
        "https://botconnector.id/desktop-ai/v1";

    private readonly HttpClient _desktopJobHttp =
        new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(300)
        };

    private DispatcherTimer? _webDesktopJobTimer;
    private bool _webDesktopJobBusy;

    private void StartWebDesktopJobBridge()
    {
        if (_webDesktopJobTimer is not null)
            return;

        _webDesktopJobTimer = new DispatcherTimer
        {
            // Perf: this is a LEGACY cloud (botconnector.id) job-claim poller.
            // 3s was a network call every 3 seconds at idle. Widened to 15s and
            // only started when a desktop cloud token already exists, so normal
            // (Hermes-only, not-signed-in) usage does ZERO polling / cloud calls.
            Interval = TimeSpan.FromSeconds(15)
        };

        _webDesktopJobTimer.Tick += async (_, _) =>
        {
            await PollWebDesktopJobAsync();
        };

        if (V412ShouldRunDesktopBridge &&
            !string.IsNullOrWhiteSpace(GetDesktopAccessToken()))
        {
            _webDesktopJobTimer.Start();
        }
    }

    private string? GetDesktopAccessToken()
    {
        if (!V412ShouldRunDesktopBridge)
        {
            return null;
        }

        _desktopAuth.LoadStored();
        return _desktopAuth.Current?.access_token;
    }

    private async Task<bool> RefreshDesktopSessionAsync(
        CancellationToken cancellationToken = default)
    {
        if (!V412ShouldRunDesktopBridge)
        {
            return false;
        }

        return await _desktopAuth.RefreshAsync(
            cancellationToken);
    }

    private async Task<HttpResponseMessage> SendWebDesktopRequestAsync(
        HttpMethod method,
        string path,
        object? body = null,
        CancellationToken cancellationToken = default)
    {
        async Task<HttpResponseMessage> SendOnceAsync()
        {
            string? accessToken = GetDesktopAccessToken();

            if (string.IsNullOrWhiteSpace(accessToken))
            {
                throw new InvalidOperationException(
                    "BotConnector Desktop sign-in required.");
            }

            var request = new HttpRequestMessage(
                method,
                DesktopJobBaseUrl + path);

            request.Headers.Authorization =
                new AuthenticationHeaderValue(
                    "Bearer",
                    accessToken);

            if (body is not null)
            {
                string json = JsonSerializer.Serialize(body);

                request.Content = new StringContent(
                    json,
                    Encoding.UTF8,
                    "application/json");
            }

            return await _desktopJobHttp.SendAsync(
                request,
                cancellationToken);
        }

        HttpResponseMessage response =
            await SendOnceAsync();

        if (response.StatusCode == HttpStatusCode.Unauthorized)
        {
            response.Dispose();

            bool refreshed =
                await RefreshDesktopSessionAsync(
                    cancellationToken);

            if (!refreshed)
            {
                V412SetBridgeSessionState(
                    false,
                    "Session expired");

                throw new InvalidOperationException(
                    "BotConnector Desktop session expired. Sign in again.");
            }

            V412SetBridgeSessionState(
                true,
                "Signed in");

            response = await SendOnceAsync();
        }

        return response;
    }

    private async Task DesktopJobHeartbeatLoopAsync(
        string jobId,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(
                    TimeSpan.FromSeconds(30),
                    cancellationToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            if (cancellationToken.IsCancellationRequested)
                return;

            try
            {
                using HttpResponseMessage response =
                    await SendWebDesktopRequestAsync(
                        HttpMethod.Post,
                        "/jobs/" +
                        Uri.EscapeDataString(jobId) +
                        "/heartbeat",
                        new { },
                        cancellationToken);

                if (!response.IsSuccessStatusCode)
                    return;
            }
            catch
            {
                return;
            }
        }
    }

    private async Task PollWebDesktopJobAsync()
    {
        if (_webDesktopJobBusy)
            return;

        if (string.IsNullOrWhiteSpace(_workspace) ||
            !System.IO.Directory.Exists(_workspace))
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(GetDesktopAccessToken()))
            return;

        _webDesktopJobBusy = true;

        try
        {
            using HttpResponseMessage response =
                await SendWebDesktopRequestAsync(
                    HttpMethod.Post,
                    "/jobs/claim",
                    new { });

            if (!response.IsSuccessStatusCode)
                return;

            string json =
                await response.Content.ReadAsStringAsync();

            using JsonDocument document =
                JsonDocument.Parse(json);

            if (!document.RootElement.TryGetProperty(
                    "job",
                    out JsonElement job) ||
                job.ValueKind == JsonValueKind.Null)
            {
                return;
            }

            string jobId =
                job.GetProperty("job_id").GetString() ?? "";

            if (string.IsNullOrWhiteSpace(jobId))
                return;

            JsonElement actionJson =
                job.GetProperty("actions");

            string envelope =
                "<botconnector_actions>\n" +
                "{\"actions\":" +
                actionJson.GetRawText() +
                "}\n" +
                "</botconnector_actions>";

            var parsedActions =
                ExtractAgentActions(envelope);

            if (parsedActions is null ||
                parsedActions.Count == 0)
            {
                await ReportWebDesktopFailureAsync(
                    jobId,
                    "No valid Desktop actions.");

                return;
            }

            string localResults;

            using var heartbeatCancellation =
                new CancellationTokenSource();

            Task heartbeatTask =
                DesktopJobHeartbeatLoopAsync(
                    jobId,
                    heartbeatCancellation.Token);

            try
            {
                localResults =
                    await ExecuteAgentActionsAsync(
                        parsedActions);

                RefreshFileTree();
            }
            catch (Exception ex)
            {
                heartbeatCancellation.Cancel();

                try
                {
                    await heartbeatTask;
                }
                catch
                {
                }

                await ReportWebDesktopFailureAsync(
                    jobId,
                    ex.Message);

                return;
            }

            heartbeatCancellation.Cancel();

            try
            {
                await heartbeatTask;
            }
            catch
            {
            }

            if (localResults.Length > 90000)
            {
                localResults =
                    localResults.Substring(0, 90000) +
                    "\n[Desktop result truncated at 90000 characters]";
            }

            using HttpResponseMessage resultResponse =
                await SendWebDesktopRequestAsync(
                    HttpMethod.Post,
                    "/jobs/" +
                    Uri.EscapeDataString(jobId) +
                    "/result",
                    new
                    {
                        result_text = localResults
                    });

            if (!resultResponse.IsSuccessStatusCode)
            {
                string detail =
                    await resultResponse.Content.ReadAsStringAsync();

                throw new InvalidOperationException(
                    "Desktop result rejected: " +
                    resultResponse.StatusCode +
                    " " +
                    detail);
            }
        }
        catch (Exception ex)
        {
            try
            {
                StatusText.Text =
                    "Desktop bridge: " +
                    ex.Message;
            }
            catch
            {
            }
        }
        finally
        {
            _webDesktopJobBusy = false;
        }
    }

    private async Task ReportWebDesktopFailureAsync(
        string jobId,
        string error)
    {
        try
        {
            if (error.Length > 12000)
                error = error.Substring(0, 12000);

            using HttpResponseMessage response =
                await SendWebDesktopRequestAsync(
                    HttpMethod.Post,
                    "/jobs/" +
                    Uri.EscapeDataString(jobId) +
                    "/fail",
                    new
                    {
                        error
                    });
        }
        catch
        {
        }
    }
}
