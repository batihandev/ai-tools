import { useEffect, useState, useRef } from "react";

export type BackendStatus =
  | "online"
  | "backend-offline"
  | "ollama-offline"
  | "error"
  | "checking";

type HealthResponse = {
  ollama_status: "online" | "offline" | "error";
  ollama_url: string;
};

export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus>("checking");
  const [details, setDetails] = useState<string>("");

  const timeoutRef = useRef<number | null>(null);
  const backoffRef = useRef<number>(1000); // start with 1s

  useEffect(() => {
    let mounted = true;

    const checkHealth = async () => {
      try {
        const start = Date.now();
        const resp = await fetch("/api/health");

        if (!mounted) return;

        if (resp.ok) {
          const data = (await resp.json()) as HealthResponse;

          if (data.ollama_status === "online") {
            setStatus("online");
            setDetails(`Connected (${data.ollama_url})`);
          } else {
            setStatus("ollama-offline");
            setDetails(`Backend OK, Ollama ${data.ollama_status}`);
          }

          // Reset backoff on success
          backoffRef.current = 10000; // Check every 10s when healthy
        } else {
          setStatus("error"); // 500 error from backend
          setDetails(`HTTP ${resp.status}`);
          // Increase backoff on error
          backoffRef.current = Math.min(backoffRef.current * 1.5, 30000);
        }
      } catch (err) {
        if (mounted) {
          // Network error (backend down)
          setStatus("backend-offline");
          setDetails("Backend unreachable");
          // Increase backoff
          backoffRef.current = Math.min(backoffRef.current * 1.5, 30000);
        }
      }

      if (mounted) {
        // Add jitter to avoid synchronized stampedes if multiple tabs open
        const jitter = Math.random() * 1000;
        timeoutRef.current = window.setTimeout(
          checkHealth,
          backoffRef.current + jitter,
        );
      }
    };

    checkHealth();

    return () => {
      mounted = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  return { status, details };
}
