/**
 * app.js — Telegram Drive frontend application.
 *
 * Handles: password auth, hierarchical folder navigation with breadcrumbs,
 * sub-folder creation, file upload/download/delete.
 */

// ══════════════════════════════════════════════
//  State
// ══════════════════════════════════════════════
let currentFolderId = null;        // null = root
let currentFolderName = "Root";
let breadcrumbs = [];              // [{id, name}, ...]
let contextMenuFolderId = null;
let contextMenuFolderName = null;

// ══════════════════════════════════════════════
//  DOM References
// ══════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

const loginScreen   = $("login-screen");
const driveScreen   = $("drive-screen");
const passwordInput = $("password-input");
const loginBtn      = $("login-btn");
const loginError    = $("login-error");

const folderList    = $("folder-list");
const folderTitle   = $("current-folder-title");
const filesTbody    = $("files-tbody");
const filesTable    = $("files-table");
const emptyState    = $("empty-state");
const userInfo      = $("user-info");
const dropZone      = $("drop-zone");
const fileInput     = $("file-input");
const progressCont  = $("upload-progress-container");
const progressFill  = $("upload-progress-fill");
const uploadFilename = $("upload-filename");
const uploadPercent = $("upload-percent");
const modalOverlay  = $("modal-overlay");
const modalInput    = $("modal-input");
const modalTitle    = $("modal-title");
const modalError    = $("modal-error");
const modalConfirm  = $("modal-confirm-btn");
const contextMenu   = $("context-menu");
const breadcrumbBar = $("breadcrumb-bar");

// ══════════════════════════════════════════════
//  Init — check auth on load
// ══════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", async () => {
    try {
        const res = await fetch("/api/auth/check");
        if (res.ok) {
            const data = await res.json();
            if (data.authenticated) {
                showDriveScreen(data.user);
                return;
            }
        }
    } catch (_) {}
    showLoginScreen();
});

// ══════════════════════════════════════════════
//  Auth Flow (Password)
// ══════════════════════════════════════════════
function showLoginScreen() {
    loginScreen.classList.add("active");
    driveScreen.classList.remove("active");
}

function showDriveScreen(user) {
    loginScreen.classList.remove("active");
    driveScreen.classList.add("active");
    driveScreen.style.flexDirection = "column";

    if (user) {
        userInfo.textContent = user.username || "Admin";
    }

    navigateToFolder(null, "Root");
    setupDragDrop();
}

async function login() {
    const password = passwordInput.value.trim();
    if (!password) return showLoginError("Enter your password");

    setButtonLoading(loginBtn, true);
    hideLoginError();

    try {
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password }),
        });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || "Login failed");

        showDriveScreen(data.user);
    } catch (err) {
        showLoginError(err.message);
    } finally {
        setButtonLoading(loginBtn, false);
    }
}

async function logout() {
    try {
        await fetch("/api/auth/logout", { method: "POST" });
    } catch (_) {}
    passwordInput.value = "";
    showLoginScreen();
}

function showLoginError(msg) {
    loginError.textContent = msg;
    loginError.classList.remove("hidden");
}

function hideLoginError() {
    loginError.classList.add("hidden");
}

function setButtonLoading(btn, loading) {
    const text = btn.querySelector(".btn-text");
    const loader = btn.querySelector(".btn-loader");
    if (loading) {
        if (text) text.classList.add("hidden");
        if (loader) loader.classList.remove("hidden");
        btn.disabled = true;
    } else {
        if (text) text.classList.remove("hidden");
        if (loader) loader.classList.add("hidden");
        btn.disabled = false;
    }
}

// Handle Enter key
passwordInput.addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });

// ══════════════════════════════════════════════
//  Navigation — Hierarchical Folder Browsing
// ══════════════════════════════════════════════

