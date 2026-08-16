using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Remote;

namespace BotConnector.Desktop.V4.Tools;

public sealed class SshCommandTool :
    IBotConnectorTool
{
    private readonly SshRuntime _ssh;

    public SshCommandTool(SshRuntime ssh)
    {
        _ssh = ssh;
    }

    public string Name => "ssh_command";

    public async Task<ToolResult> ExecuteAsync(
        ToolRequest request,
        CancellationToken cancellationToken)
    {
        if (!request.Arguments.TryGetValue(
            "destination",
            out var destination))
        {
            return new ToolResult(
                false,
                string.Empty,
                "destination required");
        }

        if (!request.Arguments.TryGetValue(
            "command",
            out var command))
        {
            return new ToolResult(
                false,
                string.Empty,
                "command required");
        }

        var result = await _ssh.ExecuteAsync(
            destination,
            command,
            cancellationToken);

        return new ToolResult(
            result.ExitCode == 0,
            result.StandardOutput,
            result.StandardError,
            result.ExitCode);
    }
}