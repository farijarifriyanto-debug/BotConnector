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

USER vscode
