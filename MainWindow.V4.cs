using BotConnector.Desktop.V4.Core;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private readonly V4RuntimeHost _v4 =
        new();

    internal V4RuntimeHost V4 =>
        _v4;

    internal void V4SetWorkspace(
        string path,
        string? repositoryRoot = null,
        string? branch = null,
        string? worktree = null)
    {
        _v4.Runtime.Workspace.SetWorkspace(
            path,
            repositoryRoot,
            branch,
            worktree);
    }

    internal void V4SetConversation(
        string? conversationId)
    {
        _v4.Runtime.Workspace.SetConversation(
            conversationId);
    }

    internal long V4WorkspaceGeneration =>
        _v4.Runtime.Workspace.Generation;
}