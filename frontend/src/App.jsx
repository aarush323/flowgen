import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, securityLevel: "loose", theme: "default" });

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export default function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [diagram, setDiagram] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [svgContent, setSvgContent] = useState("");
  const mermaidRef = useRef(null);

  useEffect(() => {
    if (!diagram) {
      setSvgContent("");
      if (mermaidRef.current) {
        mermaidRef.current.innerHTML = "";
      }
      return;
    }

    const render = async () => {
      try {
        const { svg } = await mermaid.render(`diagram-${Date.now()}`, diagram);
        setSvgContent(svg);
        if (mermaidRef.current) {
          mermaidRef.current.innerHTML = svg;
        }
      } catch (renderError) {
        setError("Failed to render Mermaid diagram.");
        console.error(renderError);
      }
    };

    render();
  }, [diagram]);

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    setSelectedFile(file ?? null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!selectedFile) {
      setError("Please select a ZIP file to upload.");
      return;
    }

    setIsLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "Upload failed.");
      }

      const data = await response.json();
      setDiagram(data.diagram);
      setSummary(data.summary);
    } catch (uploadError) {
      console.error(uploadError);
      setError(uploadError.message || "Unexpected error occurred.");
    } finally {
      setIsLoading(false);
    }
  };

  const download = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const exportSvg = () => {
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: "image/svg+xml" });
    download(blob, "architecture-diagram.svg");
  };

  const exportPng = async () => {
    if (!svgContent) return;
    const svgBlob = new Blob([svgContent], { type: "image/svg+xml" });
    const svgUrl = URL.createObjectURL(svgBlob);
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.src = svgUrl;

    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
    });

    const canvas = document.createElement("canvas");
    canvas.width = image.width || 1920;
    canvas.height = image.height || 1080;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0);
    URL.revokeObjectURL(svgUrl);

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (blob) {
      download(blob, "architecture-diagram.png");
    }
  };

  const exportMarkdown = () => {
    if (!diagram) return;
    const markdown = `\`\`\`mermaid\n${diagram}\n\`\`\``;
    const blob = new Blob([markdown], { type: "text/markdown" });
    download(blob, "architecture-diagram.md");
  };

  const reset = () => {
    setSelectedFile(null);
    setDiagram("");
    setSummary("");
    setError("");
  };

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <h1 className="text-2xl font-semibold">AI Code Architecture & Flow Diagram Generator</h1>
          <button
            onClick={reset}
            className="rounded border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
          >
            Reset
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
        <section className="rounded-lg bg-white p-6 shadow-sm">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 px-6 py-8 text-center hover:border-slate-400">
              <span className="text-lg font-medium">Upload your project ZIP</span>
              <span className="text-sm text-slate-500">
                The backend will parse Python and JavaScript files to build architecture insights.
              </span>
              <input
                type="file"
                accept=".zip"
                onChange={handleFileChange}
                className="hidden"
              />
              <span className="rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow">
                Choose ZIP
              </span>
              {selectedFile && (
                <span className="text-xs text-slate-500">{selectedFile.name}</span>
              )}
            </label>

            <div className="flex items-center justify-between">
              <button
                type="submit"
                disabled={isLoading}
                className="rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-indigo-300"
              >
                {isLoading ? "Analyzing..." : "Generate Diagram"}
              </button>
              {error && <span className="text-sm text-red-600">{error}</span>}
            </div>
          </form>
        </section>

        {diagram && (
          <section className="grid gap-6 lg:grid-cols-[2fr,1fr]">
            <div className="flex flex-col gap-4 rounded-lg bg-white p-6 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Mermaid Diagram</h2>
                <div className="flex gap-2">
                  <button
                    onClick={exportSvg}
                    className="rounded border border-slate-300 px-3 py-1 text-xs font-medium hover:bg-slate-50"
                  >
                    Export SVG
                  </button>
                  <button
                    onClick={exportPng}
                    className="rounded border border-slate-300 px-3 py-1 text-xs font-medium hover:bg-slate-50"
                  >
                    Export PNG
                  </button>
                  <button
                    onClick={exportMarkdown}
                    className="rounded border border-slate-300 px-3 py-1 text-xs font-medium hover:bg-slate-50"
                  >
                    Export Markdown
                  </button>
                </div>
              </div>
              <div
                ref={mermaidRef}
                className="overflow-auto rounded border border-slate-200 bg-slate-50 p-4"
              />
            </div>

            <aside className="flex flex-col gap-4 rounded-lg bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold">System Summary</h2>
              <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                {summary}
              </p>
            </aside>
          </section>
        )}
      </main>
    </div>
  );
}


