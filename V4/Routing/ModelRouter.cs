namespace BotConnector.Desktop.V4.Routing;

public enum WorkloadClass
{
    Chat,
    Reasoning,
    Coding,
    CodingHeavy,
    ToolAgent
}

public enum RuntimeTarget
{
    Local,
    HermesCloud
}

public sealed class ModelRouter
{
    public RuntimeTarget Route(
        WorkloadClass workload,
        bool localAvailable)
    {
        return workload switch
        {
            WorkloadClass.Chat when localAvailable
                => RuntimeTarget.Local,

            WorkloadClass.Reasoning
                => RuntimeTarget.HermesCloud,

            WorkloadClass.Coding
                => RuntimeTarget.HermesCloud,

            WorkloadClass.CodingHeavy
                => RuntimeTarget.HermesCloud,

            WorkloadClass.ToolAgent
                => RuntimeTarget.HermesCloud,

            _
                => localAvailable
                    ? RuntimeTarget.Local
                    : RuntimeTarget.HermesCloud
        };
    }
}