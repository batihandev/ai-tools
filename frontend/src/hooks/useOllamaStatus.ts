import { useEffect, useState } from "react";

export type OllamaStatus = "online" | "offline" | "error" | "checking";

type HealthResponse = {
  ollama_status: "online" | "offline" | "error";
  ollama_url: string;
};

export function useOllamaStatus() {
  const [status, setStatus] = useState<OllamaStatus>("checking");
  const [url, setUrl] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    let timeoutId: number;

    const checkHealth = async () => {
      try {
        const resp = await fetch("/api/health");
        if (!mounted) return;

        if (resp.ok) {
          const data = (await resp.json()) as HealthResponse;
          console.log("[Ollama Health]", data);
          setStatus(data.ollama_status);
          setUrl(data.ollama_url);
        } else {
          console.error(`[Ollama Health] HTTP ${resp.status}`);
          setStatus("error");
        }
      } catch (err) {
        if (mounted) {
          console.error("[Ollama Health] Fetch failed:", err);
          setStatus("offline");
        }
      }

      if (mounted) {
        timeoutId = window.setTimeout(checkHealth, 10000); // Check every 10s
      }
    };

    checkHealth();

    return () => {
      mounted = false;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, []);

  return { status, url };
}
