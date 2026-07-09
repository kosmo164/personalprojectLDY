// 초기화 및 전역 상태 관리
// 1. 전역변수 : 현재 렌더링된 차트객체(stockChart), 상태폴링용 타이머 ID(backfillTimer),
// 현재 선택된 종목코드(currentCode)를 메모리에 유지함
// 2. DOMContentLoaded : 브라우저가 HTML을 다 읽자마자 전광판 리스트, 빠른 선택 칩 버튼, 기본
// 종목시세, 그리고 기존에 돌고 있던 백필 상태를 서버에서 비동기로 호출(Fetch)하여 화면을 완성

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
// 1. 상단 전광판 데이터 연결(loadTickerTape)
// /api/watchlist API를 호출해 관심 종목들을 불러온 후 가로 띠 형태로 조립. CSS에서 무한 롤링이 끊기지 ㅇ낳고
// 이어지도록 똑같은 HTML문자열을 뒤에 한번 더 복사하여 붙여넣는 (html + html)트릭이 사용됨.

// 2.빠른 선택 칩 버튼 구성(loadQuickPicks)
// 서버가 지원하는 종목목록을 가져오ㅘ 상단에 둥근 칩(Chip)모양 버튼들로 뿌려줌
// 버튼을 누르면(onclick), 검색창(input#search-code)에 해당 코드가 자동으로 입력되고, 기존에 활성화되어 있던 칩의
// active클래스를 전부 떼어낸 뒤 현재 클릭한 버튼에만 active를 붙여 스타일을 강조한 후, loadStockDate()를 호출해
// 메인 데이터를 즉시 리로드함
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
// 사용자 경헝(UX)고도화 기능
// 1. 세련된 알림창(showToast)
// 화면에 무언가 성공하거나 실패했을때, CSS테마 색상(info, success, error)에 맞춰 동적으로 알림 상자를 생성.
// setTimeout을 겹쳐 사용해 3.2초 동안 보여준 뒤 위로 부드럽게 사라지도록(Fade-out&Translate)구현했으며, 
// 애니메이션이 끝나면 메모리 누수를 방지하기 위해 .remove()로 DOM에서 완전히 지워짐
// 2. 스켈레톤 오딩 애니메이션(setSkeleton)
// 화면에 무언가 성공하거나 실패했을때, CSS테마 색상(info, success, error)에 맞춰 동적으로 알림 상자를 생성.
// setTimeout을 겹쳐 사용해 3.2초 동안 보여준 뒤 위로 부드럽게 사라지도록(Fade-out&Translate)구현했으며,
// 애니메이션이 끝나면 메모리 누수를 방지하기 위해 .remove()로 DOM에서 완전히 지워짐
// 3. 서버에서 데이터를 받아오는 찰나의 시간 동안 화면이 툭툭 끊겨 보이지 않도록, CSS에서 선언했던 .skeleton빛줄기 
// 흐름 효과 클래스를 토글(toggle)함. 데이터 요청 시작 시 true로 켜고, 응답이 오면 false로 꺼서 부드러운 화면 전환 
// 유도 
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

    // 메인 데이터 조회 및 분석 데이터 가공(loadStockData)
    // 사용자가 검색창에 입력한 종목 코드가 없으면 에러 토스트를 띄우고 차단을 걸어둠
    // 데이터가 안전하게 수신되면 3단계 가공을 거침. 
    // 1. 텍스트매핑 : 숫자로 된 주가를 부드러운 한국 통화 포맷(.toLocaleString() + '원')
    //      으로 콤마를 찍어 출력함. 등락률 부호(+)처리가 꼼꼼하게 설계되어 있음
    // 2. 예측률 컴포넌트출력(displayPrediction) : 선형회귀모델이 연산한 수익률 수치가 양수(+)
    //      면 ▲ + 기호와 함께 초록색(gain)스타일을 입히고, 음수(-)면 ▼ 기호와 함께 빨간색(loss)
    //      스타일을 융합해 줍니다. 데이터가 0이거나 없으면 대시보드 규격에 맞춰 깔끔하게 -로 밀어버림
    // 3. 히스토리차트호출 : 상세 수치 랜더링이 끝나면 즉시 하단의 loadHistoryAndRenderChart()를
    //      트리거하여 차트 그리기에 돌입함.
    // 예외처리 : 만약 서버에 데이터가 아예 없는 신규 종목 등의 사유로 no_data 상태코드가 반환되면 CSS에서 
    //      정의했던 #empty-state 안내 레이어를 활성화(classList.remove("hidden"))하고 기존 차트
    //      잔상을 파괴(destroy())에 정갈하게 비워냄.  
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

// Chart.js기반 기술적 지표 차트 구현
// 1. 과거 90일 치의 차트 플롯용 데이터를 수집해 하나의 캔버스에 4개의 선(종가, 20일 이동평균선,
//  볼린저 상한선, 볼린저 하한선)을 동시에 겹쳐 그림.
// 2. 디자인커스텀매핑 : 이전에 정의한 CSS "황동테마"테마에 맞춰 선의 색상(borderColor)을 매칭함.
//  (종가는 황동색 #c8a557, 볼린저 밴드는 각각 초록/빨강 계열)
// 3. 툴팁 배경색을 다크모드에 맞게 어두운 잉크빛(rgba(15,17,21,.95))으로 튜닝하고 테두리를 황동색
//  으로 마감함. 격자선(grid)의 투명도를 6%(rgba(..., 0.06))로 극도로 낮춰 메인 선들만 돋보이도록 시각 
//  소음을 걷어냄 
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
// 실시간 데이터 적재(백필) 상태 폴링(Polling)
// 과거 데이터를 대량으로 긁어오는 작업은 시간이 걸리기 때문에, 웹 서버가 지치지 않도록 주기적인 상태
// 체크(폴링)시스템으로 구현되어 있음
// 1. startBackfill() : 사용자가 "초기적재시작"버튼을 누르면 서번에 POST요청을 보내 백필 스레드를 깨우고 
//  즉시 버튼을 비활성화(disabled = True)처리한 후 pollBackfillStatus()를 가동
// 2. pollBackfillStatus() : 1.5초(1500ms)마다 주기적으로 서버의 진행 상황을 물어보는 인터벌 타이머
//  (setInterval())를 실행함
// 서버가 준 현재 스냅샷(data.done/data.total)을 활용해 진행률 퍼센트 (좐료수/전체수 X 100)를 계산
// 계산된 수치대로 하단 프로그레스 바의 길리(style.width = pct%)를 실시간으로 늘려줌
// 만약 서버 측에서 running: false로 작업이 끝났음을 알리면 인터벌 타이머를 즉시 청소(clearInterval)
// 하고 버튼을 다시 활성화 상태로 복구한 뒤, 최신화된 데이터 기반으로 대시보드를 통째로 리프레시
// (loadStockData())함.
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
