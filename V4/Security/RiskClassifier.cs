using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

namespace BotConnector.Desktop.V4.Security;

public sealed class RiskClassifier
{
    private static readonly string[] ProtectedBranches =
    {
        "main",
        "master",
        "production",
        "prod",
        "release"
    };

    private static readonly string[] ElevationPatterns =
    {
        "runas.exe",
        " runas ",
        "-verb runas",
        "verb runas",
        "start-process"
    };

    public RiskAssessment ClassifyCommand(
        string? command,
        bool remote = false)
    {
        var c = CommandNormalizer.Lower(command);

        if (string.IsNullOrWhiteSpace(c))
        {
            return new(
                RiskDecision.Allow,
                RiskCategory.Shell,
                "Empty command",
                NormalizedCommand: c);
        }

        // ----------------------------------------------------
        // HARD DENY: git reset --hard
        // ----------------------------------------------------

        if (Regex.IsMatch(
            c,
            @"(^|\s)git(\s+-c\s+\S+)*(\s+-c\s+\S+)*.*\sreset\s+.*--hard(\s|$)"))
        {
            return new(
                RiskDecision.Deny,
                RiskCategory.GitResetHard,
                "git reset --hard is blocked",
                "Hard deny policy",
                c);
        }

        if (c.Contains("git reset --hard"))
        {
            return new(
                RiskDecision.Deny,
                RiskCategory.GitResetHard,
                "git reset --hard is blocked",
                "Hard deny policy",
                c);
        }

        // ----------------------------------------------------
        // Windows privilege elevation HARD DENY locally.
        // Remote sudo is ASK, because VPS mutation may be valid.
        // ----------------------------------------------------

        if (!remote)
        {
            if (
                c.Contains("-verb runas") ||
                c.Contains("verb runas") ||
                Regex.IsMatch(c, @"(^|\s)runas(\.exe)?(\s|$)")
            )
            {
                return new(
                    RiskDecision.Deny,
                    RiskCategory.PrivilegeElevation,
                    "Windows privilege elevation blocked",
                    "Admin elevation is disabled",
                    c);
            }
        }

        if (remote &&
            Regex.IsMatch(c, @"(^|\s)sudo(\s|$)"))
        {
            return new(
                RiskDecision.Ask,
                RiskCategory.RemoteSystemMutation,
                "Remote privileged command",
                "Remote sudo requires review",
                c);
        }

        // ----------------------------------------------------
        // GIT
        // ----------------------------------------------------

        if (Regex.IsMatch(c, @"(^|\s)git(\s|$)"))
        {
            if (
                c.Contains(" push ") ||
                c.StartsWith("git push")
            )
            {
                if (
                    c.Contains("--force") ||
                    c.Contains(" -f ") ||
                    c.EndsWith(" -f")
                )
                {
                    return new(
                        RiskDecision.Ask,
                        RiskCategory.GitForcePush,
                        "Git force push",
                        "Force push requires approval",
                        c);
                }

                foreach (var branch in ProtectedBranches)
                {
                    if (Regex.IsMatch(
                        c,
                        $@"\b{Regex.Escape(branch)}\b"))
                    {
                        return new(
                            RiskDecision.Ask,
                            RiskCategory.GitProtectedPush,
                            $"Push to protected branch '{branch}'",
                            "Protected/default branch requires approval",
                            c);
                    }
                }

                return new(
                    RiskDecision.Allow,
                    RiskCategory.GitNormal,
                    "Normal git push",
                    "Automatic push enabled",
                    c);
            }

            return new(
                RiskDecision.Allow,
                RiskCategory.GitNormal,
                "Normal Git operation",
                NormalizedCommand: c);
        }

        // ----------------------------------------------------
        // DESTRUCTIVE FILE COMMANDS
        // ----------------------------------------------------

        if (
            Regex.IsMatch(
                c,
                @"remove-item.*-recurse") ||
            Regex.IsMatch(
                c,
                @"(^|\s)(rmdir|rd)\s+.*(/s|-r|--recursive)") ||
            Regex.IsMatch(
                c,
                @"(^|\s)rm\s+.*(-rf|-fr|--recursive)") ||
            c.Contains("del /s")
        )
        {
            return new(
                RiskDecision.Ask,
                RiskCategory.DestructiveFileOperation,
                "Recursive/destructive file operation",
                "Destructive filesystem operation requires approval",
                c);
        }

        // ----------------------------------------------------
        // VPS / SYSTEM MUTATION
        // ----------------------------------------------------

        if (remote)
        {
            string[] systemMutation =
            {
                "systemctl restart",
                "systemctl stop",
                "systemctl disable",
                "systemctl enable",
                "docker stop",
                "docker rm",
                "docker compose down",
                "nginx -s",
                "ufw ",
                "iptables ",
                "nft "
            };

            if (systemMutation.Any(c.Contains))
            {
                return new(
                    RiskDecision.Ask,
                    RiskCategory.RemoteSystemMutation,
                    "Remote system/service mutation",
                    "Server mutation requires review",
                    c);
            }
        }

        return new(
            RiskDecision.Allow,
            remote
                ? RiskCategory.RemoteWrite
                : RiskCategory.Shell,
            remote
                ? "Normal remote command"
                : "Normal local command",
            NormalizedCommand: c);
    }

    public RiskAssessment ClassifyTool(
        string toolName,
        IReadOnlyDictionary<string,string> arguments)
    {
        var name = toolName?.Trim().ToLowerInvariant()
                   ?? string.Empty;

        if (name.Contains("read") ||
            name.Contains("search") ||
            name.Contains("list"))
        {
            return new(
                RiskDecision.Allow,
                name.StartsWith("mcp_")
                    ? RiskCategory.McpRead
                    : RiskCategory.ReadOnly,
                "Read-only operation");
        }

        if (name == "workspace_write" ||
            name == "file_write" ||
            name == "apply_patch")
        {
            return new(
                RiskDecision.Allow,
                RiskCategory.NormalWrite,
                "Normal file write");
        }

        if (name == "ssh_command")
        {
            arguments.TryGetValue(
                "command",
                out var command);

            return ClassifyCommand(
                command,
                remote: true);
        }

        if (
            name == "shell" ||
            name == "terminal" ||
            name == "local_shell" ||
            name == "run_command"
        )
        {
            arguments.TryGetValue(
                "command",
                out var command);

            return ClassifyCommand(
                command,
                remote: false);
        }

        if (name.Contains("credential") ||
            name.Contains("secret"))
        {
            return new(
                RiskDecision.Ask,
                RiskCategory.CredentialAccess,
                "Credential/secret access",
                "Sensitive data requires approval");
        }

        if (name.StartsWith("mcp_"))
        {
            return new(
                RiskDecision.Ask,
                RiskCategory.McpWrite,
                "MCP action with external side effects",
                "Non-read MCP action requires review");
        }

        return new(
            RiskDecision.Ask,
            RiskCategory.Unknown,
            $"Unclassified action: {toolName}",
            "Unknown operations require review");
    }
}