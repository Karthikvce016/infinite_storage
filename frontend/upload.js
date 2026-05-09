document.addEventListener("DOMContentLoaded", () => {
    // ── Auth guard ────────────────────────────────────────
    const token = localStorage.getItem("tg_drive_token");
    if (!token) {
        window.location.href = "/login.html";
        return;
    }

    const userName = localStorage.getItem("tg_drive_user") || "User";
    const userDisplay = document.getElementById("user-display-name");
    if (userDisplay) userDisplay.textContent = userName;

    // ── Auth headers helper ───────────────────────────────
    function authHeaders(extra = {}) {
        return { Authorization: `Bearer ${token}`, ...extra };
    }

    function handleAuthError(response) {
        if (response.status === 401) {
            localStorage.removeItem("tg_drive_token");
            localStorage.removeItem("tg_drive_user");
            window.location.href = "/login.html";
            return true;
        }
        return false;
    }

    // ── DOM refs ──────────────────────────────────────────
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const tbody = document.getElementById("files-tbody");
    const emptyState = document.getElementById("empty-state");
    const progressContainer = document.getElementById("upload-progress-container");
    const progressFill = document.getElementById("upload-progress-fill");
    const statusText = document.getElementById("upload-status");

    loadFiles();

    // Setup drag and drop
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("drag-over");
    });
    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");
        if (e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });
    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    });

    async function handleFiles(files) {
        for (let i = 0; i < files.length; i++) {
            const alias = prompt(
                `Enter an alias for "${files[i].name}" (leave empty to keep original name):`,
                ""
            );
            // If user clicks Cancel on prompt, skip this file
            if (alias === null) continue;
            await uploadFile(files[i], alias);
        }
    }

    async function uploadFile(file, alias = "") {
        const displayName = alias || file.name;
        progressContainer.classList.remove("hidden");
        statusText.textContent = `Uploading ${displayName}...`;
        progressFill.style.width = "50%";

        const formData = new FormData();
        formData.append("file", file);
        if (alias) {
            formData.append("alias", alias);
        }

        try {
            const response = await fetch("/api/upload", {
                method: "POST",
                headers: authHeaders(),
                body: formData
            });

            if (handleAuthError(response)) return;

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Upload failed");
            }

            progressFill.style.width = "100%";
            statusText.textContent = `Uploaded ${file.name} successfully!`;
            setTimeout(() => {
                progressContainer.classList.add("hidden");
                progressFill.style.width = "0%";
            }, 2000);

            loadFiles();
        } catch (error) {
            console.error(error);
            statusText.textContent = `Error: ${error.message}`;
            progressFill.style.backgroundColor = "#ff4444";
            setTimeout(() => {
                progressContainer.classList.add("hidden");
                progressFill.style.backgroundColor = ""; // reset
            }, 4000);
        }
    }

    async function loadFiles() {
        try {
            const response = await fetch("/api/files", {
                headers: authHeaders(),
            });

            if (handleAuthError(response)) return;

            const files = await response.json();

            tbody.innerHTML = "";

            if (files.length === 0) {
                emptyState.classList.remove("hidden");
                document.getElementById('files-table').classList.add("hidden");
            } else {
                emptyState.classList.add("hidden");
                document.getElementById('files-table').classList.remove("hidden");

                files.forEach(file => {
                    const tr = document.createElement("tr");
                    const escapedName = escapeHtml(file.name);
                    const encodedId = encodeURIComponent(file.id);
                    tr.innerHTML = `
                        <td>${escapedName}</td>
                        <td>${formatBytes(file.size)}</td>
                        <td class="actions">
                            <button class="btn-download" onclick="downloadFile('${encodedId}')">Download</button>
                            <button class="btn-delete" onclick="deleteFile('${encodedId}', '${escapedName}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        } catch (error) {
            console.error("Failed to load files:", error);
        }
    }

    window.downloadFile = async (encodedFileId) => {
        try {
            const response = await fetch(`/api/download/${encodedFileId}`, {
                headers: authHeaders(),
            });

            if (handleAuthError(response)) return;

            if (!response.ok) {
                const err = await response.json();
                alert(`Download failed: ${err.detail || "Unknown error"}`);
                return;
            }

            // Get filename from Content-Disposition
            const disposition = response.headers.get("Content-Disposition");
            let filename = decodeURIComponent(encodedFileId);
            if (disposition) {
                const match = disposition.match(/filename="(.+)"/);
                if (match) filename = match[1];
            }

            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error(error);
            alert("Error downloading file.");
        }
    };

    window.deleteFile = async (encodedFileId, displayName) => {
        if (!confirm(`Are you sure you want to delete ${displayName || encodedFileId}?`)) return;

        try {
            const response = await fetch(`/api/file/${encodedFileId}`, {
                method: "DELETE",
                headers: authHeaders(),
            });

            if (handleAuthError(response)) return;

            if (response.ok) {
                loadFiles();
            } else {
                alert("Failed to delete file.");
            }
        } catch (error) {
            console.error(error);
            alert("Error deleting file.");
        }
    };

    // ── Logout handler ───────────────────────────────────
    window.logoutUser = async () => {
        try {
            await fetch("/api/auth/logout", {
                method: "POST",
                headers: authHeaders(),
            });
        } catch (e) {
            // Ignore errors on logout
        }
        localStorage.removeItem("tg_drive_token");
        localStorage.removeItem("tg_drive_user");
        window.location.href = "/login.html";
    };

    function formatBytes(bytes, decimals = 2) {
        if (!+bytes) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});
