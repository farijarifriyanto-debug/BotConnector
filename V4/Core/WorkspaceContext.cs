using System;
using System.IO;
using System.Threading;

namespace BotConnector.Desktop.V4.Core;

public sealed class WorkspaceContext
{
    private readonly object _sync = new();

    public string? RootPath { get; private set; }
    public string? RepositoryRoot { get; private set; }
    public string? GitBranch { get; private set; }
    public string? WorktreePath { get; private set; }
    public string? ConversationId { get; private set; }
    public string? ActiveAgentId { get; private set; }

    public long Generation { get; private set; }

    public event EventHandler? Changed;

    public void SetWorkspace(
        string rootPath,
        string? repositoryRoot = null,
        string? gitBranch = null,
        string? worktreePath = null)
    {
        if (string.IsNullOrWhiteSpace(rootPath))
            throw new ArgumentException("Workspace path is required.", nameof(rootPath));

        var normalized = Path.GetFullPath(rootPath);

        lock (_sync)
        {
            RootPath = normalized;
            RepositoryRoot = repositoryRoot;
            GitBranch = gitBranch;
            WorktreePath = worktreePath;
            ConversationId = null;
            ActiveAgentId = null;
            Generation++;
        }

        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void SetConversation(string? conversationId)
    {
        lock (_sync)
        {
            ConversationId = conversationId;
            Generation++;
        }

        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void SetActiveAgent(string? agentId)
    {
        lock (_sync)
        {
            ActiveAgentId = agentId;
            Generation++;
        }

        Changed?.Invoke(this, EventArgs.Empty);
    }

    public bool IsWithinWorkspace(string path)
    {
        string? root;

        lock (_sync)
            root = RootPath;

        if (string.IsNullOrWhiteSpace(root))
            return false;

        var rootFull = Path.GetFullPath(root)
            .TrimEnd(Path.DirectorySeparatorChar) +
            Path.DirectorySeparatorChar;

        var target = Path.GetFullPath(path);

        return target.StartsWith(
            rootFull,
            StringComparison.OrdinalIgnoreCase);
    }
}