using System;
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

        var parent = Path.GetDirectoryName(resolvedPath);

        if (!string.IsNullOrWhiteSpace(parent))
        {
            Directory.CreateDirectory(parent);
        }

        await File.WriteAllTextAsync(
            resolvedPath,
            content,
            cancellationToken);

        return new(
            true,
            $"Wrote {resolvedPath}");
    }
}
