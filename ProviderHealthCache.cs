using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;

namespace BotConnector.Desktop
{
    /// <summary>
    /// Health state of a provider/model.
    /// </summary>
    public enum HealthState
    {
        Healthy,
        Cooldown,
        Unavailable
    }

    /// <summary>
    /// Represents the cached health information for a provider.
    /// </summary>
    public sealed class ProviderHealth
    {
        public string ProviderId { get; set; }
        public string ModelId { get; set; }
        public HealthState State { get; set; }
        public string? FailureReason { get; set; }
        public DateTime FailureTime { get; set; }
        public DateTime CooldownUntil { get; set; }
        public DateTime LastSuccess { get; set; }

        public ProviderHealth(string providerId, string modelId)
        {
            ProviderId = providerId;
            ModelId = modelId;
            State = HealthState.Healthy;
            FailureTime = DateTime.UtcNow;
            CooldownUntil = DateTime.UtcNow;
            LastSuccess = DateTime.UtcNow;
        }
    }

    /// <summary>
    /// Lightweight in-memory health cache for provider/model selection with
    /// fast failover semantics. No disk/network operations.
    /// </summary>
    public sealed class ProviderHealthCache
    {
        private readonly ConcurrentDictionary<string, ProviderHealth> _cache
            = new ConcurrentDictionary<string, ProviderHealth>();

        private readonly object _lock = new object();

        /// <summary>
        /// Gets the health record for a provider; creates a fresh entry if absent.
        /// </summary>
        public ProviderHealth GetHealth(string providerId, string modelId)
        {
            // Create a new entry if none exists (treat as healthy)
            return _cache.GetOrAdd(providerId, id => new ProviderHealth(id, modelId));
        }

        /// <summary>
        /// Marks the provider as failed with the given reason.
        /// </summary>
        public void MarkFailure(string providerId, string modelId, string reason)
        {
            var health = GetHealth(providerId, modelId);
            health.State = HealthState.Unavailable;
            health.FailureReason = reason;
            health.FailureTime = DateTime.UtcNow;
            // Set cooldown to now + 30 seconds (configurable)
            health.CooldownUntil = DateTime.UtcNow.AddSeconds(30);
        }

        /// <summary>
        /// Marks the provider as successful (healthy) usage.
        /// </summary>
        public void MarkSuccess(string providerId, string modelId)
        {
            var health = GetHealth(providerId, modelId);
            health.State = HealthState.Healthy;
            health.LastSuccess = DateTime.UtcNow;
            // Clear cooldown
            health.CooldownUntil = DateTime.UtcNow;
        }

        /// <summary>
        /// Determines the next provider to use based on policy:
        /// Primary -> Hot Standby -> Healthy Free Fallback -> Paid Emergency.
        /// </summary>
        /// <param name="currentProviderId">The currently used provider ID.</param>
        /// <param name="fallbackProviderId">Optional hot standby provider ID.</param>
        /// <param name="freeProviderIds">Comma-separated list of validated free provider IDs.</param>
        /// <param name="paidProviderId">Paid emergency provider ID.</param>
        /// <returns>Provider ID to use.</returns>
        public string SelectNextProvider(
            string currentProviderId,
            string? fallbackProviderId,
            string? freeProviderIdsCsv,
            string? paidProviderId)
        {
            // Parse comma-separated free provider list
            var freeProviderIds = freeProviderIdsCsv?
                .Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(s => s.Trim())
                .ToList() ?? new List<string>();

            // Helper: is provider healthy right now?
            bool IsHealthy(string pid)
            {
                var h = _cache.GetOrAdd(pid, id => new ProviderHealth(id, ""));
                // Cooldown not expired?
                if (h.State == HealthState.Cooldown && h.CooldownUntil > DateTime.UtcNow)
                    return false;
                // If state is Unavailable, also false
                return h.State == HealthState.Healthy;
            }

            // 1. Primary
            if (IsHealthy(currentProviderId))
                return currentProviderId;

            // 2. Hot standby (if provided and healthy)
            if (!string.IsNullOrWhiteSpace(fallbackProviderId) && IsHealthy(fallbackProviderId))
                return fallbackProviderId;

            // 3. Healthy free fallback
            if (freeProviderIds != null)
            {
                foreach (var candidate in freeProviderIds)
                {
                    if (IsHealthy(candidate))
                        return candidate;
                }
            }

            // 4. Paid emergency
            if (!string.IsNullOrWhiteSpace(paidProviderId) && IsHealthy(paidProviderId))
                return paidProviderId;

            // Fallback to any provider (should not happen ideally)
            return currentProviderId;
        }
    }
}