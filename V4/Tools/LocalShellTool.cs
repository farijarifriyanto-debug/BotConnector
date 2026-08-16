using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Tools;

public sealed class LocalShellTool :
    IBotConnectorTool
{
    public string Name =>
        "local_shell";

    public async Task<ToolResult> ExecuteAsync(
        ToolRequest request,
        CancellationToken cancellationToken)
    {
        if (!request.Arguments.TryGetValue(
            "command",
            out var command))
        {
            return new(
                false,
                string.Empty,
                "command required");
        }

        request.Arguments.TryGetValue(
            "cwd",
            out var cwd);

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

        if (
            !string.IsNullOrWhiteSpace(cwd)
            &&
            Directory.Exists(cwd))
        {
            psi.WorkingDirectory =
                Path.GetFullPath(cwd);
        }

        psi.ArgumentList.Add(
            "-NoLogo");

        psi.ArgumentList.Add(
            "-NoProfile");

        psi.ArgumentList.Add(
            "-NonInteractive");

        psi.ArgumentList.Add(
            "-Command");

        psi.ArgumentList.Add(
            command);

        using var process =
            new Process
            {
                StartInfo = psi
            };

        if (!process.Start())
        {
            return new(
                false,
                string.Empty,
                "Unable to start local shell");
        }

        var stdout =
            process.StandardOutput
                .ReadToEndAsync();

        var stderr =
            process.StandardError
                .ReadToEndAsync();

        await process.WaitForExitAsync(
            cancellationToken);

        return new(
            process.ExitCode == 0,
            await stdout,
            await stderr,
            process.ExitCode);
    }
}