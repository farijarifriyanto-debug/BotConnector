using BotConnector.Desktop.V4.Security;
using BotConnector.Desktop.V4.Tools;

namespace BotConnector.Desktop.V4.Core;

public sealed class V4RuntimeHost
{
    public V4Runtime Runtime { get; }

    public RiskClassifier Risk { get; }

    public SessionApprovalStore SessionApprovals { get; }

    public ReviewedApprovalEngine ApprovalEngine { get; }

    public ReviewedToolGateway Tools { get; }

    public V4RuntimeHost()
    {
        Runtime =
            new V4Runtime();

        Risk =
            new RiskClassifier();

        SessionApprovals =
            new SessionApprovalStore();

        ApprovalEngine =
            new ReviewedApprovalEngine(
                Risk,
                SessionApprovals,
                new WpfApprovalPrompt());

        Tools =
            new ReviewedToolGateway(
                ApprovalEngine);

        Tools.Register(
            new WorkspaceReadTool(
                Runtime.Workspace));

        Tools.Register(
            new WorkspaceWriteTool(
                Runtime.Workspace));

        Tools.Register(
            new LocalShellTool());

        Tools.Register(
            new SshCommandTool(
                Runtime.Ssh));
    }
}