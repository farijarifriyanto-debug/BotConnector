namespace BotConnector.Auth;

public sealed class AuthTokenPair
{
    public string access_token { get; set; } = "";
    public string refresh_token { get; set; } = "";
    public string token_type { get; set; } = "Bearer";
    public int expires_in { get; set; }
}
