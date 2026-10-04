(async function () {
  const style = document.createElement("style");
  style.textContent = `
    #arw-accuracy { background:#17243a;color:#eef4ff;padding:18px;border:1px solid #526682;border-radius:14px;margin:16px 0;font:14px Arial,sans-serif }
    #arw-accuracy h2 { margin:0 0 6px;font-size:20px }
    #arw-accuracy small { color:#b9c8dc }
    #arw-accuracy svg { width:100%;height:180px;display:block;margin-top:12px }
    #arw-accuracy .score { font-size:30px;font-weight:bold;margin:8px 0 }
  `;
  document.head.appendChild(style);

  const panel = document.createElement("section");
  panel.id = "arw-accuracy";
  panel.innerHTML =
    "<h2>Measured Forecast Score</h2>" +
    "<small>Brier-based score from completed forecasts with verified outcomes. Higher is better.</small>" +
    "<div class='score'>Awaiting verified outcomes</div>" +
    "<div>Waiting for completed forecasts with verified outcomes.</div>";

  const heading = [...document.querySelectorAll("h1,h2,h3,h4,strong,b,span,div")]
    .find(e => e.children.length === 0 &&
      e.textContent.trim().toLowerCase() === "measured accuracy");

  if (heading) {
    let card = heading;
    for (let i = 0; i < 6 && card.parentElement; i++) {
      card = card.parentElement;
      if (/pending/i.test(card.innerText || "") &&
          card.getBoundingClientRect().width > 250) break;
    }
    card.replaceWith(panel);
  } else {
    document.body.prepend(panel);
  }

  try {
    const response = await fetch("./accuracy-history.json?ts=" + Date.now(), {
      cache: "no-store"
    });
    if (!response.ok) throw new Error("Accuracy history unavailable.");

    const data = await response.json();
    const rows = (data.forecasts || [])
      .filter(x =>
        x.verifiedAt &&
        typeof x.outcome === "boolean" &&
        Number.isFinite(Number(x.probability)) &&
        Number(x.probability) >= 0 &&
        Number(x.probability) <= 1
      )
      .sort((a, b) => new Date(a.verifiedAt) - new Date(b.verifiedAt));

    if (!rows.length) {
      panel.insertAdjacentHTML("beforeend",
        "<svg viewBox='0 0 1000 180' role='img' aria-label='Forecast score graph'>" +
        "<line x1='8' y1='158' x2='992' y2='158' stroke='#70839e'/>" +
        "<line x1='8' y1='18' x2='8' y2='158' stroke='#70839e'/>" +
        "<text x='25' y='85' fill='#b9c8dc'>Waiting for verified outcomes</text>" +
        "</svg>");
      return;
    }

    const scores = rows.map((x, i) => {
      const recent = rows.slice(Math.max(0, i - 19), i + 1);
      const brier = recent.reduce((sum, r) => {
        const probability = Number(r.probability);
        const outcome = r.outcome ? 1 : 0;
        return sum + Math.pow(probability - outcome, 2);
      }, 0) / recent.length;

      return { score: 100 * (1 - brier) };
    });

    const last = scores[scores.length - 1];
    const points = scores.map((item, i) => {
      const x = 8 + i * 984 / Math.max(1, scores.length - 1);
      const y = 158 - item.score * 1.4;
      return x + "," + y;
    }).join(" ");

    panel.querySelector(".score").textContent =
      last.score.toFixed(1) + " / 100";

    panel.querySelector("div:not(.score)").textContent =
      rows.length + " verified forecasts; line shows the rolling score for up to the latest 20.";

    panel.insertAdjacentHTML("beforeend",
      "<svg viewBox='0 0 1000 180' role='img' aria-label='Rolling forecast score over time'>" +
      "<line x1='8' y1='158' x2='992' y2='158' stroke='#70839e'/>" +
      "<line x1='8' y1='18' x2='8' y2='158' stroke='#70839e'/>" +
      "<polyline fill='none' stroke='#53d6c5' stroke-width='4' points='" + points + "'/>" +
      "</svg>" +
      "<small>Score = 100 × (1 − mean squared probability error). It is not a guarantee of future accuracy.</small>"
    );
  } catch (error) {
    panel.querySelector("div:not(.score)").textContent =
      "No verified forecast history is available yet. The score will appear after outcomes are recorded.";
  }
})();

