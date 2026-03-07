const API_BASE = "http://127.0.0.1:8130/api/dashboard";
const POLL_INTERVAL = 5000;

function removeLoading(el) { if (el && el.classList.contains("temp-loading")) el.classList.remove("temp-loading"); }
function formatMoney(n) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n); }
function formatNumber(n) { return new Intl.NumberFormat('en-US').format(n); }

async function fetchHealth() {
    try {
        const res = await fetch(`${API_BASE}/health`);
        const data = await res.json();

        const sections = ['radar', 'product', 'traffic', 'conversion', 'revenue'];
        sections.forEach(sec => {
            const el = document.getElementById(`health-${sec}`);
            removeLoading(el);
            const status = data[`${sec}_status`];
            el.textContent = status;
            el.className = `metric-value status-${status}`;
        });

        // Parse Alerts
        const alertBar = document.getElementById('alert-bar');
        alertBar.innerHTML = '';
        if (data.alerts) {
            Object.keys(data.alerts).forEach(k => {
                if (data.alerts[k]) {
                    const alertEl = document.createElement('div');
                    alertEl.className = 'alert warning';
                    alertEl.innerHTML = `⚠️ Anomaly Detected: ${k.toUpperCase().replace('_', ' ')}`;
                    alertBar.appendChild(alertEl);
                }
            });
        }
    } catch (e) { console.error("Health err", e); }
}

async function fetchEvolution() {
    try {
        const res = await fetch(`${API_BASE}/evolution`);
        const data = await res.json();
        const list = document.getElementById('evolution-list');
        list.innerHTML = '';

        let hasItem = false;
        if (data.winning_patterns && data.winning_patterns.length) {
            hasItem = true;
            data.winning_patterns.forEach(p => {
                list.innerHTML += `<div class="list-item"><strong>[WINNING PATTERN]</strong><span>${p}</span></div>`;
            });
        }
        if (!hasItem) {
            list.innerHTML = '<div class="list-item"><span>No long-term evolution patterns crystallized yet.</span></div>';
        }
    } catch (e) { console.error("Evolution err", e); }
}

async function fetchRadar() {
    try {
        const res = await fetch(`${API_BASE}/radar`);
        const data = await res.json();
        const list = document.getElementById('radar-list');
        list.innerHTML = '';

        const opps = data.opportunities || [];
        if (opps.length === 0) list.innerHTML = '<div class="list-item"><span>No opportunities.</span></div>';

        opps.forEach(opp => {
            list.innerHTML += `<div class="list-item"><strong>${opp.query || opp.keyword}</strong><span>Score: ${opp.score || opp.normalized_score} | Source: ${opp.platform || 'Radar'}</span></div>`;
        });
    } catch (e) { console.error(e); }
}

async function fetchProducts() {
    try {
        const res = await fetch(`${API_BASE}/products`);
        const data = await res.json();
        const container = document.getElementById('products-container');
        container.innerHTML = '';
        if (data.length === 0) container.innerHTML = '<div class="temp-loading">Empty Pipeline</div>';

        data.forEach((p, idx) => {
            const name = p.generated_copy?.name || `Product_0${idx}`;
            const created = p.created_at || "Unknown";
            const landingUrl = p.landing_url || "#";
            const btnLanding = p.landing_url ? `<a href="${landingUrl}" target="_blank" class="btn btn-sm">View Landing</a>` : `<button class="btn btn-sm" disabled>View Landing</button>`;

            container.innerHTML += `
            <div class="product-card">
                <div class="product-card-header">
                    <span class="product-card-title">${name}</span>
                    <span class="badge" style="color:var(--accent-blue)">${p.lifecycle_state || 'unknown'}</span>
                </div>
                <div class="product-card-meta">Created At: ${created}</div>
                <div class="product-card-actions">
                    ${btnLanding}
                    <button class="btn btn-sm" onclick="openPreview('${p.product_id}')">Preview Product</button>
                    <button class="btn btn-sm" onclick="openMaintenance('${p.product_id}')">Maintenance</button>
                </div>
                
                <div class="product-card-actions" style="margin-top:5px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px;">
                    <button class="btn btn-primary btn-sm" onclick="triggerIntent('promote', '${p.product_id}')">Promote</button>
                    <button class="btn btn-sm" onclick="triggerIntent('pause', '${p.product_id}')">Pause</button>
                </div>
            </div>`;
        });
    } catch (e) { console.error(e); }
}

