using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using BotConnector.Desktop.V4.Providers;
using BotConnector.Desktop.V4.Tools;

namespace BotConnector.Desktop.V4.Agents;

/// <summary>
/// Cloud AI Orchestrator Brain implementation that maintains OpenAI-compatible conversation state
/// and manages tool call workflow without executing tools directly.
/// </summary>
public sealed class CloudAiOrchestratorBrain : IAgentBrain
{
    private readonly CloudAiOrchestratorClient _client;
    private readonly string _modelId;
    private readonly IReadOnlyList<ChatTool>? _toolDefinitions;
    private readonly string? _systemPrompt;

    // Internal conversation history maintained by the brain
    private readonly List<ChatMessage> _history = new();

    // Internal state for tracking pending tool calls
    private readonly List<ToolCall> _queuedToolCalls = new();
    private int _currentToolCallIndex = -1;
    private int _transcriptCountAtToolEmission = -1;
    private bool _awaitingToolResult;
    private bool _historyInitialized;

    /// <summary>
    /// Initializes a new instance of CloudAiOrchestratorBrain.
    /// </summary>
    /// <param name="client">Cloud AI Orchestrator client for model inference</param>
    /// <param name="modelId">Model identifier to use for inference</param>
    /// <param name="toolDefinitions">Optional tool definitions for the model</param>
    /// <param name="systemPrompt">Optional system prompt for the conversation</param>
    public CloudAiOrchestratorBrain(
        CloudAiOrchestratorClient client,
        string modelId,
        IReadOnlyList<ChatTool>? toolDefinitions = null,
        string? systemPrompt = null)
    {
        _client = client ?? throw new ArgumentNullException(nameof(client));
        _modelId = modelId ?? throw new ArgumentNullException(nameof(modelId));
        _toolDefinitions = toolDefinitions;
        _systemPrompt = systemPrompt;
    }

    /// <summary>
    /// Continues the agent conversation by either:
    /// - Returning a completed action with final text
    /// - Returning a tool request to execute
    /// - Processing tool results and continuing the conversation
    /// </summary>
    public async Task<AgentAction> ContinueAsync(
        IReadOnlyList<string> transcript,
        CancellationToken cancellationToken)
    {
        // If we're awaiting a tool result, consume exactly one new TOOL_RESULT entry
        if (_awaitingToolResult)
        {
            return await ProcessToolResultAsync(transcript, cancellationToken);
        }

        // Initialize history from transcript exactly once before first model call
        if (!_historyInitialized)
        {
            var initialMessages = ConvertTranscriptToMessages(transcript);
            _history.AddRange(initialMessages);
            _historyInitialized = true;
        }

        // Call model with current history
        return await CallModelAsync(_history, transcript.Count, cancellationToken);
    }

    private async Task<AgentAction> CallModelAsync(
        IReadOnlyList<ChatMessage> messages,
        int transcriptCount,
        CancellationToken cancellationToken)
    {
        // Create chat completion request
        var request = _client.CreateChatCompletionRequest(
            messages,
            _modelId,
            _toolDefinitions);

        // Get response from model
        var response = await _client.GetChatCompletionAsync(request, cancellationToken);

        // Extract the assistant message
        var assistantMessage = response.Choices[0].Message;

        // Append assistant message to history exactly once
        _history.Add(assistantMessage);

        // Case 1: Model returned final assistant content with NO tool calls
        if (string.IsNullOrEmpty(assistantMessage.Content) &&
            (assistantMessage.ToolCalls == null || assistantMessage.ToolCalls.Count == 0))
        {
            return new AgentAction(
                Completed: true,
                FinalText: assistantMessage.Content,
                ToolRequest: null);
        }

        // Case 2: Model returned assistant content WITH tool calls
        if (assistantMessage.ToolCalls != null && assistantMessage.ToolCalls.Count > 0)
        {
            // Queue all tool calls in original order
            _queuedToolCalls.Clear();
            _queuedToolCalls.AddRange(assistantMessage.ToolCalls);
            _currentToolCallIndex = 0;

            // Return the first tool request
            var firstToolCall = _queuedToolCalls[0];
            var toolRequest = ParseToolRequest(firstToolCall);

            // Track that we're awaiting a tool result
            _awaitingToolResult = true;
            _transcriptCountAtToolEmission = transcriptCount;

            return new AgentAction(
                Completed: false,
                FinalText: null,
                ToolRequest: toolRequest);
        }

        // Case 3: Model returned only text content (no tool calls)
        if (!string.IsNullOrEmpty(assistantMessage.Content))
        {
            return new AgentAction(
                Completed: true,
                FinalText: assistantMessage.Content,
                ToolRequest: null);
        }

        // Should not reach here with valid model responses
        throw new InvalidOperationException(
            "Model returned neither content nor tool calls in assistant message.");
    }

