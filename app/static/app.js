const loginPanel = document.querySelector("#loginPanel");
const appPanel = document.querySelector("#appPanel");
const loginForm = document.querySelector("#loginForm");
const uploadForm = document.querySelector("#uploadForm");
const logoutButton = document.querySelector("#logoutButton");
const refreshButton = document.querySelector("#refreshButton");
const clearTestDataButton = document.querySelector("#clearTestDataButton");
const displayName = document.querySelector("#displayName");
const permissionText = document.querySelector("#permissionText");
const uploadList = document.querySelector("#uploadList");
const message = document.querySelector("#message");
const progress = document.querySelector("#progress");
const uploadButton = document.querySelector("#uploadButton");
const folderPathInput = document.querySelector("#folderPathInput");
const createFolderButton = document.querySelector("#createFolderButton");
const folderList = document.querySelector("#folderList");
const folderSelect = document.querySelector("#folderSelect");
const rootPrefix = document.querySelector("#rootPrefix");
const uploadCount = document.querySelector("#uploadCount");
const fileSummary = document.querySelector("#fileSummary");
const fileInput = uploadForm.querySelector('input[type="file"]');

let currentUser = null;

async function request(path, options = {}) {
  const response = await fetch(path, { credentials: "include", ...options });
  if (!response.ok) {
    let detail = `요청 실패: ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }
  return response.json();
}

function showMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

async function loadMe() {
  try {
    currentUser = await request("/api/me");
    loginPanel.classList.add("hidden");
    appPanel.classList.remove("hidden");
    logoutButton.classList.remove("hidden");
    displayName.textContent = currentUser.displayName;
    rootPrefix.textContent = currentUser.rootPrefix;
    permissionText.textContent = currentUser.permissions.canUpload ? "업로드 가능" : "업로드 제한";
    clearTestDataButton.classList.toggle("hidden", currentUser.role !== "admin");
    await loadFolders();
    await loadUploads();
  } catch {
    currentUser = null;
    loginPanel.classList.remove("hidden");
    appPanel.classList.add("hidden");
    logoutButton.classList.add("hidden");
    clearTestDataButton.classList.add("hidden");
  }
}

async function loadFolders() {
  const folders = await request("/api/folders");
  folderList.innerHTML = "";
  folderSelect.innerHTML = '<option value="">앨범을 선택하세요</option>';

  if (!folders.length) {
    folderList.innerHTML = '<p class="hint">생성된 앨범 폴더가 없습니다.</p>';
    return;
  }

  for (const folder of folders) {
    const option = document.createElement("option");
    option.value = folder.relativePath;
    option.textContent = `${"  ".repeat(folder.depth || 0)}${folder.relativePath}`;
    folderSelect.appendChild(option);

    const row = document.createElement("div");
    row.className = "folder-row";
    row.style.setProperty("--depth", folder.depth || 0);
    const name = document.createElement("div");
    name.textContent = folder.relativePath;
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "ghost";
    rename.textContent = "선택";
    rename.addEventListener("click", async () => {
      folderSelect.value = folder.relativePath;
      showMessage(`${folder.relativePath} 앨범을 선택했습니다.`);
    });
    row.append(name, rename);
    folderList.appendChild(row);
  }
}

async function loadUploads() {
  const uploads = await request("/api/uploads");
  uploadList.innerHTML = "";
  uploadCount.textContent = `${uploads.length}개`;
  if (!uploads.length) {
    uploadList.innerHTML = '<p class="hint">아직 업로드된 파일이 없습니다.</p>';
    return;
  }

  for (const item of uploads) {
    const card = document.createElement("article");
    card.className = "card";

    const preview =
      item.mediaType === "video"
        ? `<video class="thumb" src="${item.previewUrl}" controls preload="metadata"></video>`
        : `<img class="thumb" src="${item.previewUrl}" alt="" loading="lazy">`;

    card.innerHTML = `
      ${preview}
      <div class="card-body">
        <div class="name"></div>
        <div class="meta">${formatBytes(item.sizeBytes)} · ${item.mediaType}</div>
        <div class="path"></div>
      </div>
    `;
    card.querySelector(".name").textContent = item.originalName;
    card.querySelector(".path").textContent = item.storedRelativePath;
    uploadList.appendChild(card);
  }
}

fileInput.addEventListener("change", () => {
  const files = [...fileInput.files];
  if (!files.length) {
    fileSummary.textContent = "선택된 파일 없음";
    return;
  }

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  fileSummary.textContent = `${files.length}개 · ${formatBytes(totalBytes)}`;
});

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(loginForm);
  try {
    await request("/api/login", { method: "POST", body: form });
    loginForm.reset();
    await loadMe();
  } catch (error) {
    showMessage(error.message, true);
  }
});

logoutButton.addEventListener("click", async () => {
  await request("/api/logout", { method: "POST" });
  await loadMe();
});

refreshButton.addEventListener("click", loadUploads);

clearTestDataButton.addEventListener("click", async () => {
  const ok = confirm("전체 업로드 기록과 저장된 테스트 파일을 삭제할까요?");
  if (!ok) return;

  clearTestDataButton.disabled = true;
  try {
    const result = await request("/api/test-data/clear", { method: "POST" });
    showMessage(`테스트 데이터 ${result.deletedUploads}개를 삭제했습니다.`);
    await loadFolders();
    await loadUploads();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    clearTestDataButton.disabled = false;
  }
});

async function createFolderFromInput() {
  const relativePath = folderPathInput.value.trim();
  if (!relativePath) return;

  createFolderButton.disabled = true;
  try {
    const created = await request("/api/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relativePath }),
    });
    folderPathInput.value = "";
    await loadFolders();
    folderSelect.value = created.relativePath;
    showMessage("앨범 폴더를 생성하고 선택했습니다.");
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    createFolderButton.disabled = false;
  }
}

createFolderButton.addEventListener("click", createFolderFromInput);

folderPathInput.addEventListener("keydown", async (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  await createFolderFromInput();
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(uploadForm);
  const files = form.getAll("files").filter((file) => file.size > 0);
  if (!files.length) return;

  uploadButton.disabled = true;
  progress.classList.remove("hidden");
  progress.removeAttribute("value");
  showMessage("업로드 중입니다. 큰 영상은 시간이 걸릴 수 있습니다.");

  try {
    await request("/api/uploads", { method: "POST", body: form });
    showMessage("업로드가 완료되었습니다.");
    fileInput.value = "";
    fileSummary.textContent = "선택된 파일 없음";
    await loadUploads();
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    uploadButton.disabled = false;
    progress.classList.add("hidden");
  }
});

loadMe();
