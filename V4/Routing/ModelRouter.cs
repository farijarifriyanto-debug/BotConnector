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
    HermesCloud,
    CloudOrchestrator
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
                => RuntimeTarget.CloudOrchestrator,

            WorkloadClass.CodingHeavy
                => RuntimeTarget.CloudOrchestrator,

            WorkloadClass.ToolAgent
                => RuntimeTarget.HermesCloud,

            _
                => localAvailable
                    ? RuntimeTarget.Local
                    : RuntimeTarget.HermesCloud
        };
    }
}