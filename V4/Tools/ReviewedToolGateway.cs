using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Security;

namespace BotConnector.Desktop.V4.Tools;

public sealed class ReviewedToolGateway
{
    private readonly Dictionary<string,IBotConnectorTool> _tools =
        new(System.StringComparer.OrdinalIgnoreCase);

    private readonly ReviewedApprovalEngine _approval;

    public ReviewedToolGateway(
        ReviewedApprovalEngine approval)
    {
        _approval = approval;
    }

    public void Register(
        IBotConnectorTool tool)
    {
        _tools[tool.Name] = tool;
    }

    public async Task<ToolResult> ExecuteAsync(
        ToolRequest request,
        CancellationToken cancellationToken)
    {
        if (!_tools.TryGetValue(
            request.Name,
            out var tool))
        {
            return new ToolResult(
                false,
                string.Empty,
                $"Unknown tool: {request.Name}");
        }

        var allowed =
            await _approval.AuthorizeToolAsync(
                request.Name,
                request.Arguments,
                cancellationToken);

        if (!allowed)
        {
            return new ToolResult(
                false,
                string.Empty,
                "Action denied by BotConnector policy.");
        }

        return await tool.ExecuteAsync(
            request,
            cancellationToken);
    }
}