const CLIENT_VERSION = "0.12.0";
const form = document.querySelector("#repo-form");
const input = document.querySelector("#repo-url");
const button = document.querySelector("#generate");
const errorBox = document.querySelector("#form-error");
const progress = document.querySelector("#progress");
const progressBar = document.querySelector("#progress-bar");
const progressMessage = document.querySelector("#progress-message");
const progressPercent = document.querySelector("#progress-percent");
const tokenInput = document.querySelector("#github-token");
const tokenToggle = document.querySelector("#toggle-token");
const themeInputs = document.querySelectorAll('input[name="theme"]');
themeInputs.forEach(item => item.addEventListener("change", () => {
  document.querySelector(".style-panel summary").textContent = `Diagram style: ${{"brand-logos":"Brand Logos", "icon-sketch":"Icon Sketch", classic:"Classic"}[item.value]}`;
}));

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function checkServerVersion() {
  try {
    const response = await fetch("/healthz", { cache: "no-store" });
    const health = response.ok ? await response.json() : {};
    if (health.version !== CLIENT_VERSION) {
      button.disabled = true;
      errorBox.textContent = `Frontend v${CLIENT_VERSION} is newer than the running backend. Restart repo2drawio-web, then reload this page.`;
      return false;
    }
  } catch {
    errorBox.textContent = "Cannot reach the repo2drawio backend. Check that the server is running.";
    return false;
  }
  return true;
}

async function readError(response) {
  try {
    const body = await response.json();
    return body.detail || "Something went wrong.";
  } catch {
    return "Something went wrong.";
  }
}

function setProgress(job) {
  const value = Math.max(5, Math.min(100, job.progress || 5));
  progressBar.style.width = `${value}%`;
  progressPercent.textContent = `${value}%`;
  progressMessage.textContent = job.message || "Inspecting repository";
}

async function poll(jobId, token) {
  for (;;) {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) throw new Error(await readError(response));
    const job = await response.json();
    setProgress(job);
    if (job.status === "complete") {
      window.location.assign(`${job.result_url}#edit=${encodeURIComponent(token)}`);
      return;
    }
    if (job.status === "failed") throw new Error(job.error || "Generation failed.");
    await wait(900);
  }
}

tokenToggle.addEventListener("click", () => {
  const showing = tokenInput.type === "text";
  tokenInput.type = showing ? "password" : "text";
  tokenToggle.textContent = showing ? "Show" : "Hide";
  tokenToggle.setAttribute("aria-label", showing ? "Show token" : "Hide token");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  if (!(await checkServerVersion())) return;
  button.disabled = true;
  input.disabled = true;
  tokenInput.disabled = true;
  progress.hidden = false;
  setProgress({ progress: 5, message: "Starting repository analysis" });
  try {
    const githubToken = tokenInput.value.trim();
    const theme = [...themeInputs].find((item) => item.checked)?.value || "brand-logos";
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_url: input.value.trim(), github_token: githubToken || null, theme }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const job = await response.json();
    tokenInput.value = "";
    await poll(job.id, job.edit_token);
  } catch (error) {
    progress.hidden = true;
    errorBox.textContent = error.message;
    input.disabled = false;
    tokenInput.disabled = false;
    button.disabled = false;
    input.focus();
  }
});

checkServerVersion();

fetch("/api/config").then(response => response.json()).then(config => {
  if (!config.allow_private) {
    document.querySelector(".private-panel").hidden = true;
    document.querySelector("#privacy-note").textContent = "Public repositories only on this demo. Self-host for private code. Diagram links can be viewed by anyone who has the link.";
  }
}).catch(() => {});
