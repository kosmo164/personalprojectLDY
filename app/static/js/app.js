let stockChart = null;
let backfillTimer = null;
let currentCode = "005930";

window.addEventListener("DOMContentLoaded", () => {
    loadTickerTape();
    loadQuickPicks();
    loadStockData();
    refreshBackfillStatus(); // 새로고침해도 진행 중이던 백필 상태를 이어서 보여줌
});

// ---------------- 토스트 ----------------
function showToast(message, type = "info") {
    const wrap = document.getElementById("toast-wrap");
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => {
        el.style.transition = "opacity .3s ease, transform .3s ease";
        el.style.opacity = "0";
        el.style.transform = "translateY(-6px)";
        setTimeout(() => el.remove(), 300);
    }, 3200);
}

// ---------------- 상단 티커 테이프 ----------------
function loadTickerTape() {
    fetch("/api/watchlist")
        .then((res) => res.json())
        .then((list) => {
            const track = document.getElementById("ticker-track");
            if (!list.length) return;
            const buildSpan = (item) => {
                const up = Math.random() > 0.5; // 실 등락 데이터를 붙이기 전까지의 자리 표시자
                return `<span><span class="tk-code">${item.itms_nm || item.srtn_cd}</span>${item.srtn_cd}</span>`;
            };
            const html = list.map(buildSpan).join("");
            // 끊김 없이 흐르도록 두 번 이어붙임
            track.innerHTML = html + html;
        })
        .catch(() => {});
}

// ---------------- 빠른 선택 칩 ----------------
function loadQuickPicks() {
    fetch("/api/codes")
        .then((res) => res.json())
        .then((list) => {
            const wrap = document.getElementById("quick-picks");
            wrap.innerHTML = "";
            list.forEach((item) => {
                const btn = document.createElement("button");
                btn.className = "chip";
                btn.textContent = `${item.itms_nm} · ${item.srtn_cd}`;
                btn.onclick = () => {
                    document.getElementById("search-code").value = item.srtn_cd;
                    document.querySelectorAll("#quick-picks .chip").forEach((c) => c.classList.remove("active"));
                    btn.classList.add("active");
                    loadStockData();
                };
                wrap.appendChild(btn);
            });
        })
        .catch(() => {});
}

// ---------------- 메인 데이터 로드 ----------------
function setSkeleton(on) {
    ["current-price", "ma-status", "bb-up-status", "bb-down-status", "pred-3m", "pred-6m", "pred-12m"].forEach((id) => {
        document.getElementById(id).classList.toggle("skeleton", on);
    });
}

function loadStockData() {
    const srtnCd = document.getElementById("search-code").value.trim();
    if (!srtnCd) {
        showToast("종목코드를 입력해주세요.", "error");
        return;
    }
    currentCode = srtnCd;
    setSkeleton(true);
    document.getElementById("empty-state").classList.add("hidden");

    fetch(`/api/stock/${srtnCd}`)
        .then(async (res) => {
            const data = await res.json();
            if (!res.ok) {
                const err = new Error(data.message || "조회 실패");
                err.payload = data;
                throw err;
            }
            return data;
        })
        .then((data) => {
            setSkeleton(false);
            document.getElementById("stock-title").innerHTML =
                `${data.itms_nm || data.srtn_cd} <span class="code">${data.srtn_cd}</span>`;
            document.getElementById("base-date").innerText = `기준일자: ${data.bas_dt || "-"}`;

            document.getElementById("current-price").innerText =
                `${Number(data.clpr).toLocaleString()} 원 (${data.flt_rt > 0 ? "+" : ""}${data.flt_rt}%)`;
            document.getElementById("ma-status").innerText = data.ma_20
                ? `${Math.round(data.ma_20).toLocaleString()} 원`
                : "데이터 부족 (20일 미만)";
            document.getElementById("bb-up-status").innerText = data.bollinger_up
                ? `${Math.round(data.bollinger_up).toLocaleString()} 원`
                : "-";
            document.getElementById("bb-down-status").innerText = data.bollinger_down
                ? `${Math.round(data.bollinger_down).toLocaleString()} 원`
                : "-";

            displayPrediction("pred-3m", data.p_3m);
            displayPrediction("pred-6m", data.p_6m);
            displayPrediction("pred-12m", data.p_12m);

            loadHistoryAndRenderChart(srtnCd);
        })
        .catch((err) => {
            setSkeleton(false);
            if (err.payload && err.payload.status === "no_data") {
                document.getElementById("stock-title").innerText = "데이터 없음";
                document.getElementById("empty-state").classList.remove("hidden");
                if (stockChart) { stockChart.destroy(); stockChart = null; }
                showToast(err.payload.message, "error");
            } else {
                showToast("조회 중 오류가 발생했습니다. 콘솔을 확인하세요.", "error");
                console.error(err);
            }
        });
}

