using System;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Remote;

public sealed record SshResult(
    int ExitCode,
    string StandardOutput,
    string StandardError);

public sealed class SshRuntime
{
    public async Task<SshResult> ExecuteAsync(
        string destination,
        string command,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(destination))
            throw new ArgumentException(
                "SSH destination required.",
                nameof(destination));

        var psi = new ProcessStartInfo
        {
            FileName = "ssh.exe",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = false,
            CreateNoWindow = true
        };

        psi.ArgumentList.Add("-o");
        psi.ArgumentList.Add("BatchMode=yes");

        psi.ArgumentList.Add("-o");
        psi.ArgumentList.Add("ConnectTimeout=10");

        psi.ArgumentList.Add("--");
        psi.ArgumentList.Add(destination);
        psi.ArgumentList.Add(command);

        using var process = new Process
        {
            StartInfo = psi
        };

        if (!process.Start())
            throw new InvalidOperationException(
                "Unable to start ssh.exe.");

        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();

        await process.WaitForExitAsync(cancellationToken);

        return new SshResult(
            process.ExitCode,
            await stdoutTask,
            await stderrTask);
    }
}