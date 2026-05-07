function updateRelativeTimes() {
  document.querySelectorAll(".relative-time").forEach(el => {
    const ts = el.dataset.ts;
    if (!ts) return;
    const date = new Date(ts + (ts.endsWith("Z") ? "" : "Z"));
    const diff = Math.floor((Date.now() - date) / 1000);
    if (diff < 60) el.textContent = `${diff}s ago`;
    else if (diff < 3600) el.textContent = `${Math.floor(diff / 60)}m ago`;
    else if (diff < 86400) el.textContent = `${Math.floor(diff / 3600)}h ago`;
    else el.textContent = date.toLocaleDateString();
  });
}

updateRelativeTimes();
setInterval(updateRelativeTimes, 30000);

async function triggerScript(scriptId) {
  const btn = document.getElementById(`trigger-${scriptId}`);
  if (btn) { btn.disabled = true; btn.textContent = "Queuing..."; }
  try {
    const resp = await fetch(`/api/scripts/${scriptId}/trigger`, { method: "POST" });
    const data = await resp.json();
    if (resp.ok) {
      window.location.href = `/jobs/${data.id}`;
    } else {
      alert(data.error || "Failed to trigger");
      if (btn) { btn.disabled = false; btn.textContent = "Run"; }
    }
  } catch (e) {
    alert("Network error");
    if (btn) { btn.disabled = false; btn.textContent = "Run"; }
  }
}
