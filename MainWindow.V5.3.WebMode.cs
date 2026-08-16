using System;
using System.IO;
using System.Windows;
using System.Windows.Controls;

namespace BotConnector.Desktop;

public partial class MainWindow
{
    private const string V53WebModeEnvironment =
        "BOTCONNECTOR_WEB_MODE";

    private static readonly string V53WebModePath =
        Path.Combine(
            Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData),
            "BotConnector",
            "Settings",
            "web-mode.txt");

    private static readonly string[] V53WebModeValues =
    {
        "auto",
        "off",
        "search",
        "deep_research",
        "url_docs"
    };

    private void V53_WebModeLoaded(
        object sender,
        RoutedEventArgs e)
    {
        if (sender is not System.Windows.Controls.ComboBox combo)
            return;

        string mode =
            V53LoadPersistedWebMode();

        int index =
            Array.IndexOf(
                V53WebModeValues,
                mode);

        combo.SelectedIndex =
            index >= 0
                ? index
                : 0;

        V53SetProcessWebMode(
            V53WebModeValues[
                combo.SelectedIndex < 0
                    ? 0
                    : combo.SelectedIndex]);

        // Startup must remain side-effect free for the visual tree.
        // The process mode is now restored; activity is shown after a
        // user-initiated mode change or an actual agent turn.
    }

    private void V53_WebModeChanged(
        object sender,
        SelectionChangedEventArgs e)
    {
        if (sender is not System.Windows.Controls.ComboBox combo)
            return;

        // SelectionChanged can fire while InitializeComponent is still
        // constructing the XAML tree because SelectedIndex is set in markup.
        // Do not touch other MainWindow controls until the Window is loaded.
        if (!IsLoaded)
            return;

        if (
            combo.SelectedIndex < 0 ||
            combo.SelectedIndex >=
                V53WebModeValues.Length
        )
            return;

        string mode =
            V53WebModeValues[
                combo.SelectedIndex];

        V53SetProcessWebMode(
            mode);

        V53PersistWebMode(
            mode);

        string label =
            V53WebModeDisplay(
                mode);

        SetAgentActivity(
            "Web: " + label);

        AppendTerminal(
            "[Web] Mode selected: " +
            label);
    }

    private static void V53SetProcessWebMode(
        string mode)
    {
        Environment.SetEnvironmentVariable(
            V53WebModeEnvironment,
            V53NormalizeWebMode(mode),
            EnvironmentVariableTarget.Process);
    }

    private static string V53CurrentWebMode()
    {
        return V53NormalizeWebMode(
            Environment.GetEnvironmentVariable(
                V53WebModeEnvironment));
    }

    private static string V53LoadPersistedWebMode()
    {
        try
        {
            if (
                File.Exists(
                    V53WebModePath)
            )
            {
                return V53NormalizeWebMode(
                    File.ReadAllText(
                        V53WebModePath));
            }
        }
        catch
        {
        }

        return "auto";
    }

    private static void V53PersistWebMode(
        string mode)
    {
        try
        {
            string? parent =
                Path.GetDirectoryName(
                    V53WebModePath);

            if (
                !string.IsNullOrWhiteSpace(
                    parent)
            )
            {
                Directory.CreateDirectory(
                    parent);
            }

            File.WriteAllText(
                V53WebModePath,
                V53NormalizeWebMode(mode));
        }
        catch
        {
        }
    }

    private static string V53NormalizeWebMode(
        string? mode)
    {
        string normalized =
            (mode ?? "")
            .Trim()
            .ToLowerInvariant();

        foreach (
            string allowed in
                V53WebModeValues)
        {
            if (
                string.Equals(
                    normalized,
                    allowed,
                    StringComparison.Ordinal)
            )
            {
                return allowed;
            }
        }

        return "auto";
    }

    private static string V53WebModeDisplay(
        string mode)
    {
        return V53NormalizeWebMode(mode)
            switch
            {
                "off" =>
                    "Off",

                "search" =>
                    "Search",

                "deep_research" =>
                    "Deep Research",

                "url_docs" =>
                    "URL / Docs",

                _ =>
                    "Auto"
            };
    }
}