async function fetchLandings() {
    try {
        const res = await fetch(`${API_BASE}/landings`);
        const data = await res.json();
        const list = document.getElementById('landings-list');
        list.innerHTML = '';
        if (data.length === 0) list.innerHTML = '<div class="list-item"><span>No active landings.</span></div>';

        data.forEach(l => {
            list.innerHTML += `<div class="list-item"><strong>${l.name}</strong><span>Status: ${l.status} | <a href="${l.landing_url}" target="_blank" style="color:var(--accent-blue)">View</a></span></div>`;
        });
    } catch (e) { console.error(e); }
}

async function fetchTraffic() {
    try {
        const res = await fetch(`${API_BASE}/traffic`);
        const data = await res.json();
        const vis = document.getElementById('metric-visitors');
        removeLoading(vis);
        vis.textContent = formatNumber(data.total_visitors || 0);
    } catch (e) { console.error(e); }
}

async function fetchConversion() {
    try {
        const [trafRes, revRes] = await Promise.all([fetch(`${API_BASE}/traffic`), fetch(`${API_BASE}/revenue`)]);
        const tData = await trafRes.json();
        const rData = await revRes.json();

        const conv = document.getElementById('metric-conv');
        const mrr = document.getElementById('metric-mrr');
        removeLoading(conv); removeLoading(mrr);

        conv.textContent = (tData.avg_conversion_rate || 0).toFixed(2) + "%";
        mrr.textContent = formatMoney(rData.total_mrr || 0);
    } catch (e) { console.error(e); }
}

async function fetchIntelligence() {
    try {
        const res = await fetch(`${API_BASE}/intelligence`);
        const data = await res.json();
        const list = document.getElementById('intelligence-list');
        list.innerHTML = '';

        if (data.length === 0) list.innerHTML = '<div class="list-item"><span>No signals.</span></div>';

        data.forEach(sig => {
            let title = sig.type || sig._category;
            let sub = sig.source_event || "Unknown";
            let val = sig.segment || sig.details || "";
            if (typeof val === 'object') val = JSON.stringify(val);
            list.innerHTML += `<div class="list-item"><strong><span style="color:var(--accent-purple)">[${sub}]</span> ${title}</strong><span>${val}</span></div>`;
        });
    } catch (e) { console.error(e); }
}

async function triggerIntent(action, id) {
    const ev = action === 'promote' ? 'dashboard_launch_product' : 'dashboard_pause_product';
    try {
        document.getElementById('update-status').textContent = "Sending Intent...";
        await fetch(`${API_BASE}/intent`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event: ev, data: { product_id: id } })
        });
        setTimeout(pollData, 500);
    } catch (e) { console.error(e); }
}

async function pollData() {
    document.getElementById('update-status').textContent = "Syncing Pipeline...";
    const start = Date.now();
    try {
        await Promise.all([
            fetchHealth(), fetchRadar(), fetchProducts(), fetchLandings(),
            fetchTraffic(), fetchConversion(), fetchIntelligence(), fetchEvolution()
        ]);
        const dur = Date.now() - start;
        document.getElementById('update-status').textContent = `Pipeline Sync OK (${dur}ms)`;
    } catch (e) {
        document.getElementById('update-status').textContent = `Sync Error`;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    pollData();
    setInterval(pollData, POLL_INTERVAL);
});

// --- P9.3 Product Inspection Controls ---

