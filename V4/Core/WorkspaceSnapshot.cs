namespace BotConnector.Desktop.V4.Core;

public sealed record WorkspaceSnapshot(
    string? RootPath,
    string? RepositoryRoot,
    string? GitBranch,
    string? WorktreePath,
    string? ConversationId,
    string? ActiveAgentId,
    long Generation);