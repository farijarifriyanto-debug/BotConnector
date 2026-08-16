using BotConnector.Desktop.V4.Agents;
using BotConnector.Desktop.V4.Mcp;
using BotConnector.Desktop.V4.Remote;
using BotConnector.Desktop.V4.Routing;
using BotConnector.Desktop.V4.Security;

namespace BotConnector.Desktop.V4.Core;

public sealed class V4Runtime
{
    public WorkspaceContext Workspace { get; } = new();

    public ApprovalPolicy Approval { get; } = new();

    public ModelRouter Router { get; } = new();

    public McpRegistry Mcp { get; } = new();

    public SshRuntime Ssh { get; } = new();

    public AgentSupervisor Agents { get; } = new();
}