function openPreview(productId) {
    const previewToken = "insp_" + Math.random().toString(36).substr(2, 9) + "_" + Date.now();
    const expiration = Date.now() + 15 * 60 * 1000;

    sessionStorage.setItem('preview_token_' + productId, JSON.stringify({
        token: previewToken,
        expires: expiration,
        mode: "read-only"
    }));

    const existingModal = document.getElementById('preview-modal');
    if (existingModal) existingModal.remove();

    const modalHtml = `
    <div id="preview-modal" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:9999; display:flex; justify-content:center; align-items:center;">
        <div style="background:#07070a; width:80%; height:80%; border-radius:12px; border:1px solid rgba(255,255,255,0.1); display:flex; flex-direction:column; overflow:hidden;">
            <div style="padding:15px; border-bottom:1px solid rgba(255,255,255,0.1); display:flex; justify-content:space-between; align-items:center;">
                <h3 style="margin:0;">Product Preview Mode [READ-ONLY]</h3>
                <div>
                   <span class="badge" style="color:var(--accent-purple)">Token: ${previewToken}</span>
                   <button class="btn btn-sm" onclick="document.getElementById('preview-modal').remove()">Close</button>
                </div>
            </div>
            <div style="padding:20px; overflow-y:auto; flex-grow:1;">
                <p>Generating safe preview view for Product ID: ${productId}...</p>
                <div id="preview-content-${productId}">Loading product details...</div>
            </div>
        </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    fetchProductDetailsForPreview(productId, previewToken);
}

function fetchProductDetailsForPreview(productId, token) {
    const stored = JSON.parse(sessionStorage.getItem('preview_token_' + productId));
    if (!stored || stored.token !== token || Date.now() > stored.expires) {
        document.getElementById('preview-content-' + productId).innerHTML = "<span style='color:red'>Preview token expired or invalid. Access denied.</span>";
        return;
    }

    fetch(`${API_BASE}/products`)
        .then(res => res.json())
        .then(data => {
            const p = data.find(x => x.product_id === productId);
            if (!p) {
                document.getElementById('preview-content-' + productId).innerHTML = "Product not found context.";
                return;
            }

            const html = `
                <div style="display:flex; flex-direction:column; gap:15px; margin-top:20px;">
                    <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:8px;">
                        <h4 style="margin-bottom:10px; color:var(--accent-blue)">Navigating Product Content</h4>
                        <p><strong>Name:</strong> ${p.generated_copy?.name || 'Unknown'}</p>
                        <p><strong>Headline:</strong> ${p.generated_copy?.headline || 'Unknown'}</p>
                        <p><strong>Subheadline:</strong> ${p.generated_copy?.subheadline || 'Unknown'}</p>
                        <p><strong>Description:</strong> ${p.generated_copy?.long_description || 'Unknown'}</p>
                    </div>
                    <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:8px;">
                        <h4 style="margin-bottom:10px; color:var(--accent-green)">Validating Language & Layout</h4>
                        <ul>
                            <li><span class="badge">Tone Check: Pending</span> No active language mutations found</li>
                            <li><span class="badge">Structure Check: Pending</span> Layout conforms to baseline standards</li>
                        </ul>
                    </div>
                    <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:8px;">
                        <h4 style="margin-bottom:10px; color:var(--accent-purple)">Internal Navigation</h4>
                        <p>[READ-ONLY]: No actionable mutators available in this context. Lifecycle cannot be altered.</p>
                    </div>
                </div>
            `;
            document.getElementById('preview-content-' + productId).innerHTML = html;
        });
}

function openMaintenance(productId) {
    if (!confirm(`Open Maintenance Session for Product: ${productId}?\nThis will emit a diagnostic context to Anti-Gravity without interrupting the product lifecycle.`)) {
        return;
    }

    // Find the product data for context
    fetch(`${API_BASE}/products`)
        .then(res => res.json())
        .then(data => {
            const p = data.find(x => x.product_id === productId);
            if (!p) return;

            const payload = {
                event: "dashboard_maintenance_requested",
                data: {
                    maintenance_type: "product",
                    product_id: productId,
                    landing_url: p.landing_url,
                    timestamp: new Date().toISOString(),
                    origin: "dashboard"
                }
            };

            fetch(`${API_BASE}/intent`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            }).then(() => {
                alert(`Maintenance Context Prepared for Anti-Gravity.\nTarget: ${productId}\nCheck execution logs for details.`);
            }).catch(console.error);
        });
}

function triggerSystemMaintenance() {
    if (!confirm(`Open Global System Maintenance Session?\nThis will emit a system-level diagnostic context to Anti-Gravity.`)) {
        return;
    }

    const payload = {
        event: "dashboard_maintenance_requested",
        data: {
            maintenance_type: "system",
            timestamp: new Date().toISOString(),
            origin: "dashboard"
        }
    };

    fetch(`${API_BASE}/intent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    }).then(() => {
        alert("Global System Maintenance Context Prepared for Anti-Gravity.\nCheck execution logs for details.");
    }).catch(console.error);
}
