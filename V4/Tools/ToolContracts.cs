using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Tools;

public sealed record ToolRequest(
    string Name,
    IReadOnlyDictionary<string,string> Arguments);

public sealed record ToolResult(
    bool Success,
    string Output,
    string? Error = null,
    int? ExitCode = null);

public interface IBotConnectorTool
{
    string Name { get; }

    Task<ToolResult> ExecuteAsync(
        ToolRequest request,
        CancellationToken cancellationToken);
}