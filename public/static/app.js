document.addEventListener("DOMContentLoaded", () => {
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

});
