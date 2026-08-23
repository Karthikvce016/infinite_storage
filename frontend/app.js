/**
 * app.js — Telegram Drive (Obsidian OS File Manager Edition)
 *
 * Features:
 * - 3-Pane Modern OS / File Manager Grid Architecture
 * - Dual View: Rich Visual Card Grid + Streamlined List Table
 * - Interactive Details Inspector Sidebar
 * - Real-time Category Filtering & Unified Search
 * - Floating Action Dock
 * - Complete Fullscreen Lightbox Previews (Image Pan/Zoom/Rotate, Video/Audio Streaming, PDF & Code)
 */

// ══════════════════════════════════════════════
//  State
// ══════════════════════════════════════════════
let currentFolderId = null;        // null = root
let currentFolderName = "Root";
let breadcrumbs = [];              // [{id, name}, ...]
let allFiles = [];                 // Full file list for current folder
let allFolders = [];               // Full subfolder list for current folder
let selectedFile = null;           // Currently selected file object in inspector
let viewMode = "grid";             // "grid" | "list"
let currentCategory = "all";       // "all" | "images" | "video" | "docs" | "audio" | "archives"
let searchQuery = "";
let sortKey = "name";              // "name" | "size" | "type"
let sortAsc = true;

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
const itemsCountLabel = $("items-count-label");
const rootCountBadge = $("root-count-badge");

const subfoldersContainer = $("subfolders-container");
const subfoldersGrid = $("subfolders-grid");

const filesCardGrid = $("files-card-grid");
const filesTableWrap = $("files-table-wrap");
const filesTbody = $("files-tbody");
const emptyState = $("empty-state");

const userInfo = $("user-info");
const dropZone = $("drop-zone");
const fileInput = $("file-input");

const progressCont = $("upload-progress-container");
const progressFill = $("upload-progress-fill");
const uploadFilename = $("upload-filename");
const uploadPercent = $("upload-percent");

const inspectorPane = $("inspector-pane");
const inspectorContent = $("inspector-content");
const inspectorToggleBtn = $("inspector-toggle-btn");

const modalOverlay = $("modal-overlay");
const modalInput = $("modal-input");
const modalTitle = $("modal-title");
const modalError = $("modal-error");
const modalConfirm = $("modal-confirm-btn");
const contextMenu = $("context-menu");
const breadcrumbBar = $("breadcrumb-bar");
const searchInput = $("search-input");
const searchClearBtn = $("search-clear-btn");

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

    if (user && userInfo) {
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
    const arrow = btn.querySelector(".btn-arrow");
    if (loading) {
        if (text) text.classList.add("hidden");
        if (arrow) arrow.classList.add("hidden");
        if (loader) loader.classList.remove("hidden");
        btn.disabled = true;
    } else {
        if (text) text.classList.remove("hidden");
        if (arrow) arrow.classList.remove("hidden");
        if (loader) loader.classList.add("hidden");
        btn.disabled = false;
    }
}

passwordInput?.addEventListener("keydown", (e) => { if (e.key === "Enter") login(); });