async function navigateToFolder(folderId, folderName) {
    currentFolderId = folderId;
    currentFolderName = folderName || "Root";

    // Update breadcrumbs
    if (folderId === null) {
        breadcrumbs = [];
    } else {
        // Fetch the path from the server
        try {
            const res = await fetch(`/api/folders/${folderId}/path`);
            if (res.ok) {
                const path = await res.json();
                breadcrumbs = path.map(f => ({ id: f.id, name: f.name }));
            }
        } catch (err) {
            console.error("Failed to fetch folder path:", err);
        }
    }

    renderBreadcrumbs();
    folderTitle.textContent = currentFolderName;
    loadFolders();
}

function renderBreadcrumbs() {
    if (!breadcrumbBar) return;

    breadcrumbBar.innerHTML = "";

    // Root crumb
    const rootCrumb = document.createElement("span");
    rootCrumb.className = `breadcrumb-item${breadcrumbs.length === 0 ? " active" : ""}`;
    rootCrumb.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
        </svg>
        Root
    `;
    rootCrumb.addEventListener("click", () => navigateToFolder(null, "Root"));
    breadcrumbBar.appendChild(rootCrumb);

    // Path crumbs
    breadcrumbs.forEach((crumb, i) => {
        // Separator
        const sep = document.createElement("span");
        sep.className = "breadcrumb-sep";
        sep.textContent = "›";
        breadcrumbBar.appendChild(sep);

        const crumbEl = document.createElement("span");
        const isLast = i === breadcrumbs.length - 1;
        crumbEl.className = `breadcrumb-item${isLast ? " active" : ""}`;
        crumbEl.textContent = crumb.name;
        if (!isLast) {
            crumbEl.addEventListener("click", () => navigateToFolder(crumb.id, crumb.name));
        }
        breadcrumbBar.appendChild(crumbEl);
    });
}

// ══════════════════════════════════════════════
//  Folders
// ══════════════════════════════════════════════
async function loadFolders() {
    try {
        const url = currentFolderId !== null
            ? `/api/folders?parent_id=${currentFolderId}`
            : `/api/folders`;
        const res = await fetch(url);
        if (res.status === 401) return showLoginScreen();
        const folders = await res.json();

        folderList.innerHTML = "";

        if (folders.length === 0 && currentFolderId === null) {
            // Show a placeholder for the root
            const li = document.createElement("li");
            li.className = "folder-item no-folders";
            li.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <span class="folder-name" style="color: var(--text-tertiary)">No folders yet</span>
            `;
            folderList.appendChild(li);
        }

        folders.forEach(f => {
            const li = document.createElement("li");
            li.className = "folder-item";
            li.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <span class="folder-name">${escapeHtml(f.name)}</span>
                <button class="btn-icon folder-more" onclick="event.stopPropagation(); showFolderMenu(event, ${f.id}, '${escapeAttr(f.name)}')" title="Options">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>
                    </svg>
                </button>
            `;
            li.addEventListener("click", () => navigateToFolder(f.id, f.name));
            folderList.appendChild(li);
        });

        loadFiles();
    } catch (err) {
        console.error("Failed to load folders:", err);
    }
}

// ── Folder context menu ──
function showFolderMenu(event, folderId, folderName) {
    contextMenuFolderId = folderId;
    contextMenuFolderName = folderName;
    contextMenu.classList.remove("hidden");
    contextMenu.style.top = event.clientY + "px";
    contextMenu.style.left = event.clientX + "px";
}

document.addEventListener("click", () => {
    contextMenu.classList.add("hidden");
});

async function renameFolderAction() {
    contextMenu.classList.add("hidden");
    const newName = prompt(`Rename folder "${contextMenuFolderName}" to:`, contextMenuFolderName);
    if (!newName || newName.trim() === contextMenuFolderName) return;

    try {
        const res = await fetch(`/api/folders/${contextMenuFolderId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName.trim() }),
        });
        if (!res.ok) {
            const data = await res.json();
            alert(data.detail || "Rename failed");
            return;
        }
        loadFolders();
    } catch (err) {
        alert("Failed to rename folder: " + err.message);
    }
}

