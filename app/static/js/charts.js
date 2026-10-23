// Draws the charts on the costs page with Chart.js.
//
// The server renders the data as JSON into <canvas data-chart="…"> (see app/charts.py), so
// the page needs no inline <script> and the Content-Security-Policy stays strict. Without
// JavaScript the canvas stays hidden and the "Dane wykresu" table shows the same numbers.
(function () {
  "use strict";

  // Series colours come from the CSS variables, so charts match the rest of the page.
  const COLOR_VARIABLES = {
    fuel: "--color-fuel",
    other: "--color-primary",
    petrol: "--color-primary",
    diesel: "--color-warning",
    lpg: "--color-fuel",
  };

  // Amounts have two decimal places; a chart may ask for another precision ("decimals").
  function numberFormat(decimals) {
    return new Intl.NumberFormat("pl-PL", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function cssColor(key) {
    const variable = COLOR_VARIABLES[key] || "--color-muted";
    return getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  }

  function draw(canvas) {
    if (Chart.getChart(canvas)) {
      return; // already drawn (e.g. both DOMContentLoaded and htmx:load fired)
    }
    const spec = JSON.parse(canvas.dataset.chart);
    const stacked = spec.kind === "stacked-bar";
    const number = numberFormat(spec.decimals ?? 2);
    const format = (value) => `${number.format(value)} ${spec.unit}`;

    canvas.parentElement.hidden = false;
    new Chart(canvas, {
      type: stacked ? "bar" : "line",
      data: {
        labels: spec.labels,
        datasets: spec.series.map((series) => ({
          label: series.label,
          data: series.values,
          backgroundColor: cssColor(series.key),
          borderColor: cssColor(series.key),
          spanGaps: true, // a fuel not refuelled on some date: continue the line
          tension: 0.2,
          pointRadius: 2,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { stacked: stacked },
          y: {
            stacked: stacked,
            beginAtZero: stacked,
            ticks: { callback: (value) => format(value) },
          },
        },
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            // Skip fuels without a refuel on the hovered date.
            filter: (item) => item.parsed.y !== null,
            callbacks: {
              label: (context) => `${context.dataset.label}: ${format(context.parsed.y)}`,
            },
          },
        },
      },
    });
  }

  function drawAll(root) {
    root.querySelectorAll("canvas[data-chart]").forEach(draw);
  }

  function destroyAll(root) {
    root.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
      const chart = Chart.getChart(canvas);
      if (chart) {
        chart.destroy();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => drawAll(document));
  // The period selector swaps the summary with HTMX: draw the new charts, drop the old ones.
  document.addEventListener("htmx:load", (event) => drawAll(event.detail.elt));
  document.addEventListener("htmx:beforeSwap", (event) => destroyAll(event.detail.target));
})();
