"""Generate visual QA previews of BotConnector Parking for Desktop, Tablet, Mobile."""
import os
import subprocess

ARTIFACT_DIR = "/home/botadmin/.gemini/antigravity-cli/brain/e1785b55-cf80-4543-ad0c-d917720f0cfa"
STATIC_INDEX = "/home/botadmin/ai-workspaces/BotConnector-Parking/parking/static/index.html"

with open(STATIC_INDEX, "r") as f:
    html = f.read()

# 1. PAYMENT_ONLY Dashboard Mock
mock_po = """
<script>
window.fetch = async function(url, opts) {
    let u = typeof url === 'string' ? url : url.url;
    if (u.includes('/customer/me')) {
        return {
            ok: true,
            status: 200,
            json: async () => ({
                authenticated: true,
                user: { id: "usr_merchant", name: "PT Solusi Parkir Cerdas", email: "merchant@solusiparkir.co.id" },
                entitled: true,
                provisioned: true,
                deployment_profile: "PAYMENT_ONLY",
                tenant: { id: 2, code: "USER-SOLUSI01", name: "PT Solusi Parkir Cerdas", deployment_profile: "PAYMENT_ONLY" },
                site: null,
                api_token: "pk_live_merch991823719"
            })
        };
    }
    if (u.includes('/payment-gateway/reconciliation')) {
        return {
            ok: true,
            status: 200,
            json: async () => ({
                total_transactions_count: 85,
                paid_transactions_count: 82,
                pending_transactions_count: 3,
                total_settled_volume_idr: 1250000
            })
        };
    }
    return { ok: true, status: 200, json: async () => ({}) };
};
</script>
"""
html_po = html.replace("<head>", "<head>" + mock_po)
po_path = f"{ARTIFACT_DIR}/scratch/payment_only_preview.html"
with open(po_path, "w") as f:
    f.write(html_po)

# 2. Simulator View Mock
mock_sim = """
<script>
window.fetch = async function(url, opts) {
    let u = typeof url === 'string' ? url : url.url;
    if (u.includes('/customer/me')) {
        return {
            ok: true,
            status: 200,
            json: async () => ({
                authenticated: true,
                user: { id: "usr_mock", name: "Budi Santoso", email: "budi@example.com" },
                entitled: true,
                provisioned: true,
                deployment_profile: "FULL_STACK",
                tenant: { id: 1, code: "USER-BUDI1234", name: "Mall Nusantara Parking", deployment_profile: "FULL_STACK" },
                site: { id: 1, code: "SITE-MN", name: "Mall Nusantara Utama", capacity_total: 250, occupancy_cached: 42 },
                api_token: "pk_live_sampletoken123456"
            })
        };
    }
    return { ok: true, status: 200, json: async () => ({}) };
};
window.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        if (typeof showTab === 'function') showTab('simulator');
    }, 100);
});
</script>
"""
html_sim = html.replace("<head>", "<head>" + mock_sim)
sim_path = f"{ARTIFACT_DIR}/scratch/simulator_preview.html"
with open(sim_path, "w") as f:
    f.write(html_sim)

devices = [
    ("payment_only_desktop_1440.png", po_path, "1440,900"),
    ("simulator_desktop_1440.png", sim_path, "1440,900"),
]

for out_name, src_file, win_size in devices:
    out_path = f"{ARTIFACT_DIR}/{out_name}"
    cmd = [
        "timeout", "10",
        "google-chrome-stable",
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--virtual-time-budget=2000",
        f"--window-size={win_size}",
        f"--screenshot={out_path}",
        f"file://{src_file}",
    ]
    subprocess.run(cmd, check=True)
    print(f"Captured: {out_name} ({win_size})")
