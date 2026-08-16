using System;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

// Disambiguate WPF vs GDI/WinForms (project enables both).
using Brush = System.Windows.Media.Brush;
using Color = System.Windows.Media.Color;
using FontFamily = System.Windows.Media.FontFamily;

namespace BotConnector.Desktop;

// V5.4 lightweight Markdown renderer for assistant text blocks (Claude-style):
// headings, bold, inline code, bullet + numbered lists, paragraphs.
public partial class MainWindow
{
    private void V5MarkdownText_Loaded(object sender, RoutedEventArgs e)
        => V5RenderMarkdownInto(sender as ContentControl);

    private void V5MarkdownText_DataContextChanged(
        object sender, DependencyPropertyChangedEventArgs e)
        => V5RenderMarkdownInto(sender as ContentControl);

    private void V5RenderMarkdownInto(ContentControl? cc)
    {
        if (cc?.DataContext is ConvBlock b && !b.IsCode)
            cc.Content = V5BuildMarkdown(b.Text);
    }

    private Brush V5TextBrush()
    {
        try { return (Brush)FindResource("Text"); }
        catch { return new SolidColorBrush(Color.FromRgb(0xE6, 0xEA, 0xF0)); }
    }

    private FrameworkElement V5BuildMarkdown(string text)
    {
        var panel = new StackPanel();

        if (string.IsNullOrEmpty(text))
            return panel;

        string[] lines = text.Replace("\r", "").Split('\n');
        int i = 0;

        while (i < lines.Length)
        {
            string t = lines[i].TrimStart();

            if (t.StartsWith("### ")) { panel.Children.Add(V5Heading(t.Substring(4), 14)); i++; continue; }
            if (t.StartsWith("## "))  { panel.Children.Add(V5Heading(t.Substring(3), 15.5)); i++; continue; }
            if (t.StartsWith("# "))   { panel.Children.Add(V5Heading(t.Substring(2), 17)); i++; continue; }

            if (t.StartsWith("- ") || t.StartsWith("* "))
            {
                while (i < lines.Length)
                {
                    string l = lines[i].TrimStart();
                    if (!(l.StartsWith("- ") || l.StartsWith("* "))) break;
                    panel.Children.Add(V5ListItem("•  ", l.Substring(2)));
                    i++;
                }
                continue;
            }

            if (Regex.IsMatch(t, @"^\d+\.\s"))
            {
                while (i < lines.Length)
                {
                    string l = lines[i].TrimStart();
                    var m = Regex.Match(l, @"^(\d+)\.\s(.*)$");
                    if (!m.Success) break;
                    panel.Children.Add(V5ListItem(m.Groups[1].Value + ".  ", m.Groups[2].Value));
                    i++;
                }
                continue;
            }

            if (t.Length == 0) { i++; continue; }

            var para = new StringBuilder();
            while (i < lines.Length)
            {
                string l = lines[i];
                string lt = l.TrimStart();
                if (lt.Length == 0 ||
                    lt.StartsWith("# ") || lt.StartsWith("## ") || lt.StartsWith("### ") ||
                    lt.StartsWith("- ") || lt.StartsWith("* ") ||
                    Regex.IsMatch(lt, @"^\d+\.\s"))
                    break;
                if (para.Length > 0) para.Append('\n');
                para.Append(l.TrimEnd());
                i++;
            }
            panel.Children.Add(V5Paragraph(para.ToString()));
        }

        return panel;
    }

    private TextBlock V5Heading(string text, double size)
    {
        var tb = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = size,
            FontWeight = FontWeights.SemiBold,
            Foreground = V5TextBrush(),
            Margin = new Thickness(0, 8, 0, 4)
        };
        V5AddInlines(tb, text.Trim());
        return tb;
    }

    private TextBlock V5Paragraph(string text)
    {
        var tb = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13.5,
            LineHeight = 20,
            Foreground = V5TextBrush(),
            Margin = new Thickness(0, 0, 0, 6)
        };
        V5AddInlines(tb, text);
        return tb;
    }

    private FrameworkElement V5ListItem(string marker, string text)
    {
        var grid = new Grid { Margin = new Thickness(2, 1, 0, 3) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var bullet = new TextBlock
        {
            Text = marker,
            FontSize = 13.5,
            Foreground = V5TextBrush(),
            Margin = new Thickness(0, 0, 4, 0)
        };
        Grid.SetColumn(bullet, 0);

        var body = new TextBlock
        {
            TextWrapping = TextWrapping.Wrap,
            FontSize = 13.5,
            LineHeight = 20,
            Foreground = V5TextBrush()
        };
        Grid.SetColumn(body, 1);
        V5AddInlines(body, text.Trim());

        grid.Children.Add(bullet);
        grid.Children.Add(body);
        return grid;
    }

    // Inline parse: **bold** and `inline code`.
    private void V5AddInlines(TextBlock tb, string text)
    {
        var codeBg = new SolidColorBrush(Color.FromRgb(0x1B, 0x24, 0x32));
        int i = 0;

        while (i < text.Length)
        {
            if (text[i] == '*' && i + 1 < text.Length && text[i + 1] == '*')
            {
                int end = text.IndexOf("**", i + 2, StringComparison.Ordinal);
                if (end > i + 1)
                {
                    tb.Inlines.Add(new Run(text.Substring(i + 2, end - (i + 2)))
                    { FontWeight = FontWeights.SemiBold });
                    i = end + 2;
                    continue;
                }
            }

            if (text[i] == '`')
            {
                int end = text.IndexOf('`', i + 1);
                if (end > i)
                {
                    tb.Inlines.Add(new Run(text.Substring(i + 1, end - (i + 1)))
                    {
                        FontFamily = new FontFamily("Cascadia Mono, Consolas"),
                        Background = codeBg,
                        FontSize = 12.5
                    });
                    i = end + 1;
                    continue;
                }
            }

            int next = i;
            while (next < text.Length)
            {
                if (text[next] == '`') break;
                if (text[next] == '*' && next + 1 < text.Length && text[next + 1] == '*') break;
                next++;
            }
            tb.Inlines.Add(new Run(text.Substring(i, next - i)));
            i = next;
        }
    }
}
