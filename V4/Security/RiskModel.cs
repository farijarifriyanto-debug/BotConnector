using System;
using System.Collections.Generic;

namespace BotConnector.Desktop.V4.Security;

public enum RiskDecision
{
    Allow,
    Ask,
    Deny
}

public enum RiskCategory
{
    ReadOnly,
    NormalWrite,
    Shell,
    Network,
    GitNormal,
    GitProtectedPush,
    GitForcePush,
    FileDelete,
    DestructiveFileOperation,
    RemoteRead,
    RemoteWrite,
    RemoteSystemMutation,
    CredentialAccess,
    McpRead,
    McpWrite,
    PrivilegeElevation,
    GitResetHard,
    ApprovalBypass,
    Unknown
}

public sealed record RiskAssessment(
    RiskDecision Decision,
    RiskCategory Category,
    string Summary,
    string? Reason = null,
    string? NormalizedCommand = null);

public sealed record ApprovalRequest(
    string ActionId,
    string Title,
    string Description,
    string? Command,
    string? Target,
    RiskCategory Category);

public enum UserApproval
{
    Deny,
    AllowOnce,
    AllowSession
}