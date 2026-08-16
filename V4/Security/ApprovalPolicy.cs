namespace BotConnector.Desktop.V4.Security;

public enum ToolRisk
{
    Read,
    WorkspaceWrite,
    Execute,
    Network,
    RemoteMutation,
    Destructive
}

public enum ApprovalDecision
{
    Allow,
    Ask,
    Deny
}

public sealed class ApprovalPolicy
{
    public ApprovalDecision Evaluate(ToolRisk risk) =>
        risk switch
        {
            ToolRisk.Read           => ApprovalDecision.Allow,
            ToolRisk.WorkspaceWrite => ApprovalDecision.Ask,
            ToolRisk.Execute        => ApprovalDecision.Ask,
            ToolRisk.Network        => ApprovalDecision.Ask,
            ToolRisk.RemoteMutation => ApprovalDecision.Ask,
            ToolRisk.Destructive    => ApprovalDecision.Deny,
            _                       => ApprovalDecision.Deny
        };
}