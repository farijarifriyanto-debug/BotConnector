using System.Windows;
using Button = System.Windows.Controls.Button;

namespace BotConnector.Desktop;

// V5.4 agent modes: Ask (read/analyze), Agent (implement), Plan (plan only).
// The selected mode is injected as a directive into the Hermes prompt.
public partial class MainWindow
{
    private string _agentMode = "agent";

    private void V5_AgentMode_Click(
        object sender,
        RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is string mode)
        {
            _agentMode = mode;
            V5UpdateModeButtons();
        }
    }

    private void V5UpdateModeButtons()
    {
        var primary = (Style)FindResource("PrimaryButton");
        var soft = (Style)FindResource("SoftButton");

        if (AskModeButton != null)
            AskModeButton.Style = _agentMode == "ask" ? primary : soft;

        if (AgentModeButton != null)
            AgentModeButton.Style = _agentMode == "agent" ? primary : soft;

        if (PlanModeButton != null)
            PlanModeButton.Style = _agentMode == "plan" ? primary : soft;
    }

    private string V5AgentModeDirective()
    {
        return _agentMode switch
        {
            "ask" =>
                "MODE: Ask. Read and analyze only. Answer the question directly. " +
                "Do NOT modify files or run commands unless the user explicitly asks.\n\n",
            "plan" =>
                "MODE: Plan. Produce a concrete, actionable implementation plan with " +
                "ordered steps and the files involved. Do NOT modify files yet; wait " +
                "for the user to start execution.\n\n",
            _ =>
                "MODE: Agent. Implement end-to-end: inspect, edit, run, test, " +
                "review, and iterate until the task is complete.\n\n"
        };
    }
}
