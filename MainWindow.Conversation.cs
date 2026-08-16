using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Controls;

namespace BotConnector.Desktop;

// V5.4 structured conversation renderer (Claude / LM Studio style).
// Additive + contract-preserving: the legacy AssistantText TextBox is kept
// (hidden) so every existing code path still works; this feeds a virtualized
// ListBox of message cards with avatars and rendered code blocks.
public partial class MainWindow
{
    public sealed class ConvBlock
    {
        public bool IsCode { get; set; }
        public string Text { get; set; } = "";
        public string Lang { get; set; } = "";

        public string LangLabel =>
            string.IsNullOrWhiteSpace(Lang) ? "code" : Lang;

        public Visibility TextVisible =>
            IsCode ? Visibility.Collapsed : Visibility.Visible;

        public Visibility CodeVisible =>
            IsCode ? Visibility.Visible : Visibility.Collapsed;
    }

    public sealed class ConvMsg
    {
        public string Role { get; set; } = "";
        public string Accent { get; set; } = "#667085";
        public string Avatar { get; set; } = "";
        public bool IsUser { get; set; }
        public string BubbleBg { get; set; } = "Transparent";
        public List<ConvBlock> Blocks { get; set; } = new();
    }

    private readonly ObservableCollection<ConvMsg> _conversation = new();

    // Bound so long sessions cannot grow the rendered list without limit.
    private const int ConversationMaxCards = 300;

    private void V5InitConversation()
    {
        try
        {
            ConversationList.ItemsSource = _conversation;
            UpdateConversationEmptyState();
        }
        catch
        {
        }
    }

    private void V5AppendConversationCard(
        string role,
        string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        string label;
        string accent;
        string avatar;

        switch (role)
        {
            case "You":
                label = "You"; accent = "#2F6FED"; avatar = "U"; break;
            case "Assistant":
            case "BotConnector":
                label = "BotConnector"; accent = "#0EA5A5"; avatar = "BC"; break;
            case "System":
                label = "System"; accent = "#B45309"; avatar = "S"; break;
            case "Error":
                label = "Error"; accent = "#B42318"; avatar = "!"; break;
            default:
                label = role; accent = "#667085"; avatar = "*"; break;
        }

        bool isUser = role == "You";

        _conversation.Add(
            new ConvMsg
            {
                Role = label,
                Accent = accent,
                Avatar = avatar,
                IsUser = isUser,
                BubbleBg = isUser ? "#16223A" : "Transparent",
                Blocks = ParseBlocks(text.Trim())
            });

        while (_conversation.Count > ConversationMaxCards)
            _conversation.RemoveAt(0);

        UpdateConversationEmptyState();
        V5ScrollConversationToEnd();
    }

    // Split a message body into text / fenced-code (```...```) blocks so code
    // renders in a monospace box like Claude / LM Studio.
    private static List<ConvBlock> ParseBlocks(string body)
    {
        var blocks = new List<ConvBlock>();

        if (string.IsNullOrEmpty(body))
            return blocks;

        string[] parts =
            body.Split(new[] { "```" }, StringSplitOptions.None);

        for (int i = 0; i < parts.Length; i++)
        {
            bool isCode = (i % 2 == 1);
            string p = parts[i];

            if (isCode)
            {
                string code = p;
                string lang = "";

                // Capture an optional language tag on the first line (```python).
                int nl = code.IndexOf('\n');
                if (nl >= 0)
                {
                    string first = code.Substring(0, nl).Trim();
                    if (first.Length > 0 &&
                        first.Length < 20 &&
                        !first.Contains(' '))
                    {
                        lang = first;
                        code = code.Substring(nl + 1);
                    }
                }

                code = code.Trim('\r', '\n');

                if (code.Length > 0)
                    blocks.Add(
                        new ConvBlock { IsCode = true, Text = code, Lang = lang });
            }
            else
            {
                string t = p.Trim();
                if (t.Length > 0)
                    blocks.Add(new ConvBlock { IsCode = false, Text = t });
            }
        }

        if (blocks.Count == 0)
            blocks.Add(new ConvBlock { IsCode = false, Text = body.Trim() });

        return blocks;
    }

    // Rebuild the structured cards from a stored transcript (used when the
    // user switches threads). Parses the AppendConversation separator format.
    private void V5RebuildConversationFromTranscript(string transcript)
    {
        _conversation.Clear();

        if (!string.IsNullOrWhiteSpace(transcript))
        {
            string[] chunks =
                transcript.Split(
                    new[] { "--------------------------------" },
                    StringSplitOptions.RemoveEmptyEntries);

            foreach (string chunk in chunks)
            {
                string c = chunk.Trim('\r', '\n', ' ');
                if (c.Length == 0)
                    continue;

                int nl = c.IndexOf('\n');
                string label = (nl >= 0 ? c.Substring(0, nl) : c).Trim();
                string body = (nl >= 0 ? c.Substring(nl + 1) : "").Trim();

                if (body.Length == 0)
                    continue;

                string role = label.ToUpperInvariant() switch
                {
                    "YOU" => "You",
                    "BOTCONNECTOR" => "BotConnector",
                    "SYSTEM" => "System",
                    "ERROR" => "Error",
                    _ => label
                };

                V5AppendConversationCard(role, body);
            }
        }

        UpdateConversationEmptyState();
    }

    private void UpdateConversationEmptyState()
    {
        if (ConversationEmpty == null)
            return;

        ConversationEmpty.Visibility =
            _conversation.Count == 0
                ? Visibility.Visible
                : Visibility.Collapsed;
    }

    private void V5ScrollConversationToEnd()
    {
        try
        {
            if (_conversation.Count == 0)
                return;

            ConversationList.ScrollIntoView(
                _conversation[_conversation.Count - 1]);
        }
        catch
        {
        }
    }

    private void V5CopyCode_Click(
        object sender,
        RoutedEventArgs e)
    {
        try
        {
            if (sender is FrameworkElement fe &&
                fe.DataContext is ConvBlock b &&
                !string.IsNullOrEmpty(b.Text))
            {
                System.Windows.Clipboard.SetText(b.Text);
            }
        }
        catch
        {
        }
    }
}