async function deleteFolderAction() {
    contextMenu.classList.add("hidden");
    if (!confirm(`Delete folder "${contextMenuFolderName}" and ALL its files and sub-folders?`)) return;

    try {
        const res = await fetch(`/api/folders/${contextMenuFolderId}`, {
            method: "DELETE",
        });
        if (!res.ok) {
            const data = await res.json();
            alert(data.detail || "Delete failed");
            return;
        }
        loadFolders();
    } catch (err) {
        alert("Failed to delete folder: " + err.message);
    }
}

// ── Create folder modal ──
function showCreateFolderModal() {
    if (currentFolderId !== null) {
        modalTitle.textContent = `New Sub-folder in "${currentFolderName}"`;
    } else {
        modalTitle.textContent = "New Folder";
    }
    modalInput.value = "";
    modalError.classList.add("hidden");
    modalConfirm.textContent = "Create";
    modalOverlay.classList.remove("hidden");
    modalInput.focus();
}

function closeModal() {
    modalOverlay.classList.add("hidden");
}

modalInput.addEventListener("keydown", (e) => { if (e.key === "Enter") confirmModal(); });

async function confirmModal() {
    const name = modalInput.value.trim();
    if (!name) {
        modalError.textContent = "Folder name is required";
        modalError.classList.remove("hidden");
        return;
    }

    try {
        const body = { name };
        if (currentFolderId !== null) {
            body.parent_id = currentFolderId;
        }

        const res = await fetch("/api/folders", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) {
            modalError.textContent = data.detail || "Failed to create folder";
            modalError.classList.remove("hidden");
            return;
        }
        closeModal();
        loadFolders();
    } catch (err) {
        modalError.textContent = err.message;
        modalError.classList.remove("hidden");
    }
}

