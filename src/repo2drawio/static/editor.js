const frame = document.querySelector("#drawio-frame");
const errorBox = document.querySelector("#editor-error");
const repoName = document.querySelector("#repo-name");
const saveState = document.querySelector("#save-state");
const copyButton = document.querySelector("#copy-link");
const downloadLink = document.querySelector("#download-link");
const jobId = window.location.pathname.split("/").filter(Boolean).pop();
const isExample = window.location.pathname.startsWith("/examples/");
const token = new URLSearchParams(window.location.hash.slice(1)).get("edit");
let diagramXml = "";
let downloadObjectUrl = null;

function localDownload(xml) {
  if (downloadObjectUrl) URL.revokeObjectURL(downloadObjectUrl);
  downloadObjectUrl = URL.createObjectURL(new Blob([xml], { type: "application/vnd.jgraph.mxfile" }));
  downloadLink.href = downloadObjectUrl;
  downloadLink.download = `${jobId}.drawio`;
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
  saveState.textContent = "Editor unavailable";
}

async function persist(xml) {
  if (!token) {
    diagramXml = xml;
    localDownload(xml);
    saveState.textContent = "Changes are local to this tab — download to keep them";
    return;
  }
  saveState.textContent = "Saving…";
  const response = await fetch(`/api/diagrams/${jobId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", "X-Edit-Token": token },
    body: JSON.stringify({ xml }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Could not save the diagram.");
  }
  diagramXml = xml;
  saveState.textContent = `Saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

window.addEventListener("message", async (event) => {
  if (event.origin !== "https://embed.diagrams.net" || event.source !== frame.contentWindow) return;
  let message;
  try {
    message = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
  } catch {
    return;
  }
  if (message.event === "init") {
    frame.contentWindow.postMessage(JSON.stringify({ action: "load", xml: diagramXml, autosave: 1 }), event.origin);
  }
  if ((message.event === "save" || message.event === "autosave") && message.xml) {
    try {
      await persist(message.xml);
    } catch (error) {
      showError(error.message);
    }
  }
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
    copyButton.textContent = "Copied!";
    setTimeout(() => { copyButton.textContent = "Copy edit link"; }, 1400);
  } catch { showError("Could not copy. Copy the address from your browser instead."); }
});

const viewButton = document.querySelector("#copy-view-link");
viewButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(`${window.location.origin}${window.location.pathname}`);
    viewButton.textContent = "Copied!";
    setTimeout(() => { viewButton.textContent = "Copy view link"; }, 1400);
  } catch { showError("Could not copy. Copy the address without its #edit fragment."); }
});

async function boot() {
  try {
    const response = await fetch(isExample ? `/api/examples/${jobId}` : `/api/diagrams/${jobId}`);
    if (!response.ok) throw new Error("Diagram not found or not ready.");
    const diagram = await response.json();
    diagramXml = diagram.xml;
    repoName.textContent = diagram.repo_slug || "Architecture";
    document.title = `${repoName.textContent} — repo2drawio`;
    if (!token) localDownload(diagramXml);
    else downloadLink.href = `/api/diagrams/${jobId}/download`;
    copyButton.hidden = !token;
    if (isExample) {
      const notice = document.querySelector("#example-notice");
      notice.textContent = `${diagram.repository} · ${diagram.commit.slice(0, 7)} · ${diagram.note} Edit here and download your copy.`;
      notice.hidden = false;
    }
    saveState.textContent = token ? "Ready to edit" : "Edit a local copy — download to keep changes";
    frame.src = "https://embed.diagrams.net/?embed=1&proto=json&spin=1&libraries=1&saveAndExit=0&noExitBtn=1";
  } catch (error) {
    showError(error.message);
  }
}

boot();
