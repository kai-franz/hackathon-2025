"use client";
import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { atomDark } from "react-syntax-highlighter/dist/esm/styles/prism";

export default function Home() {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<{optimized_query?: string; explanation?: string; error?: string}>();
  const [loading, setLoading] = useState(false);

  const optimize = async () => {
    if (!sql.trim()) return;
    setLoading(true);
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/optimize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql })
      });
      const data = await r.json();
      setResult(data);
    } catch (e) {
      setResult({ error: "Request failed, check console." });
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex flex-col items-center justify-center min-h-screen p-8 space-y-6">
      <h1 className="text-3xl font-bold">SQL Optimizer</h1>

      <textarea
        className="w-full max-w-2xl h-48 p-3 border rounded bg-gray-800 text-gray-100 border-gray-600 placeholder-gray-400 font-mono"
        placeholder="Paste your SQL query here..."
        value={sql}
        onChange={e => setSql(e.target.value)}
      />

      <button
        onClick={optimize}
        disabled={loading}
        className="px-4 py-2 rounded text-white bg-blue-600 disabled:opacity-50"
      >
        {loading ? "Optimizing…" : "Optimize"}
      </button>

      {result?.error && <p className="text-red-600">{result.error}</p>}

      {result?.optimized_query && (
        <section className="w-full max-w-2xl space-y-4">
          <div>
            <h2 className="font-semibold">Optimized query</h2>
            <SyntaxHighlighter
              language="sql"
              style={atomDark}
              wrapLongLines
              customStyle={{ fontFamily: "var(--font-geist-mono)" }}
            >
              {result.optimized_query ?? ""}
            </SyntaxHighlighter>
          </div>
          {result.explanation && (
            <div>
              <h2 className="font-semibold">Explanation</h2>
              <p className="bg-gray-800 p-4 rounded text-gray-200 whitespace-pre-wrap font-mono">{result.explanation}</p>
            </div>
          )}
        </section>
      )}
    </main>
  );
}