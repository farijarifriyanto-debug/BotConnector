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
        try
        {
            ResolvePath(path);
            return true;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
    }

    public string ResolvePath(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("Path cannot be null or empty.", nameof(path));

        if (string.IsNullOrWhiteSpace(RootPath))
            throw new InvalidOperationException("Workspace root is not set.");

        string rootFull;
        string targetFull;
        string rootSnapshot;

        lock (_sync)
        {
            rootSnapshot = RootPath;
            rootFull = Path.GetFullPath(rootSnapshot);
        }

        targetFull = Path.IsPathRooted(path)
            ? Path.GetFullPath(path)
            : Path.GetFullPath(path, rootFull);

        if (!IsDescendantOf(targetFull, rootFull))
        {
            throw new UnauthorizedAccessException($"Path '{path}' is outside the workspace boundary.");
        }

        // Walk path components from the trusted workspace root DOWN toward target
        // The workspace root itself is trusted and is not rejected
        string currentPath = rootSnapshot;
        string relativePath = targetFull.Substring(rootFull.Length).TrimStart(Path.DirectorySeparatorChar);
        string[] targetComponents = string.IsNullOrEmpty(relativePath)
            ? Array.Empty<string>()
            : relativePath.Split(new[] { Path.DirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries);

        // Start from root and build down to target
        foreach (string component in targetComponents)
        {
            currentPath = Path.Combine(currentPath, component);

            // If the component exists, check for reparse points
            if (File.Exists(currentPath) || Directory.Exists(currentPath))
            {
                var attributes = File.GetAttributes(currentPath);
                if ((attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
                {
                    throw new UnauthorizedAccessException($"Reparse point detected at '{currentPath}'.");
                }
            }
            // If component doesn't exist, stop reparse inspection (ancestors already checked)
        }

        // Also check the final target itself if it exists
        if (File.Exists(targetFull) || Directory.Exists(targetFull))
        {
            var attributes = File.GetAttributes(targetFull);
            if ((attributes & FileAttributes.ReparsePoint) == FileAttributes.ReparsePoint)
            {
                throw new UnauthorizedAccessException($"Reparse point detected at '{targetFull}'.");
            }
        }

        return targetFull;
    }

    private bool IsDescendantOf(string path, string root)
    {
        var rootInfo = new DirectoryInfo(root);
        var pathInfo = new DirectoryInfo(path);

        // Check if path equals root (boundary case)
        if (pathInfo.FullName.Equals(rootInfo.FullName, StringComparison.OrdinalIgnoreCase))
            return true;

        while (pathInfo.Parent != null)
        {
            if (pathInfo.FullName.Equals(rootInfo.FullName, StringComparison.OrdinalIgnoreCase))
                return true;
            pathInfo = pathInfo.Parent;
        }

        return false;
    }
}