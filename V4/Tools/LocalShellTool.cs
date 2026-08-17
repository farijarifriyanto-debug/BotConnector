using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Core;

namespace BotConnector.Desktop.V4.Tools;

public sealed class LocalShellTool :
    IBotConnectorTool
{
    private readonly WorkspaceContext _workspace;

    public LocalShellTool(
        WorkspaceContext workspace)
    {
        _workspace = workspace
            ?? throw new ArgumentNullException(
                nameof(workspace));
    }

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

        string workingDirectory;

        try
        {
            workingDirectory =
                _workspace.ResolvePath(
                    string.IsNullOrWhiteSpace(cwd)
                        ? "."
                        : cwd);
        }
        catch (InvalidOperationException)
        {
            return new(
                false,
                string.Empty,
                "No active workspace");
        }
        catch (UnauthorizedAccessException)
        {
            return new(
                false,
                string.Empty,
                "Working directory is outside the active workspace");
        }
        catch (ArgumentException)
        {
            return new(
                false,
                string.Empty,
                "Working directory cannot be resolved safely");
        }
        catch (IOException)
        {
            return new(
                false,
                string.Empty,
                "Working directory cannot be resolved safely");
        }
        catch (NotSupportedException)
        {
            return new(
                false,
                string.Empty,
                "Working directory cannot be resolved safely");
        }

        if (!Directory.Exists(workingDirectory))
        {
            return new(
                false,
                string.Empty,
                "Working directory does not exist");
        }

        var psi =
            new ProcessStartInfo
            {
                FileName =
                    "powershell.exe",

                WorkingDirectory =
                    workingDirectory,

                UseShellExecute =
                    false,

                RedirectStandardOutput =
                    true,

                RedirectStandardError =
                    true,

                CreateNoWindow =
                    true
            };

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