// ══════════════════════════════════════════════
//  Navigation — Hierarchical Folder Browsing
// ══════════════════════════════════════════════
async function navigateToFolder(folderId, folderName) {
    currentFolderId = folderId;
    currentFolderName = folderName || "Root";
    selectedFile = null;
    searchQuery = "";
    if (searchInput) searchInput.value = "";
    if (searchClearBtn) searchClearBtn.classList.add("hidden");

    // Quick root indicator
    const quickRoot = $("quick-root-item");
    if (quickRoot) {
        if (folderId === null) quickRoot.classList.add("active");
        else quickRoot.classList.remove("active");
    }

    // Breadcrumbs
    if (folderId === null) {
        breadcrumbs = [];
    } else {
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
    if (folderTitle) folderTitle.textContent = currentFolderName;
    await loadFolders();
    updateInspector();
}

function renderBreadcrumbs() {
    if (!breadcrumbBar) return;
    breadcrumbBar.innerHTML = "";

    const rootCrumb = document.createElement("span");
    rootCrumb.className = `breadcrumb-item${breadcrumbs.length === 0 ? " active" : ""}`;
    rootCrumb.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
        </svg>
        Root
    `;
    rootCrumb.addEventListener("click", () => navigateToFolder(null, "Root"));
    breadcrumbBar.appendChild(rootCrumb);

    breadcrumbs.forEach((crumb, i) => {
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
        allFolders = await res.json();

        // Render Sidebar tree
        if (folderList) {
            folderList.innerHTML = "";
            if (allFolders.length === 0 && currentFolderId === null) {
                const li = document.createElement("li");
                li.className = "folder-item no-folders";
                li.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                    </svg>
                    <span class="folder-name" style="color: var(--text-3);font-size:0.8rem;">No folders created</span>
                `;
                folderList.appendChild(li);
            } else {
                allFolders.forEach(f => {
                    const li = document.createElement("li");
                    li.className = `folder-item${currentFolderId === f.id ? " active" : ""}`;
                    li.innerHTML = `
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
            }
        }

        // Render Sub-folders Grid on canvas
        if (subfoldersContainer && subfoldersGrid) {
            if (allFolders.length > 0) {
                subfoldersContainer.classList.remove("hidden");
                subfoldersGrid.innerHTML = "";
                allFolders.forEach(f => {
                    const card = document.createElement("div");
                    card.className = "folder-card";
                    card.innerHTML = `
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                        </svg>
                        <span class="folder-card-title">${escapeHtml(f.name)}</span>
                    `;
                    card.addEventListener("click", () => navigateToFolder(f.id, f.name));
                    subfoldersGrid.appendChild(card);
                });
            } else {
                subfoldersContainer.classList.add("hidden");
            }
        }

        await loadFiles();
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
    if (contextMenu) contextMenu.classList.add("hidden");
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
    if (!confirm(`Delete folder "${contextMenuFolderName}" and ALL its contents?`)) return;

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
        modalTitle.textContent = "New Vault Folder";
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

modalInput?.addEventListener("keydown", (e) => { if (e.key === "Enter") confirmModal(); });

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
//  Files Rendering & View Modes
// ══════════════════════════════════════════════
async function loadFiles() {
    if (currentFolderId === null) {
        allFiles = [];
        renderFilesView();
        if (rootCountBadge) rootCountBadge.textContent = allFolders.length;
        return;
    }

    try {
        const res = await fetch(`/api/folders/${currentFolderId}/files`);
        if (res.status === 401) return showLoginScreen();
        allFiles = await res.json();
        renderFilesView();
    } catch (err) {
        console.error("Failed to load files:", err);
    }
}

function getFilteredFiles() {
    return allFiles.filter(file => {
        // Search filter
        if (searchQuery && !file.name.toLowerCase().includes(searchQuery.toLowerCase())) {
            return false;
        }
        // Category filter
        if (currentCategory === "all") return true;
        const ext = getFileExt(file.name);
        if (currentCategory === "images") return ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'].includes(ext);
        if (currentCategory === "video") return ['.mp4', '.webm', '.mov', '.mkv', '.avi', '.flv'].includes(ext);
        if (currentCategory === "docs") return ['.pdf', '.txt', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.md', '.json', '.csv'].includes(ext);
        if (currentCategory === "audio") return ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'].includes(ext);
        if (currentCategory === "archives") return ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.iso'].includes(ext);
        return true;
    }).sort((a, b) => {
        let valA = a[sortKey];
        let valB = b[sortKey];
        if (sortKey === "type") {
            valA = getFileExt(a.name);
            valB = getFileExt(b.name);
        }
        if (typeof valA === "string") {
            return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }
        return sortAsc ? valA - valB : valB - valA;
    });
}

function renderFilesView() {
    const filtered = getFilteredFiles();
    if (itemsCountLabel) itemsCountLabel.textContent = `${filtered.length} item${filtered.length === 1 ? '' : 's'}`;

    if (filtered.length === 0 && currentFolderId !== null && allFolders.length === 0) {
        emptyState.classList.remove("hidden");
        filesCardGrid.classList.add("hidden");
        filesTableWrap.classList.add("hidden");
        return;
    } else {
        emptyState.classList.add("hidden");
    }

    if (viewMode === "grid") {
        filesCardGrid.classList.remove("hidden");
        filesTableWrap.classList.add("hidden");
        renderCardGrid(filtered);
    } else {
        filesCardGrid.classList.add("hidden");
        filesTableWrap.classList.remove("hidden");
        renderListTable(filtered);
    }
}

function renderCardGrid(files) {
    filesCardGrid.innerHTML = "";
    files.forEach(file => {
        const card = document.createElement("div");
        const isSelected = selectedFile && selectedFile.id === file.id;
        card.className = `file-grid-card${isSelected ? " selected" : ""}`;

        const ext = getFileExt(file.name);
        const iconSvg = getFileIconSvg(ext);
        const previewable = isPreviewable(file.id);

        card.innerHTML = `
            <div class="card-thumb-box">
                ${iconSvg}
            </div>
            <div class="card-meta">
                <span class="card-filename" title="${escapeAttr(file.name)}">${escapeHtml(file.name)}</span>
                <div class="card-sub-info">
                    <span>${ext.toUpperCase().replace('.', '') || 'FILE'}</span>
                    <span>${formatBytes(file.size)}</span>
                </div>
            </div>
            <div class="card-actions-row" onclick="event.stopPropagation()">
                ${previewable ? `<button class="card-btn" onclick="previewFile('${escapeAttr(file.id)}')" title="Preview">View</button>` : ''}
                <button class="card-btn" onclick="downloadFile('${escapeAttr(file.id)}')" title="Download">Get</button>
                <button class="card-btn delete-btn" onclick="deleteFile('${escapeAttr(file.id)}')" title="Delete">✕</button>
            </div>
        `;

        card.addEventListener("click", () => {
            selectFile(file);
            document.querySelectorAll(".file-grid-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
        });

        card.addEventListener("dblclick", () => {
            if (previewable) previewFile(file.id);
            else downloadFile(file.id);
        });

        filesCardGrid.appendChild(card);
    });
}

function renderListTable(files) {
    filesTbody.innerHTML = "";
    files.forEach(file => {
        const tr = document.createElement("tr");
        const isSelected = selectedFile && selectedFile.id === file.id;
        if (isSelected) tr.classList.add("selected");

        const ext = getFileExt(file.name);
        const iconSvg = getFileIconSvg(ext);
        const previewable = isPreviewable(file.id);

        tr.innerHTML = `
            <td>
                <div class="file-name-cell">
                    <div class="file-icon-small">${iconSvg}</div>
                    <span class="file-name" title="${escapeAttr(file.name)}">${escapeHtml(file.name)}</span>
                </div>
            </td>
            <td class="col-type">${ext.toUpperCase().replace('.', '') || 'FILE'}</td>
            <td class="col-size">${formatBytes(file.size)}</td>
            <td>
                <div class="actions" onclick="event.stopPropagation()">
                    ${previewable ? `<button class="btn-action preview" onclick="previewFile('${escapeAttr(file.id)}')" title="Preview">Preview</button>` : ''}
                    <button class="btn-action download" onclick="downloadFile('${escapeAttr(file.id)}')">Download</button>
                    <button class="btn-action delete" onclick="deleteFile('${escapeAttr(file.id)}')">Delete</button>
                </div>
            </td>
        `;

        tr.addEventListener("click", () => {
            selectFile(file);
            document.querySelectorAll("#files-tbody tr").forEach(r => r.classList.remove("selected"));
            tr.classList.add("selected");
        });

        tr.addEventListener("dblclick", () => {
            if (previewable) previewFile(file.id);
            else downloadFile(file.id);
        });

        filesTbody.appendChild(tr);
    });
}

// ══════════════════════════════════════════════
//  Inspector Details Sidebar
// ══════════════════════════════════════════════
function selectFile(file) {
    selectedFile = file;
    updateInspector();
    // Auto-open inspector if collapsed
    if (inspectorPane.classList.contains("collapsed")) {
        inspectorPane.classList.remove("collapsed");
        inspectorToggleBtn.classList.add("active");
    }
}

function updateInspector() {
    if (!inspectorContent) return;

    if (!selectedFile) {
        inspectorContent.innerHTML = `
            <div class="inspector-empty">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
                <p>Select any file to inspect metadata, storage chunks, and actions.</p>
            </div>
        `;
        return;
    }

    const ext = getFileExt(selectedFile.name);
    const iconSvg = getFileIconSvg(ext);
    const previewable = isPreviewable(selectedFile.id);

    inspectorContent.innerHTML = `
        <div class="inspector-card-active">
            <div class="inspector-preview-box">
                ${iconSvg}
            </div>

            <div class="inspector-details-list">
                <div class="detail-row">
                    <span class="detail-k">Filename</span>
                    <span class="detail-v" title="${escapeAttr(selectedFile.name)}">${escapeHtml(selectedFile.name)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-k">File Size</span>
                    <span class="detail-v">${formatBytes(selectedFile.size)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-k">Extension</span>
                    <span class="detail-v">${ext.toUpperCase() || 'NONE'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-k">Storage</span>
                    <span class="detail-v" style="color:var(--emerald-bright)">Telegram Doc (Raw)</span>
                </div>
                <div class="detail-row">
                    <span class="detail-k">Compression</span>
                    <span class="detail-v">0% (Lossless)</span>
                </div>
            </div>

            <div class="inspector-actions-box">
                ${previewable ? `
                    <button class="inspector-action-btn primary" onclick="previewFile('${escapeAttr(selectedFile.id)}')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        Full Preview
                    </button>
                ` : ''}
                <button class="inspector-action-btn secondary" onclick="downloadFile('${escapeAttr(selectedFile.id)}')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Download File
                </button>
                <button class="inspector-action-btn danger" onclick="deleteFile('${escapeAttr(selectedFile.id)}')">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    Delete from Vault
                </button>
            </div>
        </div>
    `;
}

function toggleInspector() {
    inspectorPane.classList.toggle("collapsed");
    inspectorToggleBtn.classList.toggle("active");
}

function closeInspector() {
    inspectorPane.classList.add("collapsed");
    inspectorToggleBtn.classList.remove("active");
}

// ══════════════════════════════════════════════
//  Search & Filter Controls
// ══════════════════════════════════════════════
function handleSearch(val) {
    searchQuery = val.trim();
    if (searchClearBtn) {
        if (searchQuery) searchClearBtn.classList.remove("hidden");
        else searchClearBtn.classList.add("hidden");
    }
    renderFilesView();
}

function clearSearch() {
    if (searchInput) searchInput.value = "";
    handleSearch("");
}

function setCategoryFilter(category) {
    currentCategory = category;
    document.querySelectorAll(".category-filter-chips .chip").forEach(c => {
        if (c.textContent.toLowerCase() === category.toLowerCase() ||
            (category === "all" && c.textContent.toLowerCase() === "all") ||
            (category === "video" && c.textContent.toLowerCase() === "videos") ||
            (category === "docs" && c.textContent.toLowerCase() === "documents")) {
            c.classList.add("active");
        } else {
            c.classList.remove("active");
        }
    });
    renderFilesView();
}

function setViewMode(mode) {
    viewMode = mode;
    $("view-grid-btn")?.classList.toggle("active", mode === "grid");
    $("view-list-btn")?.classList.toggle("active", mode === "list");
    renderFilesView();
}

function sortFiles(key) {
    if (sortKey === key) {
        sortAsc = !sortAsc;
    } else {
        sortKey = key;
        sortAsc = true;
    }
    renderFilesView();
}

// ══════════════════════════════════════════════
//  File Uploading
// ══════════════════════════════════════════════
function triggerUpload() {
    if (currentFolderId === null) {
        alert("Please navigate into a vault folder first before uploading files.");
        return;
    }
    fileInput.click();
}

fileInput?.addEventListener("change", (e) => {
    if (e.target.files.length > 0) handleFiles(e.target.files);
    fileInput.value = "";
});

function setupDragDrop() {
    const mainContent = document.querySelector(".browser-pane");
    if (!mainContent) return;

    mainContent.addEventListener("dragover", (e) => {
        e.preventDefault();
        if (currentFolderId !== null) {
            dropZone.classList.add("drag-over");
        }
    });

    mainContent.addEventListener("dragleave", (e) => {
        if (!mainContent.contains(e.relatedTarget)) {
            dropZone.classList.remove("drag-over");
        }
    });

    mainContent.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
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

// ══════════════════════════════════════════════
//  File Download & Delete
// ══════════════════════════════════════════════
async function downloadFile(fileId) {
    const url = `/api/folders/${currentFolderId}/download/${encodeURIComponent(fileId)}`;

    const statusEl = document.createElement("div");
    statusEl.style.cssText = "position:fixed;bottom:24px;right:24px;padding:12px 18px;background:linear-gradient(135deg,var(--emerald),var(--emerald-dim));color:#061b14;border-radius:12px;font-weight:700;z-index:9999;font-size:0.85rem;box-shadow:0 10px 30px rgba(16,185,129,0.3);";
    statusEl.textContent = `Downloading ${fileId}...`;
    document.body.appendChild(statusEl);

    try {
        const res = await fetch(url);
        if (!res.ok) {
            const text = await res.text();
            throw new Error(`Download failed: ${res.status} — ${text}`);
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
    } catch (err) {
        statusEl.textContent = `Error: ${err.message}`;
        statusEl.style.background = "var(--red)";
        statusEl.style.color = "#fff";
    }
    setTimeout(() => statusEl.remove(), 4000);
}

async function deleteFile(fileId) {
    if (!confirm(`Permanently delete "${fileId}" from Telegram storage?`)) return;

    try {
        const res = await fetch(`/api/folders/${currentFolderId}/files/${encodeURIComponent(fileId)}`, {
            method: "DELETE",
        });
        if (!res.ok) {
            const data = await res.json();
            alert(data.detail || "Delete failed");
            return;
        }
        if (selectedFile && selectedFile.id === fileId) {
            selectedFile = null;
            updateInspector();
        }
        loadFiles();
    } catch (err) {
        alert("Delete failed: " + err.message);
    }
}

// ══════════════════════════════════════════════
//  Preview Lightbox
// ══════════════════════════════════════════════
function isPreviewable(fileId) {
    const ext = getFileExt(fileId);
    return [
        // Images
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico',
        // Videos
        '.mp4', '.webm', '.mov', '.mkv',
        // Audio
        '.mp3', '.wav', '.ogg', '.m4a', '.flac',
        // Documents / Code
        '.pdf', '.txt', '.md', '.json', '.xml', '.html', '.css', '.js',
    ].includes(ext);
}

function previewFile(fileId) {
    if (!isPreviewable(fileId)) {
        alert('This file type cannot be previewed directly. Please download it instead.');
        return;
    }
    const previewUrl = `/api/folders/${currentFolderId}/preview/${encodeURIComponent(fileId)}`;
    openPreviewModal(fileId, previewUrl);
}

function openPreviewModal(fileId, previewUrl) {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay preview-overlay';
    modal.onclick = (e) => { if (e.target === modal) closePreviewModal(modal); };

    const ext = getFileExt(fileId);
    const isImage = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.ico', '.svg'].includes(ext);
    let contentHtml = '';
    let bodyClass = '';
    let toolbarHtml = '';

    if (isImage) {
        toolbarHtml = `
            <div class="preview-toolbar">
                <button class="preview-tool-btn" id="preview-zoom-out" title="Zoom Out (-)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
                </button>
                <span class="preview-zoom-label" id="preview-zoom-label" title="Reset (100%)">100%</span>
                <button class="preview-tool-btn" id="preview-zoom-in" title="Zoom In (+)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
                </button>
                <div class="preview-divider"></div>
                <button class="preview-tool-btn" id="preview-zoom-fit" title="Toggle 2.5x (F)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
                </button>
                <button class="preview-tool-btn" id="preview-rotate" title="Rotate 90° (R)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                </button>
                <button class="preview-tool-btn" id="preview-reset" title="Reset View (0)">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
                </button>
            </div>
        `;
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.85rem;color:var(--text-2);">Retrieving image from Telegram...</p>
            </div>
            <div class="preview-image-viewport" id="preview-image-viewport">
                <div class="preview-image-wrapper" id="preview-image-wrapper">
                    <img src="${previewUrl}" alt="${escapeAttr(fileId)}"
                        onload="document.getElementById('preview-loader')?.remove()"
                        onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')">
                </div>
            </div>
            <div class="preview-hints">
                <span><kbd>Scroll</kbd> Zoom</span>
                <span><kbd>Drag</kbd> Pan</span>
                <span><kbd>Double-click</kbd> Fit/2.5x</span>
                <span><kbd>Esc</kbd> Close</span>
            </div>
        `;
    } else if (['.mp4', '.webm', '.mov', '.mkv'].includes(ext)) {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.85rem;color:var(--text-2);">Streaming video from Telegram...</p>
            </div>
            <div class="preview-media-container">
                <video controls autoplay playsinline
                    onloadeddata="document.getElementById('preview-loader')?.remove()"
                    onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')">
                    <source src="${previewUrl}">
                </video>
            </div>
        `;
    } else if (['.mp3', '.wav', '.ogg', '.m4a', '.flac'].includes(ext)) {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.85rem;color:var(--text-2);">Streaming audio from Telegram...</p>
            </div>
            <div class="preview-media-container">
                <audio controls autoplay
                    oncanplay="document.getElementById('preview-loader')?.remove()"
                    onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')">
                    <source src="${previewUrl}">
                </audio>
            </div>
        `;
    } else if (ext === '.pdf') {
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.85rem;color:var(--text-2);">Retrieving PDF from Telegram...</p>
            </div>
            <iframe class="preview-pdf-iframe" src="${previewUrl}"
                onload="document.getElementById('preview-loader')?.remove()"
                onerror="handlePreviewLoadError(this, '${escapeAttr(fileId)}')"></iframe>
        `;
    } else {
        bodyClass = 'scrollable';
        contentHtml = `
            <div class="preview-spinner-overlay" id="preview-loader">
                <div class="preview-spinner"></div>
                <p style="margin-top:14px;font-size:0.85rem;color:var(--text-2);">Retrieving file from Telegram...</p>
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
                                <p style="font-size:0.85rem;color:var(--text-2);">${escapeHtml(err.message)}</p>
                            </div>
                        `;
                    }
                }
            });
    }

    modal.innerHTML = `
        <div class="preview-dialog" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="preview-header-left">
                    <span class="preview-badge">${escapeHtml(ext.replace('.', '') || 'FILE')}</span>
                    <h3 class="preview-title" title="${escapeAttr(fileId)}">${escapeHtml(fileId)}</h3>
                </div>
                ${toolbarHtml}
                <div class="preview-header-actions">
                    <button class="btn-action download" onclick="downloadFile('${escapeAttr(fileId)}')">Download</button>
                    <button class="btn-icon" onclick="closePreviewModal(this.closest('.modal-overlay'))" title="Close (Esc)">✕</button>
                </div>
            </div>
            <div class="modal-body ${bodyClass}">
                ${contentHtml}
            </div>
        </div>
    `;

    document.body.appendChild(modal);

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
            modal, viewport, wrapper, label, btnIn, btnOut, btnFit, btnReset, btnRotate,
        });
    } else {
        const onKeyDown = (e) => {
            if (e.key === 'Escape') closePreviewModal(modal);
        };
        window.addEventListener('keydown', onKeyDown);
        modal._cleanup = () => window.removeEventListener('keydown', onKeyDown);
    }
}

function handlePreviewLoadError(el, fileId) {
    const parent = el.closest('.preview-dialog')?.querySelector('.modal-body');
    if (!parent) return;
    parent.innerHTML = `
        <div class="preview-error-box">
            <svg class="preview-error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <h4 style="margin-bottom:8px;font-size:1.05rem;">File Not Found on Telegram</h4>
            <p style="font-size:0.84rem;color:var(--text-2);margin-bottom:18px;">
                The message containing <strong>${escapeHtml(fileId)}</strong> could not be retrieved. Click Sync below to re-index your channel.
            </p>
            <button class="btn-primary" onclick="rebuildIndex();closePreviewModal(this.closest('.modal-overlay'))">
                Sync Telegram Index
            </button>
        </div>
    `;
}

function closePreviewModal(modal) {
    if (modal._cleanup) modal._cleanup();
    modal.remove();
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

    function applyTransform(animate = false) {
        if (animate) wrapper.classList.remove('no-transition');
        else wrapper.classList.add('no-transition');
        wrapper.style.transform = `translate3d(${posX}px, ${posY}px, 0) scale(${scale}) rotate(${rotation}deg)`;
        if (label) label.textContent = `${Math.round(scale * 100)}%`;
    }

    function zoomBy(factor, clientX, clientY, animate = true) {
        const oldScale = scale;
        const newScale = Math.min(maxScale, Math.max(minScale, oldScale * factor));
        if (Math.abs(newScale - oldScale) < 0.001) return;

        if (clientX !== undefined && clientY !== undefined && viewport) {
            const rect = viewport.getBoundingClientRect();
            const relX = clientX - (rect.left + rect.width / 2);
            const relY = clientY - (rect.top + rect.height / 2);
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
        scale = 1.0; posX = 0; posY = 0; rotation = 0;
        applyTransform(animate);
    }

    function rotate(animate = true) {
        rotation = (rotation + 90) % 360;
        applyTransform(animate);
    }

    if (btnIn) btnIn.onclick = () => zoomBy(1.3, undefined, undefined, true);
    if (btnOut) btnOut.onclick = () => zoomBy(1 / 1.3, undefined, undefined, true);
    if (btnReset) btnReset.onclick = () => resetView(true);
    if (label) label.onclick = () => resetView(true);
    if (btnFit) btnFit.onclick = () => (Math.abs(scale - 1.0) > 0.1 ? resetView(true) : zoomBy(2.5, undefined, undefined, true));
    if (btnRotate) btnRotate.onclick = () => rotate(true);

    const onWheel = (e) => {
        e.preventDefault();
        zoomBy(e.deltaY < 0 ? 1.15 : 0.87, e.clientX, e.clientY, false);
    };
    viewport.addEventListener('wheel', onWheel, { passive: false });

    const onMouseDown = (e) => {
        if (e.button !== 0) return;
        isDragging = true;
        startX = e.clientX - posX;
        startY = e.clientY - posY;
        viewport.classList.add('is-dragging');
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

    const onKeyDown = (e) => {
        if (e.key === 'Escape') closePreviewModal(modal);
        if (e.key === '+' || e.key === '=') zoomBy(1.25, undefined, undefined, true);
        if (e.key === '-' || e.key === '_') zoomBy(0.8, undefined, undefined, true);
        if (e.key === '0') resetView(true);
        if (e.key === 'r' || e.key === 'R') rotate(true);
    };
    window.addEventListener('keydown', onKeyDown);

    return () => {
        viewport.removeEventListener('wheel', onWheel);
        viewport.removeEventListener('mousedown', onMouseDown);
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
        window.removeEventListener('keydown', onKeyDown);
    };
}

// ══════════════════════════════════════════════
//  Rebuild & Sidebar Toggle
// ══════════════════════════════════════════════
function toggleSidebar() {
    $("sidebar")?.classList.toggle("open");
}

async function rebuildIndex() {
    const btn = $("rebuild-index-btn");
    const originalText = btn ? btn.innerHTML : "";
    if (btn) {
        btn.innerHTML = `
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin">
                <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            <span>Syncing...</span>
        `;
        btn.disabled = true;
    }

    try {
        const res = await fetch("/api/debug/rebuild", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Sync failed");

        alert(`Vault Rebuilt: ${data.summary.files} files, ${data.summary.folders} folders indexed.`);
        loadFolders();
    } catch (err) {
        alert("Rebuild failed: " + err.message);
    } finally {
        if (btn) {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    }
}

// ══════════════════════════════════════════════
//  Helpers & File Type Icons
// ══════════════════════════════════════════════
function getFileExt(filename) {
    if (!filename || !filename.includes('.')) return "";
    return filename.substring(filename.lastIndexOf('.')).toLowerCase();
}

function getFileIconSvg(ext) {
    if (['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'].includes(ext)) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`;
    }
    if (['.mp4', '.webm', '.mov', '.mkv', '.avi', '.flv'].includes(ext)) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>`;
    }
    if (['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac'].includes(ext)) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`;
    }
    if (['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.iso'].includes(ext)) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>`;
    }
    if (ext === '.pdf') {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`;
    }
    if (['.txt', '.md', '.json', '.xml', '.html', '.css', '.js', '.py', '.cpp'].includes(ext)) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`;
    }
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="card-type-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
}

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
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}
