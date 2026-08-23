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

const loginScreen = $("login-screen");
const driveScreen = $("drive-screen");
const passwordInput = $("password-input");
const loginBtn = $("login-btn");
const loginError = $("login-error");

const folderList = $("folder-list");
const folderTitle = $("current-folder-title");
const filesTbody = $("files-tbody");
const filesTable = $("files-table");
const emptyState = $("empty-state");
const userInfo = $("user-info");
const dropZone = $("drop-zone");
const fileInput = $("file-input");
const progressCont = $("upload-progress-container");
const progressFill = $("upload-progress-fill");
const uploadFilename = $("upload-filename");
const uploadPercent = $("upload-percent");
const modalOverlay = $("modal-overlay");
const modalInput = $("modal-input");
const modalTitle = $("modal-title");
const modalError = $("modal-error");
const modalConfirm = $("modal-confirm-btn");
const contextMenu = $("context-menu");
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
    } catch (_) { }
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
    } catch (_) { }
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
                const previewable = isPreviewable(file.id);
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
                            ${previewable ? `<button class="btn-action preview" onclick="previewFile('${escapeAttr(file.id)}')" title="Preview">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                    <circle cx="12" cy="12" r="3"/>
                                </svg>
                                Preview
                            </button>` : ''}
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
                    // Refresh only once the server has actually confirmed the upload
                    loadFiles();
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

// ── Preview ──
function isPreviewable(fileId) {
    const ext = fileId.substring(fileId.lastIndexOf('.')).toLowerCase();
    const previewable = [
        // Images
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico',
        // Videos
        '.mp4', '.webm', '.mov', '.mkv',
        // Audio
        '.mp3', '.wav', '.ogg', '.m4a', '.flac',
        // Documents
        '.pdf', '.txt', '.md', '.json', '.xml', '.html', '.css', '.js',
    ];
    return previewable.includes(ext);
}

function previewFile(fileId) {
    if (!isPreviewable(fileId)) {
        alert('This file type cannot be previewed. Please download it instead.');
        return;
    }

    const previewUrl = `/api/folders/${currentFolderId}/preview/${encodeURIComponent(fileId)}`;
    openPreviewModal(fileId, previewUrl);
}

