document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-news-card-image]").forEach((image) => {
    image.addEventListener("error", () => image.remove());
  });
  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    const input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;

    button.addEventListener("click", () => {
      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      button.setAttribute("aria-pressed", String(!isVisible));
      button.setAttribute("aria-label", isVisible ? "Show password" : "Hide password");
      input.focus({ preventScroll: true });
    });
  });

  document.querySelectorAll("[data-featured-carousel]").forEach((carousel) => {
    const slides = Array.from(carousel.querySelectorAll("[data-featured-slide]"));
    const dots = Array.from(carousel.querySelectorAll("[data-featured-dot]"));
    if (slides.length < 2) return;
    let active = 0;
    let timer;

    const show = (next) => {
      active = (next + slides.length) % slides.length;
      slides.forEach((slide, index) => {
        const current = index === active;
        slide.classList.toggle("is-active", current);
        slide.setAttribute("aria-hidden", String(!current));
        slide.tabIndex = current ? 0 : -1;
        dots[index]?.toggleAttribute("aria-current", current);
      });
    };
    const stop = () => window.clearInterval(timer);
    const start = () => {
      stop();
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        timer = window.setInterval(() => show(active + 1), 6500);
      }
    };

    dots.forEach((dot, index) => dot.addEventListener("click", () => {
      show(index);
      start();
    }));
    carousel.addEventListener("pointerenter", stop);
    carousel.addEventListener("pointerleave", start);
    carousel.addEventListener("focusin", stop);
    carousel.addEventListener("focusout", start);
    start();
  });

  const liveSlate = document.querySelector("[data-live-slate]");
  if (liveSlate) {
    const refreshScores = async () => {
      try {
        const response = await fetch("/api/live-matches", { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        payload.matches.forEach((match) => {
          const card = liveSlate.querySelector(`[data-live-match="${CSS.escape(match.id)}"]`);
          const score = card?.querySelector("[data-live-score]");
          if (score && match.score) score.textContent = match.score;
        });
      } catch (_) {
        // Keep the most recently stored score when a refresh is unavailable.
      }
    };
    window.setInterval(refreshScores, 60000);
  }

  const liveNews = document.querySelector("[data-news-live]");
  if (liveNews) {
    let firstStory = liveNews.dataset.newsFirst;
    const source = liveNews.dataset.newsSource || "all";
    const count = liveNews.querySelector("[data-news-count]");
    const checked = liveNews.querySelector("[data-news-checked]");
    const refreshNews = async () => {
      try {
        const response = await fetch(`/api/news-status?source=${encodeURIComponent(source)}`, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        if (count) count.textContent = `${payload.total} stories`;
        if (checked) checked.textContent = "Checked just now";
        if (firstStory && payload.first_id && payload.first_id !== firstStory) {
          window.location.reload();
          return;
        }
        firstStory = payload.first_id || firstStory;
      } catch (_) {
        if (checked) checked.textContent = "Live update paused";
      }
    };
    window.setInterval(refreshNews, 60000);
  }

});
