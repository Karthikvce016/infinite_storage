document.addEventListener("DOMContentLoaded", () => {
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
            await uploadFile(files[i]);
        }
    }

    async function uploadFile(file) {
        progressContainer.classList.remove("hidden");
        statusText.textContent = `Uploading ${file.name}...`;
        progressFill.style.width = "50%"; // Fake progress for now since fetch doesn't support upload progress natively easily

        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });

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
            const response = await fetch("/api/files");
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
                    tr.innerHTML = `
                        <td>${file.name}</td>
                        <td>${formatBytes(file.size)}</td>
                        <td class="actions">
                            <button class="btn-download" onclick="downloadFile('${file.id}')">Download</button>
                            <button class="btn-delete" onclick="deleteFile('${file.id}')">Delete</button>
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        } catch (error) {
            console.error("Failed to load files:", error);
        }
    }

    window.downloadFile = (fileId) => {
        // Direct trigger of download
        window.location.href = `/api/download/${fileId}`;
    };

    window.deleteFile = async (fileId) => {
        if (!confirm(`Are you sure you want to delete ${fileId}?`)) return;

        try {
            const response = await fetch(`/api/file/${fileId}`, {
                method: "DELETE"
            });
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

    function formatBytes(bytes, decimals = 2) {
        if (!+bytes) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
    }
});
