
(function(){
  function bindRowLinks(){
    document.querySelectorAll(".row-link").forEach(tr => {
      tr.addEventListener("click", () => {
        const href = tr.getAttribute("data-href");
        if(href) window.location.href = href;
      });
    });
  }

  function chartKRI(){
    const el = document.getElementById("kriChart");
    if(!el || !window.__DASH) return;
    const items = (window.__DASH.prisons || []).slice(0,10).reverse();
    const labels = items.map(x => x.name.replace("سجن ",""));
    const data = items.map(x => x.kri);

    new Chart(el, {
      type: "bar",
      data: { labels, datasets: [{ label: "KRI", data }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, max: 100, ticks: { stepSize: 20 } },
          x: { ticks: { font: { size: 12 } } }
        }
      }
    });
  }

  function chartTrend(){
    const el = document.getElementById("trendChart");
    if(!el || !window.__PRISON) return;
    const t = window.__PRISON.trend || [];
    const labels = t.map(x => x.ref_no);
    const data = t.map(x => x.score);

    new Chart(el, {
      type: "line",
      data: { labels, datasets: [{ label: "مؤشر المخاطر", data, tension: 0.25 }] },
      options: {
        responsive:true,
        maintainAspectRatio:false,
        plugins: { legend: { display:false } },
        scales: { y: { beginAtZero: true, max: 100, ticks: { stepSize: 20 } } }
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function(){
    bindRowLinks();
    chartKRI();
    chartTrend();
  });
})();