function openPreviewModal(fileId, previewUrl) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay preview-overlay';
    modal.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;background:rgba(0,0,0,0.85);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);display:flex;align-items:center;justify-content:center;z-index:2000;padding:16px;';
    modal.onclick = (e) => { if (e.target === modal) closePreviewModal(modal); };

    const ext = fileId.substring(fileId.lastIndexOf('.')).toLowerCase();
    const isImage = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico', '.svg'].includes(ext);
    let contentHtml = '';
    let bodyClass = '';
    let toolbarHtml = '';

    if (isImage) {
        toolbarHtml = `
            <div class="preview-toolbar">
                <button class="preview-tool-btn" id="preview-zoom-out" title="Zoom Out (-)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>
                    </svg>
                </button>
                <span class="preview-zoom-label" id="preview-zoom-label" title="Click to Reset (100%)">100%</span>
                <button class="preview-tool-btn" id="preview-zoom-in" title="Zoom In (+)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
                    </svg>
                </button>
                <div class="preview-divider"></div>
                <button class="preview-tool-btn" id="preview-zoom-fit" title="Fit to Screen / Toggle 2.5x (F)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
                    </svg>
                </button>
                <button class="preview-tool-btn" id="preview-rotate" title="Rotate 90° (R)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                    </svg>
                </button>
                <button class="preview-tool-btn" id="preview-reset" title="Reset View (0)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>
                    </svg>
                </button>
            </div>
        `;
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.88rem;color:var(--text-secondary);">Retrieving file from Telegram...</p>
            </div>
            <div class="preview-image-viewport" id="preview-image-viewport" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;margin:0 auto;overflow:hidden;position:relative;cursor:grab;user-select:none;touch-action:none;">
                <div class="preview-image-wrapper" id="preview-image-wrapper" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;margin:0 auto;text-align:center;transform-origin:center center;">
                    <img id="preview-target-img" src="${previewUrl}" alt="${escapeHtml(fileId)}" draggable="false"
                        onload="document.getElementById('preview-loader')?.remove()"
                        onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')"
                        style="max-width:calc(88vw - 60px);max-height:calc(88vh - 110px);width:auto;height:auto;object-fit:contain;display:block;margin:auto;border-radius:6px;box-shadow:0 16px 50px rgba(0,0,0,0.75);">
                </div>
                <div class="preview-hints">
                    <span><kbd>Wheel</kbd> Zoom</span>
                    <span><kbd>Drag</kbd> Pan</span>
                    <span><kbd>Dbl-Click</kbd> Zoom</span>
                    <span><kbd>F</kbd> Fit</span>
                    <span><kbd>Esc</kbd> Close</span>
                </div>
            </div>
        `;
    } else if (['.mp4', '.webm', '.mov', '.mkv'].includes(ext)) {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.88rem;color:var(--text-secondary);">Retrieving video from Telegram...</p>
            </div>
            <div class="preview-media-container" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;padding:24px;">
                <video controls autoplay playsinline
                    onloadeddata="document.getElementById('preview-loader')?.remove()"
                    onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')"
                    style="max-width:100%;max-height:100%;">
                    <source src="${previewUrl}" type="${getMediaType(ext)}">
                    Your browser does not support video playback.
                </video>
            </div>
        `;
    } else if (['.mp3', '.wav', '.ogg', '.m4a', '.flac'].includes(ext)) {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.88rem;color:var(--text-secondary);">Retrieving audio from Telegram...</p>
            </div>
            <div class="preview-media-container" style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;padding:24px;">
                <audio controls autoplay
                    onloadeddata="document.getElementById('preview-loader')?.remove()"
                    onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')"
                    style="width:100%;max-width:520px;">
                    <source src="${previewUrl}" type="${getMediaType(ext)}">
                    Your browser does not support audio playback.
                </audio>
            </div>
        `;
    } else if (['.pdf'].includes(ext)) {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.88rem;color:var(--text-secondary);">Retrieving PDF from Telegram...</p>
            </div>
            <iframe class="preview-pdf-iframe" src="${previewUrl}"
                onload="document.getElementById('preview-loader')?.remove()"
                onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')"
                style="width:100%;height:100%;border:none;"></iframe>
        `;
    } else if (['.txt', '.md', '.json', '.xml', '.html', '.css', '.js'].includes(ext)) {
        bodyClass = 'scrollable';
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.88rem;color:var(--text-secondary);">Retrieving file from Telegram...</p>
            </div>
            <pre class="preview-code-container"><code id="preview-text-content"></code></pre>
        `;
        fetch(previewUrl)
            .then(async r => {
                document.getElementById('preview-loader')?.remove();
                if (!r.ok) {
                    const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
                    throw new Error(err.detail || `HTTP ${r.status}`);
                }
                return r.text();
            })
            .then(text => {
                const el = document.getElementById('preview-text-content');
                if (el) el.textContent = text;
            })
            .catch((err) => {
                document.getElementById('preview-loader')?.remove();
                const el = document.getElementById('preview-text-content');
                if (el) {
                    const parent = el.closest('.preview-dialog')?.querySelector('.modal-body');
                    if (parent) {
                        parent.innerHTML = `
                            <div class="preview-error-box">
                                <svg class="preview-error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                                </svg>
                                <h4 style="margin-bottom:8px;">Failed to Load Preview</h4>
                                <p style="font-size:0.88rem;color:var(--text-secondary);margin-bottom:16px;">${escapeHtml(err.message)}</p>
                            </div>
                        `;
                    }
                }
            });
    }

    modal.innerHTML = `
        <div class="preview-dialog" style="display:flex;flex-direction:column;width:88vw;max-width:1600px;height:88vh;max-height:94vh;padding:0;margin:auto;overflow:hidden;background:var(--bg-primary);border:1px solid var(--surface-border);border-radius:var(--radius-xl);box-shadow:var(--shadow-lg),0 0 70px rgba(0,0,0,0.85);" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="preview-header-left">
                    <span class="preview-badge">${escapeHtml(ext.replace('.', '') || 'FILE')}</span>
                    <h3 class="preview-title" title="${escapeAttr(fileId)}">${escapeHtml(fileId)}</h3>
                </div>
                ${toolbarHtml}
                <div class="preview-header-actions">
                    <button class="btn-secondary btn-sm" onclick="downloadFile('${escapeAttr(fileId)}')">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
                        </svg>
                        Download
                    </button>
                    <button class="btn-icon" onclick="closePreviewModal(this.closest('.modal-overlay'))" title="Close (Esc)">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="modal-body ${bodyClass}" style="flex:1 1 0%;min-height:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;margin:0;padding:0;overflow:hidden;position:relative;background:radial-gradient(circle at 50% 50%,#151522 0%,#08080c 100%);text-align:center;">
                ${contentHtml}
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    requestAnimationFrame(() => modal.style.opacity = '1');

    // Initialize interactive Zoom & Pan if image
    if (isImage) {
        const viewport = modal.querySelector('#preview-image-viewport');
        const wrapper = modal.querySelector('#preview-image-wrapper');
        const label = modal.querySelector('#preview-zoom-label');
        const btnIn = modal.querySelector('#preview-zoom-in');
        const btnOut = modal.querySelector('#preview-zoom-out');
        const btnFit = modal.querySelector('#preview-zoom-fit');
        const btnReset = modal.querySelector('#preview-reset');
        const btnRotate = modal.querySelector('#preview-rotate');

        modal._cleanup = setupImageZoomPan({
            modal,
            viewport,
            wrapper,
            label,
            btnIn,
            btnOut,
            btnFit,
            btnReset,
            btnRotate,
        });
    } else {
        const onKeyDown = (e) => {
            if (e.key === 'Escape') closePreviewModal(modal);
        };
        window.addEventListener('keydown', onKeyDown);
        modal._cleanup = () => window.removeEventListener('keydown', onKeyDown);
    }
}

