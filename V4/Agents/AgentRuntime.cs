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
    private readonly ReviewedToolGateway _gateway;

    public AgentRuntime(ReviewedToolGateway gateway)
    {
        _gateway = gateway
            ?? throw new ArgumentNullException(nameof(gateway));
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

            var result = await _gateway.ExecuteAsync(
                action.ToolRequest,
                cancellationToken);

            transcript.Add(
                $"TOOL_RESULT name={action.ToolRequest.Name} success={result.Success}\n" +
                result.Output +
                (string.IsNullOrWhiteSpace(result.Error)
                    ? string.Empty
                    : $"\nERROR={result.Error}"));
        }

        throw new InvalidOperationException(
            $"Agent exceeded MaxIterations={MaxIterations}.");
    }
}