function displayPrediction(elementId, value) {
    const el = document.getElementById(elementId);
    if (value === undefined || value === null || value === 0) {
        el.innerText = "-";
        el.className = "p-value";
        return;
    }
    const prefix = value > 0 ? "▲ +" : "▼ ";
    el.innerText = `${prefix}${value}%`;
    el.className = value > 0 ? "p-value gain" : "p-value loss";
}

// ---------------- 실제 히스토리 기반 차트 ----------------
function loadHistoryAndRenderChart(srtnCd) {
    fetch(`/api/stock/${srtnCd}/history?days=90`)
        .then((res) => res.json())
        .then((rows) => renderChart(rows))
        .catch((err) => console.error(err));
}

function renderChart(rows) {
    const ctx = document.getElementById("stockChart").getContext("2d");
    if (stockChart) stockChart.destroy();

    const labels = rows.map((r) => r.BAS_DT || r.bas_dt);
    const closeData = rows.map((r) => r.CLPR ?? r.clpr);
    const maData = rows.map((r) => r.MA_20 ?? r.ma_20);
    const upData = rows.map((r) => r.BOLLINGER_UP ?? r.bollinger_up);
    const downData = rows.map((r) => r.BOLLINGER_DOWN ?? r.bollinger_down);

    stockChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                { label: "종가", data: closeData, borderColor: "#c8a557", backgroundColor: "transparent", borderWidth: 2.2, pointRadius: 0, tension: 0.2 },
                { label: "20일 이평선", data: maData, borderColor: "#eae6da", borderDash: [4, 4], backgroundColor: "transparent", borderWidth: 1.2, pointRadius: 0, tension: 0.2 },
                { label: "볼린저 상한", data: upData, borderColor: "#5fa876", backgroundColor: "transparent", borderWidth: 1, pointRadius: 0, tension: 0.2 },
                { label: "볼린저 하한", data: downData, borderColor: "#c1584a", backgroundColor: "transparent", borderWidth: 1, pointRadius: 0, tension: 0.2 },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 600, easing: "easeOutQuart" },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { labels: { color: "#8b8f98", font: { family: "Inter", size: 11 } } },
                tooltip: { backgroundColor: "rgba(15,17,21,.95)", borderColor: "#c8a557", borderWidth: 1 },
            },
            scales: {
                x: { grid: { color: "rgba(234,230,218,0.06)" }, ticks: { color: "#8b8f98", maxTicksLimit: 8 } },
                y: { grid: { color: "rgba(234,230,218,0.06)" }, ticks: { color: "#8b8f98" } },
            },
        },
    });
}

// ---------------- 초기 적재(백필) ----------------
function startBackfill() {
    const btn = document.getElementById("backfill-btn");
    fetch("/api/backfill/start", { method: "POST" })
        .then((res) => res.json())
        .then((data) => {
            if (data.status === "already_running") {
                showToast("이미 적재가 진행 중입니다.", "info");
            } else {
                showToast("관심종목 초기 데이터 적재를 시작했습니다.", "success");
            }
            btn.disabled = true;
            document.getElementById("backfill-progress-wrap").classList.remove("hidden");
            pollBackfillStatus();
        })
        .catch(() => showToast("적재 시작 요청에 실패했습니다.", "error"));
}

function pollBackfillStatus() {
    clearInterval(backfillTimer);
    backfillTimer = setInterval(refreshBackfillStatus, 1500);
}

function refreshBackfillStatus() {
    fetch("/api/backfill/status")
        .then((res) => res.json())
        .then((data) => {
            const btn = document.getElementById("backfill-btn");
            const wrap = document.getElementById("backfill-progress-wrap");
            if (data.total > 0) {
                wrap.classList.remove("hidden");
                const pct = Math.round((data.done / data.total) * 100);
                document.getElementById("backfill-fill").style.width = `${pct}%`;
                document.getElementById("backfill-pct").innerText = `${pct}%`;
                document.getElementById("backfill-label").innerText = data.running
                    ? `수집 중 · 종목코드 ${data.current_code || ""}`
                    : data.last_message || "완료";
            }
            if (data.running) {
                btn.disabled = true;
            } else {
                clearInterval(backfillTimer);
                btn.disabled = false;
                if (data.last_message) {
                    showToast(data.last_message, "success");
                    loadQuickPicks();
                    loadTickerTape();
                    loadStockData();
                }
            }
        })
        .catch(() => clearInterval(backfillTimer));
}
