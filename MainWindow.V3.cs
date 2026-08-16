using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private sealed class V3ProjectPolicy
    {
        public bool workspace_read { get; set; } = true;
        public bool workspace_write { get; set; } = true;

        public bool build_test { get; set; } = true;

        public bool git_read { get; set; } = true;
        public bool git_commit { get; set; } = true;
        public bool git_worktree { get; set; } = true;

        public bool network { get; set; } = false;
        public bool outside_workspace { get; set; } = false;
        public bool admin { get; set; } = false;
    }

    private string
        _v3ParallelAdvisory =
            "";

    private bool
        _v3ValidationRunning;

    private CancellationTokenSource?
        _v3AdvisorCancellation;



    private string V3Root =>
        Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "BotConnector",
            "DesktopV3");


    private string V3WorkspaceKey()
    {
        string source =
            (_workspace ?? "no-workspace")
                .ToLowerInvariant();

        using var sha =
            SHA256.Create();

        byte[] hash =
            sha.ComputeHash(
                Encoding.UTF8.GetBytes(
                    source));

        return Convert
            .ToHexString(hash)
            .Substring(0,24)
            .ToLowerInvariant();
    }


    private string V3PolicyPath()
    {
        return Path.Combine(
            V3Root,
            "Policies",
            V3WorkspaceKey() +
            ".json");
    }


    private string V3WorktreeRoot()
    {
        return Path.Combine(
            V3Root,
            "Worktrees",
            V3WorkspaceKey());
    }


    private V3ProjectPolicy V3LoadPolicy()
    {
        string path =
            V3PolicyPath();

        Directory.CreateDirectory(
            Path.GetDirectoryName(
                path)!);

        if (!File.Exists(path))
        {
            var initial =
                new V3ProjectPolicy();

            File.WriteAllText(
                path,
                JsonSerializer.Serialize(
                    initial,
                    new JsonSerializerOptions
                    {
                        WriteIndented =
                            true
                    }),
                new UTF8Encoding(false));

            return initial;
        }

        try
        {
            return
                JsonSerializer.Deserialize<V3ProjectPolicy>(
                    File.ReadAllText(path))
                ??
                new V3ProjectPolicy();
        }
        catch
        {
            return
                new V3ProjectPolicy();
        }
    }


    private string V3PolicySummary()
    {
        V3ProjectPolicy p =
            V3LoadPolicy();

        return
            "workspace_read=" +
            p.workspace_read +
            "\nworkspace_write=" +
            p.workspace_write +
            "\nbuild_test=" +
            p.build_test +
            "\ngit_read=" +
            p.git_read +
            "\ngit_commit=" +
            p.git_commit +
            "\ngit_worktree=" +
            p.git_worktree +
            "\nnetwork=" +
            p.network +
            "\noutside_workspace=" +
            p.outside_workspace +
            "\nadmin=" +
            p.admin;
    }


    private string V3ReadInstructionFile(
        string path,
        int maxChars)
    {
        try
        {
            string text =
                File.ReadAllText(
                    path);

            if (
                text.Length >
                maxChars)
            {
                return
                    text.Substring(
                        0,
                        maxChars) +
                    "\n[TRUNCATED]";
            }

            return text;
        }
        catch (
            Exception ex)
        {
            return
                "[unable to read: " +
                ex.Message +
                "]";
        }
    }


    private string V3ProjectInstructions()
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
        {
            return
                "(no project instructions)";
        }

        var builder =
            new StringBuilder();

        int total =
            0;

        const int totalLimit =
            60000;

        void AddFile(
            string file)
        {
            if (
                total >=
                totalLimit ||
                !File.Exists(file))
            {
                return;
            }

            string relative =
                Path.GetRelativePath(
                    _workspace,
                    file);

            string text =
                V3ReadInstructionFile(
                    file,
                    16000);

            if (
                total +
                text.Length >
                totalLimit)
            {
                text =
                    text.Substring(
                        0,
                        Math.Max(
                            0,
                            totalLimit -
                            total));
            }

            builder.AppendLine();
            builder.AppendLine(
                "===== " +
                relative +
                " =====");

            builder.AppendLine(
                text);

            total +=
                text.Length;
        }

        AddFile(
            Path.Combine(
                _workspace,
                ".github",
                "copilot-instructions.md"));

        AddFile(
            Path.Combine(
                _workspace,
                "CLAUDE.md"));

        AddFile(
            Path.Combine(
                _workspace,
                "GEMINI.md"));

        AddFile(
            Path.Combine(
                _workspace,
                "AGENTS.md"));

        try
        {
            foreach (
                string file in
                EnumerateWorkspaceFilesSafe(
                    _workspace))
            {
                if (
                    total >=
                    totalLimit)
                {
                    break;
                }

                if (
                    string.Equals(
                        Path.GetFileName(file),
                        "AGENTS.md",
                        StringComparison
                            .OrdinalIgnoreCase) &&
                    !string.Equals(
                        file,
                        Path.Combine(
                            _workspace,
                            "AGENTS.md"),
                        StringComparison
                            .OrdinalIgnoreCase))
                {
                    AddFile(
                        file);
                }
            }
        }
        catch
        {
        }

        if (
            builder.Length ==
            0)
        {
            return
                "(no AGENTS.md or project instruction file found)";
        }

        return
            builder.ToString();
    }


    private string V3AugmentUserPrompt(
        string userPrompt)
    {
        var b =
            new StringBuilder();

        b.AppendLine(
            userPrompt);

        b.AppendLine();
        b.AppendLine(
            "=== BOTCONNECTOR V3 AGENT WORKSPACE ===");

        b.AppendLine();
        b.AppendLine(
            "PROJECT INSTRUCTIONS:");

        b.AppendLine(
            V3ProjectInstructions());

        b.AppendLine();
        b.AppendLine(
            "PROJECT PERMISSION POLICY:");

        b.AppendLine(
            V3PolicySummary());

        if (
            !string.IsNullOrWhiteSpace(
                _v3ParallelAdvisory))
        {
            b.AppendLine();
            b.AppendLine(
                "PARALLEL AGENT ADVISORY:");

            b.AppendLine(
                _v3ParallelAdvisory);
        }

        b.AppendLine();
        b.AppendLine(
            "Instruction precedence: when multiple AGENTS.md files apply, " +
            "use the nearest relevant AGENTS.md for the file being changed.");

        b.AppendLine();
        b.AppendLine(
            "Additional V3 action types available in botconnector_actions:");

        b.AppendLine(
            "- git_status");

        b.AppendLine(
            "- git_diff");

        b.AppendLine(
            "- git_commit (put commit message in content)");

        b.AppendLine(
            "- git_worktree_list");

        b.AppendLine(
            "- git_worktree_create (put branch name in path)");

        b.AppendLine(
            "- git_worktree_remove (put worktree leaf name in path)");

        b.AppendLine(
            "- validate");

        b.AppendLine();
        b.AppendLine(
            "Never use git push, force push, reset --hard, arbitrary outside-workspace paths, " +
            "administrator elevation, or network access through these V3 tools.");

        return
            b.ToString();
    }


    private async Task<string>
        V3RunOneAdvisorAsync(
            string role,
            string task,
            CancellationToken cancellationToken)
    {
        try
        {
            string prompt =
                "You are the " +
                role +
                " advisor inside BotConnector V3. " +
                "Analyze only; do not emit botconnector_actions and do not attempt local writes. " +
                "Be concrete and concise. " +
                "Consider project instructions if provided below.\n\n" +
                "TASK:\n" +
                task +
                "\n\nPROJECT INSTRUCTIONS:\n" +
                V3ProjectInstructions();

            var response =
                await _desktopAuth
                    .SendChatAsync(
                        prompt,
                        null,
                        cancellationToken);

            return
                "[" +
                role +
                "]\n" +
                ExtractAssistantText(
                    response.result);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            return
                "[" +
                role +
                " unavailable: " +
                ex.Message +
                "]";
        }
    }


    private async Task<string>
        V3RunParallelAdvisorsAsync(
            string task,
            CancellationToken cancellationToken)
    {
        Task<string>[] agents =
        {
            V3RunOneAdvisorAsync(
                "Planner",
                task,
                cancellationToken),

            V3RunOneAdvisorAsync(
                "Coder-A",
                task,
                cancellationToken),

            V3RunOneAdvisorAsync(
                "Reviewer",
                task,
                cancellationToken),

            V3RunOneAdvisorAsync(
                "Tester",
                task,
                cancellationToken)
        };

        string[] results =
            await Task.WhenAll(
                agents);

        return
            string.Join(
                "\n\n",
                results);
    }


    private string? V3FindGit()
    {
        string? path =
            Environment.GetEnvironmentVariable(
                "PATH");

        if (
            string.IsNullOrWhiteSpace(
                path))
        {
            return null;
        }

        foreach (
            string folder in
            path.Split(
                Path.PathSeparator))
        {
            try
            {
                string candidate =
                    Path.Combine(
                        folder.Trim(),
                        "git.exe");

                if (
                    File.Exists(
                        candidate))
                {
                    return
                        candidate;
                }
            }
            catch
            {
            }
        }

        return null;
    }


    private async Task<string>
        V3RunGitAsync(
            params string[] args)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
        {
            return
                "Git unavailable: open a workspace first.";
        }

        string? git =
            V3FindGit();

        if (
            string.IsNullOrWhiteSpace(
                git))
        {
            return
                "git.exe not found.";
        }

        var psi =
            new ProcessStartInfo
            {
                FileName =
                    git,

                WorkingDirectory =
                    _workspace,

                UseShellExecute =
                    false,

                RedirectStandardOutput =
                    true,

                RedirectStandardError =
                    true,

                CreateNoWindow =
                    true
            };

        foreach (
            string arg in
            args)
        {
            psi.ArgumentList.Add(
                arg);
        }

        using Process? process =
            Process.Start(
                psi);

        if (
            process == null)
        {
            return
                "Failed to start git.";
        }

        Task<string> stdout =
            process.StandardOutput
                .ReadToEndAsync();

        Task<string> stderr =
            process.StandardError
                .ReadToEndAsync();

        await process
            .WaitForExitAsync();

        string output =
            (await stdout) +
            (await stderr);

        return
            "$ git " +
            string.Join(
                " ",
                args) +
            "\nEXIT=" +
            process.ExitCode +
            "\n" +
            output.Trim();
    }


    private async Task<bool>
        V3IsGitRepositoryAsync()
    {
        string output =
            await V3RunGitAsync(
                "rev-parse",
                "--is-inside-work-tree");

        return
            output.Contains(
                "true",
                StringComparison
                    .OrdinalIgnoreCase) &&
            output.Contains(
                "EXIT=0",
                StringComparison.Ordinal);
    }


    private static string
        V3SafeBranch(
            string? requested)
    {
        string value =
            string.IsNullOrWhiteSpace(
                requested)
                ? "botconnector/" +
                  DateTime.UtcNow
                      .ToString(
                          "yyyyMMdd-HHmmss")
                : requested.Trim();

        if (
            value.Contains("..") ||
            value.StartsWith("-") ||
            value.IndexOfAny(
                new[]
                {
                    '\\',
                    ':',
                    '*',
                    '?',
                    '"',
                    '<',
                    '>',
                    '|',
                    ' '
                }) >= 0)
        {
            throw new InvalidOperationException(
                "Invalid worktree branch name.");
        }

        return value;
    }


    private static string
        V3WorktreeLeaf(
            string branch)
    {
        var b =
            new StringBuilder();

        foreach (
            char c in branch)
        {
            if (
                char.IsLetterOrDigit(c) ||
                c == '-' ||
                c == '_' ||
                c == '.')
            {
                b.Append(c);
            }
            else
            {
                b.Append('_');
            }
        }

        string leaf =
            b.ToString();

        if (
            string.IsNullOrWhiteSpace(
                leaf))
        {
            leaf =
                "worktree";
        }

        return leaf;
    }


    private async Task<string>
        V3ExecuteGitActionAsync(
            string type,
            string? path,
            string? content)
    {
        V3ProjectPolicy policy =
            V3LoadPolicy();

        if (
            !await V3IsGitRepositoryAsync())
        {
            return
                type +
                ": workspace is not a Git repository.";
        }

        if (
            type ==
            "git_status")
        {
            if (!policy.git_read)
                return "git_status denied by project policy.";

            return await V3RunGitAsync(
                "status",
                "--short",
                "--branch");
        }

        if (
            type ==
            "git_diff")
        {
            if (!policy.git_read)
                return "git_diff denied by project policy.";

            return await V3RunGitAsync(
                "diff",
                "--",
                ".");
        }

        if (
            type ==
            "git_commit")
        {
            if (!policy.git_commit)
                return "git_commit denied by project policy.";

            string message =
                string.IsNullOrWhiteSpace(
                    content)
                    ? "BotConnector AI changes"
                    : content.Trim();

            if (
                message.Length >
                200)
            {
                message =
                    message.Substring(
                        0,
                        200);
            }

            string add =
                await V3RunGitAsync(
                    "add",
                    "-A");

            if (
                !add.Contains(
                    "EXIT=0",
                    StringComparison.Ordinal))
            {
                return add;
            }

            return
                add +
                "\n\n" +
                await V3RunGitAsync(
                    "commit",
                    "-m",
                    message);
        }

        if (
            type ==
            "git_worktree_list")
        {
            if (!policy.git_read)
                return "git_worktree_list denied by project policy.";

            return await V3RunGitAsync(
                "worktree",
                "list",
                "--porcelain");
        }

        if (
            type ==
            "git_worktree_create")
        {
            if (!policy.git_worktree)
                return "git_worktree_create denied by project policy.";

            string branch =
                V3SafeBranch(
                    path);

            string root =
                V3WorktreeRoot();

            Directory.CreateDirectory(
                root);

            string destination =
                Path.Combine(
                    root,
                    V3WorktreeLeaf(
                        branch));

            if (
                Directory.Exists(
                    destination))
            {
                return
                    "Worktree already exists: " +
                    destination;
            }

            string output =
                await V3RunGitAsync(
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    destination,
                    "HEAD");

            return
                output +
                "\nWORKTREE=" +
                destination;
        }

        if (
            type ==
            "git_worktree_remove")
        {
            if (!policy.git_worktree)
                return "git_worktree_remove denied by project policy.";

            if (
                string.IsNullOrWhiteSpace(
                    path))
            {
                return
                    "git_worktree_remove requires path leaf.";
            }

            string root =
                Path.GetFullPath(
                    V3WorktreeRoot());

            string candidate =
                Path.GetFullPath(
                    Path.Combine(
                        root,
                        path));

            string prefix =
                root.TrimEnd(
                    Path.DirectorySeparatorChar) +
                Path.DirectorySeparatorChar;

            if (
                !candidate.StartsWith(
                    prefix,
                    StringComparison
                        .OrdinalIgnoreCase))
            {
                return
                    "Worktree path denied.";
            }

            return
                await V3RunGitAsync(
                    "worktree",
                    "remove",
                    candidate);
        }

        return
            "Unknown V3 Git action: " +
            type;
    }


    private async Task<string>
        V3RunSandboxCommandAsync(
            string command)
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace))
        {
            return
                "No workspace.";
        }

        string cmdArgs =
            "/d /s /c " +
            command;

        string args64 =
            Convert.ToBase64String(
                Encoding.UTF8.GetBytes(
                    cmdArgs));

        return
            await RunPowerShellAsync(
                new[]
                {
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    BrokerPath,
                    "run",
                    "-Workspace",
                    _workspace,
                    "-Mode",
                    "offline",
                    "-Exe",
                    Path.Combine(
                        Environment.GetFolderPath(
                            Environment.SpecialFolder.Windows),
                        "System32",
                        "cmd.exe"),
                    "-ArgumentsB64",
                    args64
                });
    }


    private string?
        V3DetectValidationCommand()
    {
        if (
            string.IsNullOrWhiteSpace(
                _workspace) ||
            !Directory.Exists(
                _workspace))
        {
            return null;
        }

        if (
            Directory
                .EnumerateFiles(
                    _workspace,
                    "*.sln",
                    SearchOption.TopDirectoryOnly)
                .Any() ||
            Directory
                .EnumerateFiles(
                    _workspace,
                    "*.csproj",
                    SearchOption.TopDirectoryOnly)
                .Any())
        {
            return
                "dotnet build --nologo";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "package.json")))
        {
            return
                "npm test --if-present";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "pyproject.toml")) ||
            File.Exists(
                Path.Combine(
                    _workspace,
                    "pytest.ini")))
        {
            return
                "python -m pytest -q";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "go.mod")))
        {
            return
                "go test ./...";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "Cargo.toml")))
        {
            return
                "cargo test";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "pom.xml")))
        {
            return
                "mvn test -q";
        }

        if (
            File.Exists(
                Path.Combine(
                    _workspace,
                    "gradlew.bat")))
        {
            return
                "gradlew.bat test";
        }

        return null;
    }


    private async Task<string>
        V3RunAutoValidationAsync()
    {
        if (_v3ValidationRunning)
        {
            return
                "";
        }

        V3ProjectPolicy policy =
            V3LoadPolicy();

        if (!policy.build_test)
        {
            return
                "AUTO VALIDATION: disabled by project policy.";
        }

        string? command =
            V3DetectValidationCommand();

        if (
            string.IsNullOrWhiteSpace(
                command))
        {
            if (
                await V3IsGitRepositoryAsync())
            {
                string diffCheck =
                    await V3RunGitAsync(
                        "diff",
                        "--check");

                return
                    "AUTO VALIDATION:\n" +
                    diffCheck;
            }

            return
                "AUTO VALIDATION: no supported project validation command detected.";
        }

        _v3ValidationRunning =
            true;

        try
        {
            string output =
                await V3RunSandboxCommandAsync(
                    command);

            return
                "AUTO VALIDATION COMMAND: " +
                command +
                "\n" +
                output;
        }
        catch (
            Exception ex)
        {
            return
                "AUTO VALIDATION ERROR: " +
                ex.Message;
        }
        finally
        {
            _v3ValidationRunning =
                false;
        }
    }


    private async void V3_GitStatus_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        AppendTerminal(
            "[V3 Git Status]");

        AppendTerminal(
            await V3ExecuteGitActionAsync(
                "git_status",
                null,
                null));
    }


    private async void V3_GitDiff_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        AppendTerminal(
            "[V3 Git Diff]");

        AppendTerminal(
            await V3ExecuteGitActionAsync(
                "git_diff",
                null,
                null));
    }


    private async void V3_Validate_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        V2ActivityText.Text =
            "Validating…";

        try
        {
            AppendTerminal(
                "[V3 Validate]");

            AppendTerminal(
                await V3RunAutoValidationAsync());
        }
        finally
        {
            V2ActivityText.Text =
                "";
        }
    }


    private async void V3_Commit_Click(
        object sender,
        System.Windows.RoutedEventArgs e)
    {
        string title =
            _v2CurrentSession?.Title ??
            "changes";

        string message =
            "BotConnector AI: " +
            title;

        AppendTerminal(
            "[V3 Git Commit]");

        AppendTerminal(
            await V3ExecuteGitActionAsync(
                "git_commit",
                null,
                message));

        RefreshFileTree();
    }
}


