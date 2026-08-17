using System;
using System.Collections.Generic;
using System.Net.Http;
using BotConnector.Desktop.V4.Agents;
using BotConnector.Desktop.V4.Providers;
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

    public AgentRuntime Agent { get; }

    private readonly HttpClient _cloudHttpClient = new();

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
            new LocalShellTool(Runtime.Workspace));

        Tools.Register(
            new SshCommandTool(
                Runtime.Ssh));

        Agent =
            new AgentRuntime(
                Tools);
    }

    public CloudAiOrchestratorBrain CreateCloudCodingBrain()
    {
        var baseUrl = Environment.GetEnvironmentVariable("BOTCONNECTOR_CLOUD_ORCHESTRATOR_BASE_URL");
        var model = Environment.GetEnvironmentVariable("BOTCONNECTOR_CLOUD_ORCHESTRATOR_MODEL");
        var apiKey = Environment.GetEnvironmentVariable("BOTCONNECTOR_CLOUD_ORCHESTRATOR_API_KEY");

        if (string.IsNullOrWhiteSpace(baseUrl))
        {
            throw new InvalidOperationException(
                "Cloud orchestrator configuration error: BOTCONNECTOR_CLOUD_ORCHESTRATOR_BASE_URL is required.");
        }

        if (string.IsNullOrWhiteSpace(model))
        {
            throw new InvalidOperationException(
                "Cloud orchestrator configuration error: BOTCONNECTOR_CLOUD_ORCHESTRATOR_MODEL is required.");
        }

        var client = new CloudAiOrchestratorClient(
            _cloudHttpClient,
            apiKey,
            baseUrl);

        var tools = new List<ChatTool>
        {
            CreateWorkspaceReadTool(client),
            CreateWorkspaceWriteTool(client),
            CreateLocalShellTool(client),
            CreateSshCommandTool(client)
        };

        return new CloudAiOrchestratorBrain(
            client,
            model,
            tools);
    }

    private ChatTool CreateWorkspaceReadTool(
        CloudAiOrchestratorClient client)
    {
        var parameters = new Dictionary<string, FunctionParameter>
        {
            ["path"] = new FunctionParameter
            {
                Type = "string",
                Description = "Path to the file to read inside the active Windows workspace"
            }
        };

        return client.CreateFunctionTool(
            "workspace_read",
            "Read a text file inside the active Windows workspace.",
            parameters,
            new List<string> { "path" });
    }

    private ChatTool CreateWorkspaceWriteTool(
        CloudAiOrchestratorClient client)
    {
        var parameters = new Dictionary<string, FunctionParameter>
        {
            ["path"] = new FunctionParameter
            {
                Type = "string",
                Description = "Path to the file to create or replace inside the active Windows workspace"
            },
            ["content"] = new FunctionParameter
            {
                Type = "string",
                Description = "Content to write to the file"
            }
        };

        return client.CreateFunctionTool(
            "workspace_write",
            "Create or replace a text file inside the active Windows workspace.",
            parameters,
            new List<string> { "path", "content" });
    }

    private ChatTool CreateLocalShellTool(
        CloudAiOrchestratorClient client)
    {
        var parameters = new Dictionary<string, FunctionParameter>
        {
            ["command"] = new FunctionParameter
            {
                Type = "string",
                Description = "PowerShell command to execute"
            },
            ["cwd"] = new FunctionParameter
            {
                Type = "string",
                Description = "Working directory constrained to the active Windows workspace. Optional.",
                Enum = null
            }
        };

        return client.CreateFunctionTool(
            "local_shell",
            "Run a PowerShell command with its working directory constrained to the active Windows workspace. Execution remains subject to the reviewed security gateway.",
            parameters,
            new List<string> { "command" });
    }

    private ChatTool CreateSshCommandTool(
        CloudAiOrchestratorClient client)
    {
        var parameters = new Dictionary<string, FunctionParameter>
        {
            ["destination"] = new FunctionParameter
            {
                Type = "string",
                Description = "SSH destination to connect to"
            },
            ["command"] = new FunctionParameter
            {
                Type = "string",
                Description = "Command to execute on the remote destination"
            }
        };

        return client.CreateFunctionTool(
            "ssh_command",
            "Run a command on an explicitly selected SSH destination. Execution remains subject to the reviewed security gateway.",
            parameters,
            new List<string> { "destination", "command" });
    }
}