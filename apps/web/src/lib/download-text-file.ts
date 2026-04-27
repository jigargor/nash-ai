/**
 * Download text as a file. Leading-dot names (e.g. `.codereview.yml`) are often
 * mangled by the anchor `download` attribute; prefer File System Access API when available.
 */
export async function downloadTextFile(filename: string, content: string): Promise<void> {
  const blob = new Blob([content], { type: "text/yaml;charset=utf-8" });

  if (
    filename.startsWith(".") &&
    typeof window !== "undefined" &&
    "showSaveFilePicker" in window &&
    typeof window.showSaveFilePicker === "function"
  ) {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{ description: "YAML", accept: { "text/yaml": [".yml", ".yaml"] } }],
      });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
    }
  }

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