function setupImageZoomPan({ modal, viewport, wrapper, label, btnIn, btnOut, btnFit, btnReset, btnRotate }) {
    let scale = 1.0;
    const minScale = 0.15;
    const maxScale = 10.0;
    let posX = 0;
    let posY = 0;
    let rotation = 0;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialPinchDist = 0;
    let initialPinchScale = 1.0;

    function applyTransform(animate = false) {
        if (animate) {
            wrapper.classList.remove('no-transition');
        } else {
            wrapper.classList.add('no-transition');
        }
        wrapper.style.transform = `translate3d(${posX}px, ${posY}px, 0) scale(${scale}) rotate(${rotation}deg)`;
        if (label) {
            label.textContent = `${Math.round(scale * 100)}%`;
        }
    }

    function zoomBy(factor, clientX, clientY, animate = true) {
        const oldScale = scale;
        const newScale = Math.min(maxScale, Math.max(minScale, oldScale * factor));
        if (Math.abs(newScale - oldScale) < 0.001) return;

        if (clientX !== undefined && clientY !== undefined && viewport) {
            const rect = viewport.getBoundingClientRect();
            const centerViewportX = rect.left + rect.width / 2;
            const centerViewportY = rect.top + rect.height / 2;
            const relX = clientX - centerViewportX;
            const relY = clientY - centerViewportY;

            // Zoom centered precisely on mouse pointer
            posX = relX - (relX - posX) * (newScale / oldScale);
            posY = relY - (relY - posY) * (newScale / oldScale);
        } else {
            posX = posX * (newScale / oldScale);
            posY = posY * (newScale / oldScale);
        }

        scale = newScale;
        applyTransform(animate);
    }

    function resetView(animate = true) {
        scale = 1.0;
        posX = 0;
        posY = 0;
        rotation = 0;
        applyTransform(animate);
    }

    function toggleFitOrZoom(clientX, clientY) {
        if (Math.abs(scale - 1.0) > 0.1 || posX !== 0 || posY !== 0) {
            resetView(true);
        } else {
            zoomBy(2.5, clientX, clientY, true);
        }
    }

    function rotate(animate = true) {
        rotation = (rotation + 90) % 360;
        applyTransform(animate);
    }

    // Button event listeners
    if (btnIn) btnIn.onclick = () => zoomBy(1.3, undefined, undefined, true);
    if (btnOut) btnOut.onclick = () => zoomBy(1 / 1.3, undefined, undefined, true);
    if (btnReset) btnReset.onclick = () => resetView(true);
    if (label) label.onclick = () => resetView(true);
    if (btnFit) btnFit.onclick = () => toggleFitOrZoom();
    if (btnRotate) btnRotate.onclick = () => rotate(true);

    // Mouse Wheel zoom
    const onWheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 0.87;
        zoomBy(factor, e.clientX, e.clientY, false);
    };
    viewport.addEventListener('wheel', onWheel, { passive: false });

    // Double Click
    const onDblClick = (e) => {
        e.preventDefault();
        toggleFitOrZoom(e.clientX, e.clientY);
    };
    viewport.addEventListener('dblclick', onDblClick);

    // Mouse Drag / Pan
    const onMouseDown = (e) => {
        if (e.button !== 0) return;
        isDragging = true;
        startX = e.clientX - posX;
        startY = e.clientY - posY;
        viewport.classList.add('is-dragging');
        wrapper.classList.add('no-transition');
        e.preventDefault();
    };
    viewport.addEventListener('mousedown', onMouseDown);

    const onMouseMove = (e) => {
        if (!isDragging) return;
        posX = e.clientX - startX;
        posY = e.clientY - startY;
        applyTransform(false);
    };
    window.addEventListener('mousemove', onMouseMove);

    const onMouseUp = () => {
        if (isDragging) {
            isDragging = false;
            viewport.classList.remove('is-dragging');
        }
    };
    window.addEventListener('mouseup', onMouseUp);

    // Touch support (Pinch zoom & touch pan)
    const onTouchStart = (e) => {
        if (e.touches.length === 1) {
            isDragging = true;
            startX = e.touches[0].clientX - posX;
            startY = e.touches[0].clientY - posY;
            wrapper.classList.add('no-transition');
        } else if (e.touches.length === 2) {
            isDragging = false;
            const dx = e.touches[0].clientX - e.touches[1].clientX;
            const dy = e.touches[0].clientY - e.touches[1].clientY;
            initialPinchDist = Math.hypot(dx, dy);
            initialPinchScale = scale;
        }
    };

    const onTouchMove = (e) => {
        if (e.touches.length === 1 && isDragging) {
            e.preventDefault();
            posX = e.touches[0].clientX - startX;
            posY = e.touches[0].clientY - startY;
            applyTransform(false);
        } else if (e.touches.length === 2 && initialPinchDist > 0) {
            e.preventDefault();
            const dx = e.touches[0].clientX - e.touches[1].clientX;
            const dy = e.touches[0].clientY - e.touches[1].clientY;
            const dist = Math.hypot(dx, dy);
            const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
            const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            const factor = (dist / initialPinchDist) * (initialPinchScale / scale);
            zoomBy(factor, midX, midY, false);
        }
    };

    const onTouchEnd = () => {
        isDragging = false;
        initialPinchDist = 0;
    };

    viewport.addEventListener('touchstart', onTouchStart, { passive: false });
    viewport.addEventListener('touchmove', onTouchMove, { passive: false });
    viewport.addEventListener('touchend', onTouchEnd);

    // Keyboard Shortcuts
    const onKeyDown = (e) => {
        if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;

        if (e.key === 'Escape') {
            closePreviewModal(modal);
        } else if (e.key === '+' || e.key === '=') {
            e.preventDefault();
            zoomBy(1.3, undefined, undefined, true);
        } else if (e.key === '-' || e.key === '_') {
            e.preventDefault();
            zoomBy(1 / 1.3, undefined, undefined, true);
        } else if (e.key === '0' || e.key === 'f' || e.key === 'F') {
            e.preventDefault();
            resetView(true);
        } else if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            rotate(true);
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            posX += 40;
            applyTransform(true);
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            posX -= 40;
            applyTransform(true);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            posY += 40;
            applyTransform(true);
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            posY -= 40;
            applyTransform(true);
        }
    };
    window.addEventListener('keydown', onKeyDown);

    // Initial transform
    applyTransform(false);

    // Return cleanup function
    return () => {
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
        window.removeEventListener('keydown', onKeyDown);
        viewport.removeEventListener('wheel', onWheel);
        viewport.removeEventListener('dblclick', onDblClick);
        viewport.removeEventListener('mousedown', onMouseDown);
        viewport.removeEventListener('touchstart', onTouchStart);
        viewport.removeEventListener('touchmove', onTouchMove);
        viewport.removeEventListener('touchend', onTouchEnd);
    };
}

