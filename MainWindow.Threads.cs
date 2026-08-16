using System;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;

// Disambiguate WPF vs WinForms (project enables both).
using Button = System.Windows.Controls.Button;
using TextBox = System.Windows.Controls.TextBox;
using Orientation = System.Windows.Controls.Orientation;
using HorizontalAlignment = System.Windows.HorizontalAlignment;

namespace BotConnector.Desktop;

// V5.4 thread lifecycle: right-click a session to rename or delete.
public partial class MainWindow
{
    private void V2_SessionList_RightDown(
        object sender,
        MouseButtonEventArgs e)
    {
        // Right-click selects the item under the cursor so the context menu
        // acts on it.
        if (ItemsControl.ContainerFromElement(
                V2SessionList,
                e.OriginalSource as DependencyObject)
            is ListBoxItem item)
        {
            item.IsSelected = true;
        }
    }

    private void V2_RenameSession_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (V2SessionList.SelectedItem is not V2Session session)
            return;

        string? name =
            PromptText(
                "Rename thread",
                session.Title);

        if (string.IsNullOrWhiteSpace(name))
            return;

        session.Title = name.Trim();
        session.UpdatedUtc = DateTime.UtcNow;

        V2SaveSessions();
        V2RefreshSessions();

        V2SessionList.SelectedItem =
            V2SessionList.Items
                .Cast<V2Session>()
                .FirstOrDefault(x => x.Id == session.Id);
    }

    private void V2_DeleteSession_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (V2SessionList.SelectedItem is not V2Session session)
            return;

        var confirm =
            System.Windows.MessageBox.Show(
                "Delete this thread?\n\n\"" + session.Title + "\"",
                "Delete thread",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning);

        if (confirm != MessageBoxResult.Yes)
            return;

        _v2Sessions.RemoveAll(x => x.Id == session.Id);

        if (_v2Sessions.Count == 0)
        {
            _v2Sessions.Add(
                new V2Session
                {
                    Id = Guid.NewGuid().ToString("N"),
                    Title = "New Chat",
                    Text = "",
                    UpdatedUtc = DateTime.UtcNow
                });
        }

        V2SaveSessions();
        V2RefreshSessions();

        // Load the most recent remaining thread.
        var next =
            _v2Sessions
                .OrderByDescending(x => x.UpdatedUtc)
                .First();

        V2LoadSession(next);
    }

    // Minimal self-contained text prompt (no external dependency).
    private string? PromptText(
        string title,
        string initial)
    {
        var win = new Window
        {
            Title = title,
            Width = 400,
            Height = 168,
            Owner = this,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            ResizeMode = ResizeMode.NoResize,
            WindowStyle = WindowStyle.ToolWindow
        };

        var grid = new Grid { Margin = new Thickness(16) };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var caption = new TextBlock
        {
            Text = title,
            FontSize = 12,
            Margin = new Thickness(0, 0, 0, 8)
        };
        Grid.SetRow(caption, 0);

        var box = new TextBox
        {
            Text = initial,
            FontSize = 13,
            Padding = new Thickness(6, 4, 6, 4)
        };
        Grid.SetRow(box, 1);

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 14, 0, 0)
        };
        Grid.SetRow(buttons, 2);

        string? result = null;

        var ok = new Button
        {
            Content = "OK",
            Width = 76,
            Margin = new Thickness(0, 0, 8, 0),
            IsDefault = true
        };
        ok.Click += (_, _) =>
        {
            result = box.Text;
            win.DialogResult = true;
        };

        var cancel = new Button
        {
            Content = "Cancel",
            Width = 76,
            IsCancel = true
        };

        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);

        grid.Children.Add(caption);
        grid.Children.Add(box);
        grid.Children.Add(buttons);

        win.Content = grid;

        win.Loaded += (_, _) =>
        {
            box.Focus();
            box.SelectAll();
        };

        return win.ShowDialog() == true ? result : null;
    }
}
