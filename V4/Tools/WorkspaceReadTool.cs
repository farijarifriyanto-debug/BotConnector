using System;
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

        string resolvedPath;
        try
        {
            resolvedPath = _workspace.ResolvePath(path);
        }
        catch (ArgumentException)
        {
            return new(
                false,
                string.Empty,
                "Path is outside the active workspace");
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
                "Path is outside the active workspace");
        }
        catch (IOException)
        {
            return new(
                false,
                string.Empty,
                "Path cannot be resolved safely");
        }

        if (!File.Exists(resolvedPath))
        {
            return new(
                false,
                string.Empty,
                "File not found");
        }

        var content =
            await File.ReadAllTextAsync(
                resolvedPath,
                cancellationToken);

        return new(
            true,
            content);
    }
}