function closePreviewModal(modal) {
    if (!modal) return;
    if (typeof modal._cleanup === 'function') {
        try { modal._cleanup(); } catch (_) { }
    }
    modal.style.opacity = '0';
    setTimeout(() => modal.remove(), 200);
}

function handlePreviewLoadError(el, fileId) {
    document.getElementById('preview-loader')?.remove();
    const modalBody = el ? (el.closest('.modal-body') || document.querySelector('.preview-dialog .modal-body')) : document.querySelector('.preview-dialog .modal-body');
    if (modalBody) {
        modalBody.innerHTML = `
            <div class="preview-error-box">
                <svg class="preview-error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <h4 style="margin-bottom:8px;font-size:1.1rem;font-weight:600;">Unable to Load Preview</h4>
                <p style="font-size:0.88rem;color:var(--text-secondary);margin-bottom:20px;max-width:380px;line-height:1.5;">
                    The file message could not be retrieved from Telegram. The file may have been uploaded to a previous channel or deleted.
                </p>
                <div style="display:flex;gap:10px;justify-content:center;">
                    <button class="btn-primary btn-sm" onclick="downloadFile('${escapeAttr(fileId)}')">
                        Try Downloading
                    </button>
                    <button class="btn-secondary btn-sm" onclick="closePreviewModal(this.closest('.modal-overlay'))">
                        Close
                    </button>
                </div>
            </div>
        `;
    }
}

function getMediaType(ext) {
    const types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime',
        '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.m4a': 'audio/mp4',
        '.flac': 'audio/flac',
    };
    return types[ext] || 'application/octet-stream';
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
    // Use the stable button reference instead of the implicit global `event`,
    // which is undefined when this runs outside a direct user-gesture stack.
    const btn = document.getElementById("rebuild-index-btn");
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
    // Escapes for safe interpolation into a double-quoted HTML attribute.
    // & first so we don't double-encode the entities below; then quotes and
    // angle brackets (covers both attribute context and inline JS-in-attr).
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}
