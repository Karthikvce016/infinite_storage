/**
 * auth.js – Handles Telegram OTP login flow and token management.
 */

let _phoneCodeHash = "";
let _phone = "";

// ── Check if already logged in ──────────────────────────
(function checkAuth() {
    const token = localStorage.getItem("tg_drive_token");
    if (token && window.location.pathname.includes("login")) {
        // Verify token is still valid
        fetch("/api/auth/me", {
            headers: { Authorization: `Bearer ${token}` },
        })
            .then((r) => {
                if (r.ok) window.location.href = "/";
            })
            .catch(() => {});
    }
})();

// ── OTP Digit Box Handlers ──────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    const digits = document.querySelectorAll(".otp-digit");

    digits.forEach((input, idx) => {
        input.addEventListener("input", (e) => {
            const val = e.target.value.replace(/\D/g, "");
            e.target.value = val;
            if (val && idx < digits.length - 1) {
                digits[idx + 1].focus();
            }
            // Auto-submit when all filled
            if (idx === digits.length - 1 && val) {
                const code = Array.from(digits)
                    .map((d) => d.value)
                    .join("");
                if (code.length === digits.length) {
                    verifyOtp();
                }
            }
        });

        input.addEventListener("keydown", (e) => {
            if (e.key === "Backspace" && !e.target.value && idx > 0) {
                digits[idx - 1].focus();
                digits[idx - 1].value = "";
            }
        });

        // Handle paste
        input.addEventListener("paste", (e) => {
            e.preventDefault();
            const paste = (e.clipboardData || window.clipboardData)
                .getData("text")
                .replace(/\D/g, "");
            paste.split("").forEach((char, i) => {
                if (digits[idx + i]) {
                    digits[idx + i].value = char;
                }
            });
            const focusIdx = Math.min(idx + paste.length, digits.length - 1);
            digits[focusIdx].focus();
            // Auto-submit if fully pasted
            const code = Array.from(digits)
                .map((d) => d.value)
                .join("");
            if (code.length === digits.length) {
                setTimeout(() => verifyOtp(), 200);
            }
        });
    });

    // Enter key on phone input
    const phoneInput = document.getElementById("phone-input");
    if (phoneInput) {
        phoneInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") sendOtp();
        });
    }
});

// ── Send OTP ─────────────────────────────────────────────
async function sendOtp() {
    const phoneInput = document.getElementById("phone-input");
    const btn = document.getElementById("btn-send-otp");
    const raw = phoneInput.value.trim().replace(/[\s\-()]/g, "");

    if (!raw || raw.length < 8) {
        showError("Please enter a valid phone number with country code.");
        return;
    }

    _phone = raw.startsWith("+") ? raw : "+" + raw;
    setLoading(btn, true);
    hideError();

    try {
        const res = await fetch("/api/auth/send-otp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone: _phone }),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to send OTP");

        _phoneCodeHash = data.phone_code_hash;
        switchStep("step-otp");
        document.querySelector(".otp-digit").focus();
    } catch (err) {
        showError(err.message);
    } finally {
        setLoading(btn, false);
    }
}

// ── Verify OTP ───────────────────────────────────────────
async function verifyOtp() {
    const btn = document.getElementById("btn-verify-otp");
    const digits = document.querySelectorAll(".otp-digit");
    const code = Array.from(digits)
        .map((d) => d.value)
        .join("");

    if (code.length < 5) {
        showError("Please enter the complete verification code.");
        return;
    }

    setLoading(btn, true);
    hideError();

    try {
        const res = await fetch("/api/auth/verify-otp", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phone: _phone,
                code: code,
                phone_code_hash: _phoneCodeHash,
            }),
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Verification failed");

        // Store token
        localStorage.setItem("tg_drive_token", data.token);
        localStorage.setItem("tg_drive_user", data.name);

        // Show success
        document.getElementById("user-name").textContent = data.name;
        switchStep("step-success");

        // Redirect after animation
        setTimeout(() => {
            window.location.href = "/";
        }, 1500);
    } catch (err) {
        showError(err.message);
        // Clear OTP boxes on error
        digits.forEach((d) => (d.value = ""));
        digits[0].focus();
    } finally {
        setLoading(btn, false);
    }
}

// ── Go back to phone step ────────────────────────────────
function goBackToPhone() {
    hideError();
    // Clear OTP
    document.querySelectorAll(".otp-digit").forEach((d) => (d.value = ""));
    switchStep("step-phone");
    document.getElementById("phone-input").focus();
}

// ── UI Helpers ───────────────────────────────────────────
function switchStep(stepId) {
    document.querySelectorAll(".login-step").forEach((s) => {
        s.classList.remove("active");
    });
    document.getElementById(stepId).classList.add("active");
}

function setLoading(btn, loading) {
    const text = btn.querySelector(".btn-text");
    const loader = btn.querySelector(".btn-loader");
    if (loading) {
        text.classList.add("hidden");
        loader.classList.remove("hidden");
        btn.disabled = true;
    } else {
        text.classList.remove("hidden");
        loader.classList.add("hidden");
        btn.disabled = false;
    }
}

function showError(msg) {
    const el = document.getElementById("error-msg");
    el.textContent = msg;
    el.classList.remove("hidden");
    // Shake animation
    el.classList.remove("shake");
    void el.offsetWidth;
    el.classList.add("shake");
}

function hideError() {
    document.getElementById("error-msg").classList.add("hidden");
}
