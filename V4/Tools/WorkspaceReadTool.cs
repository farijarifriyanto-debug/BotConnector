using System.IO;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Core;

namespace BotConnector.Desktop.V4.Tools;

public sealed class WorkspaceReadTool :
    IBotConnectorTool
{
    private readonly WorkspaceContext _workspace;

    public WorkspaceReadTool(
        WorkspaceContext workspace)
    {
        _workspace = workspace;
    }

    public string Name =>
        "workspace_read";

    public async Task<ToolResult> ExecuteAsync(
        ToolRequest request,
        CancellationToken cancellationToken)
    {
        if (!request.Arguments.TryGetValue(
            "path",
            out var path))
        {
            return new(
                false,
                string.Empty,
                "path is required");
        }

        path = Path.GetFullPath(path);

        if (!File.Exists(path))
        {
            return new(
                false,
                string.Empty,
                "File not found");
        }

        var content =
            await File.ReadAllTextAsync(
                path,
                cancellationToken);

        return new(
            true,
            content);
    }
}