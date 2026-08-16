FROM mcr.microsoft.com/devcontainers/dotnet:8.0-noble

USER root

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       git \
       jq \
       ripgrep \
    && rm -rf /var/lib/apt/lists/*


# SERENA_DOTNET10_RUNTIME
# Serena C# Roslyn Language Server requires .NET 10+ runtime.
# Keep the project SDK/TargetFramework on .NET 8; install runtime only.
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh \
        -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh \
        --channel 10.0 \
        --runtime dotnet \
        --install-dir /usr/share/dotnet \
        --no-path \
    && rm -f /tmp/dotnet-install.sh

USER vscode
