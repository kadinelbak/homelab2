(() => {
  const toast = () => document.querySelector(".toast");
  const announce = (message, error = false) => {
    const node = toast();
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("error", error);
    node.classList.add("show");
    window.setTimeout(() => node.classList.remove("show"), 2600);
  };

  const refreshExperiments = async () => {
    const response = await fetch("/experiments", { headers: { "X-Requested-With": "fetch" }, cache: "no-store" });
    if (!response.ok) throw new Error("Could not refresh experiments");
    const page = new DOMParser().parseFromString(await response.text(), "text/html");
    const nextMain = page.querySelector("main");
    const currentMain = document.querySelector("main");
    if (!nextMain || !currentMain) throw new Error("Could not update experiments");
    currentMain.innerHTML = nextMain.innerHTML;
  };

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-reactive]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('button[type="submit"], button:not([type])');
    const original = button?.textContent;
    if (button) { button.disabled = true; button.textContent = "Saving…"; }
    try {
      const response = await fetch(form.action, { method: form.method || "POST", body: new FormData(form), redirect: "follow" });
      if (!response.ok) throw new Error("Save failed");
      await refreshExperiments();
      announce("Saved");
    } catch (_) {
      announce("Could not save. Your entry was not changed.", true);
      if (button) { button.disabled = false; button.textContent = original; }
    }
  });

  document.addEventListener("input", (event) => {
    const filter = event.target.closest("[data-experiment-filter]");
    if (!filter) return;
    const needle = filter.value.trim().toLowerCase();
    document.querySelectorAll("[data-experiment-card]").forEach((card) => {
      card.hidden = !card.textContent.toLowerCase().includes(needle);
    });
  });
})();
