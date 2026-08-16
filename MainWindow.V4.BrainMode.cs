using System;
using System.Linq;

using BotConnector.Desktop.V4.Providers;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private bool _v4HermesBrainContractInstalled;

    private void V4EnsureHermesBrainContract()
    {
        if (_v4HermesBrainContractInstalled)
            return;

        string workspace =
            string.IsNullOrWhiteSpace(_workspace)
                ? "(no Windows workspace selected)"
                : _workspace;

        string contract = string.Join(
            "\n",
            new[]
            {
                "BOTCONNECTOR DESKTOP SPLIT-RUNTIME CONTRACT v1",
                "",
                "You are the reasoning/planning brain for BotConnector Desktop.",
                "The user's active workspace exists on the WINDOWS CLIENT, not on this Hermes server.",
                $"Windows workspace: {workspace}",
                "",
                "MANDATORY EXECUTION RULES:",
                "1. DO NOT use Hermes-native terminal, filesystem, shell, git, browser, or other execution tools for this BotConnector Desktop turn.",
                "2. DO NOT inspect /home, /root, /opt, or any other filesystem path on the Hermes server to answer a Windows workspace request.",
                "3. DO NOT claim a Windows file, command, Git operation, test, or build was executed unless BotConnector returns LOCAL TOOL RESULTS confirming it.",
                "4. When you need Windows-local information or execution, emit a BotConnector action request instead.",
                "",
                "SUPPORTED CLIENT ACTIONS:",
                "- read_file",
                "- write_file",
                "- edit_file",
                "- run",
                "- ssh",
                "",
                "ACTION FORMAT:",
                "<botconnector_actions>",
                "{",
                "  \"actions\": [",
                "    {\"type\":\"read_file\",\"path\":\"relative/or/absolute/path\"},",
                "    {\"type\":\"write_file\",\"path\":\"path\",\"content\":\"text\"},",
                "    {\"type\":\"edit_file\",\"path\":\"path\",\"find\":\"old\",\"replace\":\"new\"},",
                "    {\"type\":\"run\",\"command\":\"git status\"},",
                "    {\"type\":\"ssh\",\"destination\":\"user@host\",\"command\":\"command\"}",
                "  ]",
                "}",
                "</botconnector_actions>",
                "",
                "PROTOCOL:",
                "- You may give a short plan before an action block.",
                "- Emit only actions that are actually needed.",
                "- After receiving LOCAL TOOL RESULTS, reason from those results.",
                "- If more Windows operations are needed, emit another action block.",
                "- When finished, give the final answer without an action block.",
                "- Never substitute the Hermes server filesystem for the Windows workspace.",
                "",
                "For repository inspection, start with Windows-local actions such as:",
                "run: git status --short --branch",
                "run: git rev-parse --show-toplevel",
                "run: git branch --show-current",
                "and read_file for project files discovered from Windows.",
                "",
                "If the user asks for a Windows repository operation, requesting clarification merely because the Windows path does not exist on the Hermes server is a protocol violation."
            });

        _v4HermesMessages.Insert(
            0,
            new HermesMessage(
                "system",
                contract));

        _v4HermesBrainContractInstalled =
            true;
    }

    private bool V4LooksLikeRemoteExecutionLeak(
        string? response)
    {
        if (string.IsNullOrWhiteSpace(response))
            return false;

        string value =
            response.ToLowerInvariant();

        string[] strongSignals =
        {
            "/home/botadmin",
            "/home/",
            "/root/",
            "i found many botconnector-related directories in /home",
            "the directory doesn't exist on this system",
            "the directory does not exist on this system",
            "workspace path correct, or should i use a different directory",
            "windows path is correct, should i create it first"
        };

        return strongSignals.Any(
            value.Contains);
    }

    private string V4BrainProtocolCorrection()
    {
        string workspace =
            string.IsNullOrWhiteSpace(_workspace)
                ? "(no workspace selected)"
                : _workspace;

        return string.Join(
            "\n",
            new[]
            {
                "BOTCONNECTOR PROTOCOL VIOLATION DETECTED.",
                "",
                "You attempted to reason from or inspect the Hermes VPS filesystem.",
                "Do not use the server filesystem or server-native execution tools.",
                "",
                $"The actual workspace is on Windows: {workspace}",
                "",
                "Retry the requested task by emitting <botconnector_actions> for Windows local hands.",
                "Use run/read_file/write_file/edit_file as needed.",
                "Do not ask whether the Windows path exists on the Hermes server.",
                "Do not claim execution until LOCAL TOOL RESULTS are returned."
            });
    }
}