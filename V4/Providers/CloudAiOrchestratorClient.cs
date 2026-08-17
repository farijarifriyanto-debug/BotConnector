using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace BotConnector.Desktop.V4.Providers;

/// <summary>
/// Cloud AI Orchestrator client for interacting with AI providers.
/// Handles assistant tool_calls, tool messages, and proper OpenAI JSON schema.
/// </summary>
public sealed class CloudAiOrchestratorClient
{
    private readonly HttpClient _httpClient;
    private readonly string? _apiKey;
    private readonly string _baseUrl;
    private readonly JsonSerializerOptions _jsonOptions;

    /// <summary>
    /// Initializes a new instance of the CloudAiOrchestratorClient.
    /// </summary>
    /// <param name="httpClient">Configured HttpClient instance</param>
    /// <param name="apiKey">Optional API key for authentication</param>
    /// <param name="baseUrl">Base URL for the AI provider (must be configured)</param>
    /// <exception cref="ArgumentNullException">Thrown if baseUrl is null or empty</exception>
    public CloudAiOrchestratorClient(HttpClient httpClient, string? apiKey, string baseUrl)
    {
        _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        _apiKey = apiKey;
        _baseUrl = baseUrl?.TrimEnd('/') ?? throw new ArgumentNullException(nameof(baseUrl));
        if (string.IsNullOrWhiteSpace(_baseUrl))
            throw new ArgumentException("Base URL cannot be whitespace", nameof(baseUrl));
        if (!_baseUrl.StartsWith("http", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("Base URL must be a valid HTTP/HTTPS URL", nameof(baseUrl));

        _jsonOptions = new JsonSerializerOptions
        {
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
        };
    }

    /// <summary>
    /// Sends a chat completion request to the AI provider.
    /// </summary>
    /// <param name="request">Chat completion request</param>
    /// <param name="cancellationToken">Cancellation token</param>
    /// <returns>Chat completion response</returns>
    public async Task<ChatCompletionResponse> GetChatCompletionAsync(
        ChatCompletionRequest request,
        CancellationToken cancellationToken = default)
    {
        if (request == null)
            throw new ArgumentNullException(nameof(request));

        using var httpRequest = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/chat/completions")
        {
            Content = new StringContent(
                JsonSerializer.Serialize(request, _jsonOptions),
                Encoding.UTF8,
                "application/json")
        };

        if (!string.IsNullOrEmpty(_apiKey))
        {
            httpRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
        }

        using var response = await _httpClient.SendAsync(httpRequest, cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();

        var responseContent = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        return JsonSerializer.Deserialize<ChatCompletionResponse>(responseContent, _jsonOptions)
            ?? throw new InvalidOperationException("Failed to deserialize response");
    }

    /// <summary>
    /// Creates a chat completion request from messages.
    /// </summary>
    public ChatCompletionRequest CreateChatCompletionRequest(
        IReadOnlyList<ChatMessage> messages,
        string model,
        IReadOnlyList<ChatTool>? tools = null,
        string? toolChoice = null)
    {
        return new ChatCompletionRequest
        {
            Model = model,
            Messages = messages,
            Tools = tools,
            ToolChoice = toolChoice
        };
    }

    /// <summary>
    /// Creates a system message.
    /// </summary>
    public ChatMessage CreateSystemMessage(string content)
    {
        return new ChatMessage
        {
            Role = ChatRole.System,
            Content = content
        };
    }

    /// <summary>
    /// Creates a user message.
    /// </summary>
    public ChatMessage CreateUserMessage(string content)
    {
        return new ChatMessage
        {
            Role = ChatRole.User,
            Content = content
        };
    }

    /// <summary>
    /// Creates an assistant message with optional tool calls.
    /// </summary>
    public ChatMessage CreateAssistantMessage(
        string? content = null,
        IReadOnlyList<ToolCall>? toolCalls = null)
    {
        return new ChatMessage
        {
            Role = ChatRole.Assistant,
            Content = content,
            ToolCalls = toolCalls
        };
    }

    /// <summary>
    /// Creates a tool message that provides the result of a tool call.
    /// </summary>
    public ChatMessage CreateToolMessage(string toolCallId, string content)
    {
        return new ChatMessage
        {
            Role = ChatRole.Tool,
            ToolCallId = toolCallId,
            Content = content
        };
    }

    /// <summary>
    /// Creates a function tool definition.
    /// </summary>
    public ChatTool CreateFunctionTool(
        string name,
        string description,
        IReadOnlyDictionary<string, FunctionParameter> parameters,
        IReadOnlyList<string> requiredParameters)
    {
        return new ChatTool
        {
            Type = ChatToolType.Function,
            Function = new FunctionTool
            {
                Name = name,
                Description = description,
                Parameters = new FunctionParameters
                {
                    Type = "object",
                    Properties = parameters,
                    Required = requiredParameters
                }
            }
        };
    }
}

/// <summary>
/// Chat completion request model.
/// </summary>
public sealed class ChatCompletionRequest
{
    [JsonPropertyName("model")]
    public required string Model { get; set; }

    [JsonPropertyName("messages")]
    public required IReadOnlyList<ChatMessage> Messages { get; set; }

    [JsonPropertyName("tools")]
    public IReadOnlyList<ChatTool>? Tools { get; set; }

    [JsonPropertyName("tool_choice")]
    public string? ToolChoice { get; set; }
}

/// <summary>
/// Chat message model.
/// </summary>
public sealed class ChatMessage
{
    [JsonPropertyName("role")]
    public required ChatRole Role { get; set; }

    [JsonPropertyName("content")]
    public string? Content { get; set; }

    [JsonPropertyName("tool_calls")]
    public IReadOnlyList<ToolCall>? ToolCalls { get; set; }

    [JsonPropertyName("tool_call_id")]
    public string? ToolCallId { get; set; }
}

/// <summary>
/// Chat role enum.
/// </summary>
public enum ChatRole
{
    System,
    User,
    Assistant,
    Tool
}

/// <summary>
/// Tool call model.
/// </summary>
public sealed class ToolCall
{
    [JsonPropertyName("id")]
    public required string Id { get; set; }

    [JsonPropertyName("type")]
    public required string Type { get; set; }

    [JsonPropertyName("function")]
    public required ToolCallFunction Function { get; set; }
}

/// <summary>
/// Tool call function model.
/// </summary>
public sealed class ToolCallFunction
{
    [JsonPropertyName("name")]
    public required string Name { get; set; }

    [JsonPropertyName("arguments")]
    public required string Arguments { get; set; }
}

/// <summary>
/// Chat tool model.
/// </summary>
public sealed class ChatTool
{
    [JsonPropertyName("type")]
    public required ChatToolType Type { get; set; }

    [JsonPropertyName("function")]
    public FunctionTool? Function { get; set; }
}

/// <summary>
/// Chat tool type enum.
/// </summary>
public enum ChatToolType
{
    Function
}

/// <summary>
/// Function tool model.
/// </summary>
public sealed class FunctionTool
{
    [JsonPropertyName("name")]
    public required string Name { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("parameters")]
    public required FunctionParameters Parameters { get; set; }
}

/// <summary>
/// Function parameters model.
/// </summary>
public sealed class FunctionParameters
{
    [JsonPropertyName("type")]
    public required string Type { get; set; }

    [JsonPropertyName("properties")]
    public required IReadOnlyDictionary<string, FunctionParameter> Properties { get; set; }

    [JsonPropertyName("required")]
    public IReadOnlyList<string>? Required { get; set; }
}

/// <summary>
/// Function parameter model.
/// </summary>
public sealed class FunctionParameter
{
    [JsonPropertyName("type")]
    public required string Type { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("enum")]
    public IReadOnlyList<string>? Enum { get; set; }
}

/// <summary>
/// Chat completion response model.
/// </summary>
public sealed class ChatCompletionResponse
{
    [JsonPropertyName("id")]
    public required string Id { get; set; }

    [JsonPropertyName("object")]
    public required string Object { get; set; }

    [JsonPropertyName("created")]
    public required long Created { get; set; }

    [JsonPropertyName("model")]
    public required string Model { get; set; }

    [JsonPropertyName("choices")]
    public required IReadOnlyList<Choice> Choices { get; set; }

    [JsonPropertyName("usage")]
    public Usage? Usage { get; set; }
}

/// <summary>
/// Choice model.
/// </summary>
public sealed class Choice
{
    [JsonPropertyName("index")]
    public required int Index { get; set; }

    [JsonPropertyName("message")]
    public required ChatMessage Message { get; set; }

    [JsonPropertyName("finish_reason")]
    public string? FinishReason { get; set; }
}

/// <summary>
/// Usage model.
/// </summary>
public sealed class Usage
{
    [JsonPropertyName("prompt_tokens")]
    public required int PromptTokens { get; set; }

    [JsonPropertyName("completion_tokens")]
    public required int CompletionTokens { get; set; }

    [JsonPropertyName("total_tokens")]
    public required int TotalTokens { get; set; }
}