using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Tools;

namespace BotConnector.Desktop.V4.Agents;

public sealed record AgentAction(
    bool Completed,
    string? FinalText,
    ToolRequest? ToolRequest);

public interface IAgentBrain
{
    Task<AgentAction> ContinueAsync(
        IReadOnlyList<string> transcript,
        CancellationToken cancellationToken);
}

public sealed class AgentRuntime
{
    private readonly IReadOnlyDictionary<string,IBotConnectorTool> _tools;

    public AgentRuntime(IEnumerable<IBotConnectorTool> tools)
    {
        var map = new Dictionary<string,IBotConnectorTool>(
            StringComparer.OrdinalIgnoreCase);

        foreach (var tool in tools)
            map[tool.Name] = tool;

        _tools = map;
    }

    public int MaxIterations { get; init; } = 32;

    public async Task<string> RunAsync(
        IAgentBrain brain,
        IList<string> transcript,
        CancellationToken cancellationToken)
    {
        for (var iteration = 1; iteration <= MaxIterations; iteration++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var action = await brain.ContinueAsync(
                new List<string>(transcript),
                cancellationToken);

            if (action.Completed)
                return action.FinalText ?? string.Empty;

            if (action.ToolRequest is null)
                throw new InvalidOperationException(
                    "Agent returned neither completion nor tool request.");

            if (!_tools.TryGetValue(
                action.ToolRequest.Name,
                out var tool))
            {
                transcript.Add(
                    $"TOOL_ERROR unknown_tool={action.ToolRequest.Name}");

                continue;
            }

            var result = await tool.ExecuteAsync(
                action.ToolRequest,
                cancellationToken);

            transcript.Add(
                $"TOOL_RESULT name={tool.Name} success={result.Success}\n" +
                result.Output +
                (string.IsNullOrWhiteSpace(result.Error)
                    ? string.Empty
                    : $"\nERROR={result.Error}"));
        }

        throw new InvalidOperationException(
            $"Agent exceeded MaxIterations={MaxIterations}.");
    }
}