    private async Task<AgentAction> ProcessToolResultAsync(
        IReadOnlyList<string> transcript,
        CancellationToken cancellationToken)
    {
        if (!_awaitingToolResult || _currentToolCallIndex < 0 || _queuedToolCalls.Count == 0)
        {
            throw new InvalidOperationException(
                "No pending tool call to process.");
        }

        // Require exactly one NEW TOOL_RESULT entry after the recorded transcript position
        if (transcript.Count != _transcriptCountAtToolEmission + 1)
        {
            throw new InvalidOperationException(
                $"Waiting for tool result but expected exactly one new transcript entry. Expected: {_transcriptCountAtToolEmission + 1}, Actual: {transcript.Count}");
        }

        // Get the new TOOL_RESULT entry (the one after our recorded position)
        var newToolResultEntry = transcript[_transcriptCountAtToolEmission];

        // Validate that this is actually a TOOL_RESULT entry
        if (!newToolResultEntry.StartsWith("TOOL_RESULT ", StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"Expected TOOL_RESULT entry but got: {newToolResultEntry.Substring(0, Math.Min(20, newToolResultEntry.Length))}");
        }

        _transcriptCountAtToolEmission = transcript.Count;

        // Parse the TOOL_RESULT entry
        var toolResultContent = ParseToolResult(newToolResultEntry);

        // Get the pending tool call
        var pendingCall = _queuedToolCalls[_currentToolCallIndex];

        // Create tool message with the ACTUAL tool_call_id from the queued call
        var toolMessage = _client.CreateToolMessage(
            pendingCall.Id,
            toolResultContent);

        // Append the tool message to history
        _history.Add(toolMessage);

        // Mark current tool call as consumed
        _currentToolCallIndex++;

        // Case A: More tool calls remain in the original assistant message
        if (_currentToolCallIndex < _queuedToolCalls.Count)
        {
            var nextToolCall = _queuedToolCalls[_currentToolCallIndex];
            var toolRequest = ParseToolRequest(nextToolCall);

            // Still awaiting another tool result
            _awaitingToolResult = true;
            _transcriptCountAtToolEmission = transcript.Count;

            return new AgentAction(
                Completed: false,
                FinalText: null,
                ToolRequest: toolRequest);
        }

        // Case B: All tool calls completed, call model again with updated history
        _awaitingToolResult = false;
        _queuedToolCalls.Clear();
        _currentToolCallIndex = -1;

        return await CallModelAsync(_history, transcript.Count, cancellationToken);
    }

    private IReadOnlyList<ChatMessage> ConvertTranscriptToMessages(
        IReadOnlyList<string> transcript)
    {
        var messages = new List<ChatMessage>();

        // Add system prompt if provided
        if (_systemPrompt != null)
        {
            messages.Add(_client.CreateSystemMessage(_systemPrompt));
        }

        foreach (var entry in transcript)
        {
            if (entry.StartsWith("TOOL_RESULT ", StringComparison.Ordinal))
            {
                // TOOL_RESULT entries are handled by ProcessToolResultAsync
                // They should not be converted to messages here
                // Skip them to avoid duplicate processing
                continue;
            }
            else if (entry.StartsWith("USER: ", StringComparison.Ordinal))
            {
                messages.Add(_client.CreateUserMessage(
                    entry.Substring(6)));
            }
            else if (entry.StartsWith("ASSISTANT: ", StringComparison.Ordinal))
            {
                messages.Add(_client.CreateAssistantMessage(
                    entry.Substring(11)));
            }
            else
            {
                // Default to user message for backward compatibility
                messages.Add(_client.CreateUserMessage(entry));
            }
        }

        return messages;
    }

    private string ParseToolResult(string toolResultEntry)
    {
        // Parse TOOL_RESULT format: "TOOL_RESULT name={name} success={success}\n{output}"
        var lines = toolResultEntry.Split(new[] { '\n' }, 2);
        var content = lines.Length > 1 ? lines[1] : string.Empty;

        return content;
    }

    private ToolRequest ParseToolRequest(ToolCall toolCall)
    {
        // Validate tool call
        if (string.IsNullOrWhiteSpace(toolCall.Id))
        {
            throw new InvalidOperationException(
                "Tool call is missing required id field.");
        }

        if (string.IsNullOrWhiteSpace(toolCall.Function.Name))
        {
            throw new InvalidOperationException(
                "Tool call is missing required function name.");
        }

        if (string.IsNullOrWhiteSpace(toolCall.Function.Arguments))
        {
            throw new InvalidOperationException(
                "Tool call is missing required function arguments.");
        }

        try
        {
            // Parse JSON arguments
            using var doc = JsonDocument.Parse(toolCall.Function.Arguments);
            var root = doc.RootElement;

            // Require root to be an object
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new InvalidOperationException(
                    "Tool call arguments must be a JSON object.");
            }

            var arguments = new Dictionary<string, string>();
            foreach (var property in root.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.String)
                {
                    arguments[property.Name] =
                        property.Value.GetString() ?? string.Empty;
                }
                else
                {
                    arguments[property.Name] =
                        property.Value.GetRawText();
                }
            }

            return new ToolRequest(
                Name: toolCall.Function.Name,
                Arguments: arguments);
        }
        catch (JsonException ex)
        {
            throw new InvalidOperationException(
                $"Failed to parse tool call arguments as JSON: {ex.Message}", ex);
        }
    }
}