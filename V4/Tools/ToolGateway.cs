using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Security;

namespace BotConnector.Desktop.V4.Tools;

public sealed record RegisteredTool(
    IBotConnectorTool Tool,
    ToolRisk Risk);

public sealed class ToolGateway
{
    private readonly Dictionary<string,RegisteredTool> _tools =
        new(StringComparer.OrdinalIgnoreCase);

    private readonly ApprovalPolicy _approval;

    public ToolGateway(ApprovalPolicy approval)
    {
        _approval = approval;
    }

    public void Register(
        IBotConnectorTool tool,
        ToolRisk risk)
    {
        _tools[tool.Name] =
            new RegisteredTool(tool, risk);
    }

    public ApprovalDecision DecisionFor(string toolName)
    {
        if (!_tools.TryGetValue(toolName, out var registered))
            return ApprovalDecision.Deny;

        return _approval.Evaluate(registered.Risk);
    }

    public async Task<ToolResult> ExecuteAllowedAsync(
        ToolRequest request,
        CancellationToken cancellationToken)
    {
        if (!_tools.TryGetValue(request.Name, out var registered))
        {
            return new ToolResult(
                false,
                string.Empty,
                $"Unknown tool: {request.Name}");
        }

        var decision = _approval.Evaluate(
            registered.Risk);

        if (decision != ApprovalDecision.Allow)
        {
            return new ToolResult(
                false,
                string.Empty,
                $"Approval required: {decision}");
        }

        return await registered.Tool.ExecuteAsync(
            request,
            cancellationToken);
    }
}