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

  document.querySelectorAll(".nav-animated").forEach((link) => {
    let motionTimer;
    const playMotion = () => {
      window.clearTimeout(motionTimer);
      link.classList.remove("is-animating");
      void link.offsetWidth;
      link.classList.add("is-animating");
      motionTimer = window.setTimeout(() => link.classList.remove("is-animating"), 1500);
    };

    link.addEventListener("pointerenter", playMotion);
    link.addEventListener("focus", playMotion);
  });
});