// ══════════════════════════════════════════════
//  Files
// ══════════════════════════════════════════════
async function loadFiles() {
    // Only show files if we are inside a folder (not at root level)
    if (currentFolderId === null) {
        filesTbody.innerHTML = "";
        emptyState.classList.add("hidden");
        filesTable.classList.add("hidden");
        return;
    }

    try {
        const res = await fetch(`/api/folders/${currentFolderId}/files`);
        if (res.status === 401) return showLoginScreen();
        const files = await res.json();

        filesTbody.innerHTML = "";

        if (files.length === 0) {
            emptyState.classList.remove("hidden");
            filesTable.classList.add("hidden");
        } else {
            emptyState.classList.add("hidden");
            filesTable.classList.remove("hidden");

            files.forEach(file => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td>
                        <div class="file-name-cell">
                            <div class="file-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                                    <polyline points="14 2 14 8 20 8"/>
                                </svg>
                            </div>
                            <span class="file-name">${escapeHtml(file.name)}</span>
                        </div>
                    </td>
                    <td class="col-size">${formatBytes(file.size)}</td>
                    <td>
                        <div class="actions">
                            <button class="btn-action download" onclick="downloadFile('${escapeAttr(file.id)}')">Download</button>
                            <button class="btn-action delete" onclick="deleteFile('${escapeAttr(file.id)}')">Delete</button>
                        </div>
                    </td>
                `;
                filesTbody.appendChild(tr);
            });
        }
    } catch (err) {
        console.error("Failed to load files:", err);
    }
}

// ── Upload ──
function triggerUpload() {
    if (currentFolderId === null) {
        alert("Please navigate into a folder first before uploading files.");
        return;
    }
    fileInput.click();
}

fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) handleFiles(e.target.files);
    fileInput.value = "";
});

function setupDragDrop() {
    const mainContent = document.querySelector(".main-content");

    mainContent.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (currentFolderId !== null) {
            dropZone.classList.add("visible", "drag-over");
        }
    });

    mainContent.addEventListener("dragleave", (e) => {
        if (!mainContent.contains(e.relatedTarget)) {
            dropZone.classList.remove("visible", "drag-over");
        }
    });

    mainContent.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("visible", "drag-over");
        if (currentFolderId === null) {
            alert("Please navigate into a folder first before uploading files.");
            return;
        }
        if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
    });
}

async function handleFiles(files) {
    for (let i = 0; i < files.length; i++) {
        await uploadFile(files[i]);
    }
}

async function uploadFile(file) {
    progressCont.classList.remove("hidden");
    uploadFilename.textContent = `Uploading ${file.name}...`;
    uploadPercent.textContent = "0%";
    progressFill.style.width = "0%";

    const formData = new FormData();
    formData.append("file", file);

    try {
        await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            xhr.upload.addEventListener("progress", (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 100);
                    progressFill.style.width = pct + "%";
                    uploadPercent.textContent = pct + "%";
                }
            });

            xhr.addEventListener("load", () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    progressFill.style.width = "100%";
                    uploadPercent.textContent = "100%";
                    uploadFilename.textContent = `Uploaded ${file.name} ✓`;
                    resolve();
                } else {
                    try {
                        const err = JSON.parse(xhr.responseText);
                        reject(new Error(err.detail || "Upload failed"));
                    } catch (_) {
                        reject(new Error("Upload failed"));
                    }
                }
            });

            xhr.addEventListener("error", () => reject(new Error("Network error")));

            xhr.open("POST", `/api/folders/${currentFolderId}/upload`);
            xhr.send(formData);
        });

        setTimeout(() => {
            progressCont.classList.add("hidden");
            progressFill.style.width = "0%";
        }, 2000);

        loadFiles();
    } catch (err) {
        uploadFilename.textContent = `Error: ${err.message}`;
        progressFill.style.background = "var(--red)";
        setTimeout(() => {
            progressCont.classList.add("hidden");
            progressFill.style.background = "";
        }, 4000);
    }
}

// ── Download ──
async function downloadFile(fileId) {
    const url = `/api/folders/${currentFolderId}/download/${encodeURIComponent(fileId)}`;
    
    // Show a temporary status
    const statusEl = document.createElement("div");
    statusEl.style.cssText = "position:fixed;bottom:20px;right:20px;padding:12px 16px;background:var(--accent);color:#fff;border-radius:8px;z-index:9999;font-size:0.85rem;";
    statusEl.textContent = `Downloading ${fileId}...`;
    document.body.appendChild(statusEl);

    try {
        const res = await fetch(url);
        if (!res.ok) {
            const text = await res.text();
            throw new Error(`Download failed: ${res.status} ${res.statusText} — ${text}`);
        }
        const blob = await res.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = fileId;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
        statusEl.textContent = `Downloaded ${fileId} ✓`;
        statusEl.style.background = "var(--green)";
    } catch (err) {
        statusEl.textContent = `Error: ${err.message}`;
        statusEl.style.background = "var(--red)";
        console.error("Download error:", err);
    }
    setTimeout(() => statusEl.remove(), 4000);
}

// ── Delete ──
async function deleteFile(fileId) {
    if (!confirm(`Delete "${fileId}"?`)) return;

    try {
        const res = await fetch(
            `/api/folders/${currentFolderId}/files/${encodeURIComponent(fileId)}`,
            { method: "DELETE" }
        );
        if (res.ok) {
            loadFiles();
        } else {
            const data = await res.json();
            alert(data.detail || "Failed to delete file");
        }
    } catch (err) {
        alert("Error deleting file: " + err.message);
    }
}

// ══════════════════════════════════════════════
//  Sidebar toggle (mobile)
// ══════════════════════════════════════════════
function toggleSidebar() {
    $("sidebar").classList.toggle("open");
}

// ══════════════════════════════════════════════
//  Rebuild Index
// ══════════════════════════════════════════════
async function rebuildIndex() {
    const btn = event.target.closest('button');
    const originalText = btn.innerHTML;
    btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin">
            <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Rebuilding...
    `;
    btn.disabled = true;

    try {
        const res = await fetch("/api/debug/rebuild", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Rebuild failed");
        
        alert(`Rebuild complete: ${data.summary.files} files, ${data.summary.folders} folders`);
        loadFolders();
    } catch (err) {
        alert("Rebuild failed: " + err.message);
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// ══════════════════════════════════════════════
//  Utilities
// ══════════════════════════════════════════════
function formatBytes(bytes, decimals = 1) {
    if (!+bytes) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/'/g, "\\'").replace(/"/g, '\\"');
}
