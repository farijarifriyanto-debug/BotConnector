using System.IO;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Core;

namespace BotConnector.Desktop.V4.Tools;

public sealed class WorkspaceWriteTool :
    IBotConnectorTool
{
    private readonly WorkspaceContext _workspace;

    public WorkspaceWriteTool(
        WorkspaceContext workspace)
    {
        _workspace = workspace;
    }

    public string Name =>
        "workspace_write";

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

        if (!request.Arguments.TryGetValue(
            "content",
            out var content))
        {
            return new(
                false,
                string.Empty,
                "content is required");
        }

        path = Path.GetFullPath(path);

        var parent =
            Path.GetDirectoryName(path);

        if (!string.IsNullOrWhiteSpace(parent))
        {
            Directory.CreateDirectory(parent);
        }

        await File.WriteAllTextAsync(
            path,
            content,
            cancellationToken);

        return new(
            true,
            $"Wrote {path}");
    }
}