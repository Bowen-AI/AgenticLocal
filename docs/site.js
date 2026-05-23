(() => {
  const commandPattern = /(^|\n)\s*(?:bash|brew|curl|gh|git|ls|ollama|pip|python|python3|pytest|scripts\/|sudo|agentic-loop)\b/;

  const fallbackCopyText = (text) => {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, textArea.value.length);
    const copied = document.execCommand("copy");
    textArea.remove();

    if (!copied) {
      throw new Error("Copy command was not accepted by the browser.");
    }
  };

  const copyText = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (error) {
        fallbackCopyText(text);
        return;
      }
    }

    fallbackCopyText(text);
  };

  const buttonLabel = (text) => {
    const trimmed = text.trim();
    if (
      commandPattern.test(trimmed) ||
      trimmed.startsWith("http://127.0.0.1") ||
      trimmed.startsWith("https://bowen-ai.github.io")
    ) {
      return "Copy command";
    }
    return "Copy";
  };

  const setButtonState = (button, text, className) => {
    button.textContent = text;
    button.classList.remove("is-copied", "is-error");
    if (className) {
      button.classList.add(className);
    }
  };

  const enhanceCodeBlock = (pre, index) => {
    if (pre.closest(".code-copy")) {
      return;
    }

    const text = pre.textContent || "";
    const label = buttonLabel(text);
    const wrapper = document.createElement("div");
    const toolbar = document.createElement("div");
    const button = document.createElement("button");

    wrapper.className = "code-copy";
    toolbar.className = "copy-toolbar";
    button.className = "copy-button";
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", `${label} ${index + 1}`);

    button.addEventListener("click", async () => {
      try {
        await copyText(text.trimEnd());
        setButtonState(button, "Copied", "is-copied");
      } catch (error) {
        setButtonState(button, "Copy failed", "is-error");
      }

      window.setTimeout(() => {
        setButtonState(button, label, "");
      }, 1800);
    });

    pre.before(wrapper);
    toolbar.append(button);
    wrapper.append(toolbar, pre);
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("pre").forEach(enhanceCodeBlock);
  });
})();
