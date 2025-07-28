"use client";
import { useState, useEffect, useCallback } from "react";
import { Light as SyntaxHighlighter } from "react-syntax-highlighter";
import ReactMarkdown from "react-markdown";
import { atomOneDark, atomOneDarkReasonable } from "react-syntax-highlighter/dist/esm/styles/hljs";
import sql from "react-syntax-highlighter/dist/esm/languages/hljs/sql";
import javascript from "react-syntax-highlighter/dist/esm/languages/hljs/javascript";

// Register languages for highlight.js instance
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("javascript", javascript);
import remarkGfm from "remark-gfm";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Copy as CopyIcon, Check as CheckIcon } from "lucide-react";

export default function Home() {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<{optimized_query?: string; explanation?: string; error?: string}>();
  const [loading, setLoading] = useState(false);

  type SlowQuery = { id: string; query: string; suggestions: string };

  const [slowQueries, setSlowQueries] = useState<SlowQuery[]>([]);
  const [sqLoading, setSqLoading] = useState(false);
  const [sqError, setSqError] = useState<string | null>(null);

  const [debugInfo, setDebugInfo] = useState<{message?: string; error?: string}>();
  const [debugLoading, setDebugLoading] = useState(false);

  const fetchSlowQueries = useCallback(async () => {
    setSqLoading(true);
    setSqError(null);
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/slow_queries`);
      const data = await r.json();
      setSlowQueries(data ?? []);
    } catch (err) {
      console.error(err);
      setSqError("Failed to fetch slow queries.");
    } finally {
      setSqLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSlowQueries();
  }, [fetchSlowQueries]);

  const fetchDebugInfo = async () => {
    if (debugLoading) return;
    setDebugLoading(true);
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/debug`);
      const data = await r.json();
      setDebugInfo(data);
    } catch (err) {
      console.error(err);
      setDebugInfo({ error: "Failed to fetch debug info." });
    } finally {
      setDebugLoading(false);
    }
  };

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
    } catch (err) {
      setResult({ error: "Request failed, check console." });
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex flex-col items-center justify-start min-h-screen p-8 w-full bg-gradient-to-br from-[#0d1117] via-[#0a1120] to-black text-slate-100">
      <Tabs defaultValue="optimize" className="w-full max-w-5xl">
        <TabsList className="mb-8 flex justify-center">
          <TabsTrigger value="optimize">Optimizer</TabsTrigger>
          <TabsTrigger value="slow-queries">Slow Queries</TabsTrigger>
          <TabsTrigger value="debug">Debug</TabsTrigger>
        </TabsList>

        <TabsContent value="optimize">
          {/* --- existing optimizer UI start --- */}
          <div className="flex flex-col items-center space-y-6">
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
                    style={atomOneDark}
                    wrapLongLines
                    customStyle={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    {result.optimized_query ?? ""}
                  </SyntaxHighlighter>
                </div>
                {result.explanation && (
                  <div>
                    <h2 className="font-semibold">Explanation</h2>
                    <p className="bg-gray-800 p-4 rounded text-gray-200 whitespace-pre-wrap font-mono">
                      {result.explanation}
                    </p>
                  </div>
                )}
              </section>
            )}
          </div>
          {/* --- existing optimizer UI end --- */}
        </TabsContent>

        <TabsContent value="slow-queries">
          <div className="space-y-6">
            <div className="flex items-center gap-4">
            <button
              onClick={fetchSlowQueries}
              disabled={sqLoading}
              className="px-4 py-2 rounded-md bg-gradient-to-r from-cyan-500 to-indigo-500 font-medium hover:brightness-110 transition disabled:opacity-50"
            >
              {sqLoading ? "Refreshing…" : "Refresh"}
            </button>
              {sqError && <p className="text-red-600">{sqError}</p>}
            </div>

            <div className="flex flex-col gap-6 w-full">
              {slowQueries.map((q, idx) => (
                <Card key={q.id ?? idx} className="w-full bg-[#131a24]/80 border-[#1f2a37]/80 shadow-lg shadow-cyan-500/10 backdrop-blur-md">
                  <CardHeader>
                    <CardTitle>Slow Query #{idx + 1}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div>
                      <SyntaxHighlighter
                        language="sql"
                        style={atomOneDark}
                        wrapLongLines
                        customStyle={{ fontFamily: "var(--font-geist-mono)" }}
                      >
                        {q.query}
                      </SyntaxHighlighter>
                    </div>
                    <div>
                      <h2 className="font-semibold mb-2">AI suggestions</h2>
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        className="prose md:prose-lg prose-invert max-w-none"
                        components={{
                          // Add breathing-room around headings
                          h1: ({ node, ...props }) => (
                            <h1 className="mt-8 mb-4 text-2xl font-bold" {...props} />
                          ),
                          h2: ({ node, ...props }) => (
                            <h2 className="mt-7 mb-3 text-xl font-semibold" {...props} />
                          ),
                          h3: ({ node, ...props }) => (
                            <h3 className="mt-6 mb-3 text-lg font-semibold" {...props} />
                          ),
                          h4: ({ node, ...props }) => (
                            <h4 className="mt-8 mb-4 text-2xl font-bold" {...props} />
                          ),
                          p: ({ node, ...props }) => (
                            <p className="mb-4 leading-relaxed" {...props} />
                          ),
                          ul: ({ node, ...props }) => (
                            <ul
                              className="list-disc ml-6 marker:text-slate-300 space-y-2"
                              {...props}
                            />
                          ),
                          ol: ({ node, ...props }) => (
                            <ol
                              className="list-decimal ml-6 marker:text-slate-300 space-y-2"
                              {...props}
                            />
                          ),
                          code({ node, className, children, ...props }) {
                            const match = /language-(\w+)/.exec(className || "");
                            const isInline =
                              !node || node.position?.start.line === node.position?.end.line;

                            const codeText = String(children).replace(/\n$/, "");

                            if (!isInline && match) {
                              // Component for the copy button with icon toggle
                              const CopyButton = () => {
                                const [copied, setCopied] = useState(false);
                                const Icon = copied ? CheckIcon : CopyIcon;
                                return (
                                  <button
                                    onClick={() => {
                                      navigator.clipboard.writeText(codeText);
                                      setCopied(true);
                                      setTimeout(() => setCopied(false), 2000);
                                    }}
                                    className="absolute top-2 right-2 p-1 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors"
                                    aria-label="Copy code to clipboard"
                                  >
                                    <Icon className={`w-4 h-4 ${copied ? "text-green-400" : ""}`} />
                                  </button>
                                );
                              };

                              return (
                                <div className="relative my-6">
                                  <CopyButton />
                                  <SyntaxHighlighter
                                    language={match[1]}
                                    style={atomOneDark}
                                    wrapLongLines
                                    customStyle={{
                                      fontFamily: "var(--font-geist-mono)",
                                      borderRadius: "0.5rem",
                                      padding: "1rem",
                                      background: "rgba(255,255,255,0.05)",
                                    }}
                                  >
                                    {codeText}
                                  </SyntaxHighlighter>
                                </div>
                              );
                            }

                            // Inline code or no language: small styling
                            return (
                              <code
                                className={`px-1 py-0.5 rounded bg-gray-700 text-pink-300 ${className || ""}`}
                                {...props}
                              >
                                {children}
                              </code>
                            );
                          },
                        }}
                      >
                        {q.suggestions}
                      </ReactMarkdown>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            {!sqLoading && slowQueries.length === 0 && (
              <p className="text-gray-400 text-center">No slow queries found 🎉</p>
            )}
          </div>
        </TabsContent>

        <TabsContent value="debug">
          <div className="space-y-6">
            <div className="flex items-center gap-4">
              <button
                onClick={fetchDebugInfo}
                disabled={debugLoading}
                className="px-4 py-2 rounded-md bg-gradient-to-r from-purple-500 to-pink-500 font-medium hover:brightness-110 transition disabled:opacity-50"
              >
                {debugLoading ? "Loading…" : "Fetch Debug Info"}
              </button>
            </div>

            <Card className="w-full max-w-2xl bg-[#131a24]/80 border-[#1f2a37]/80 shadow-lg shadow-purple-500/10 backdrop-blur-md">
              <CardHeader>
                <CardTitle>Debug Information</CardTitle>
              </CardHeader>
              <CardContent>
                {debugInfo?.error ? (
                  <p className="text-red-400">{debugInfo.error}</p>
                ) : debugInfo?.message ? (
                  <p className="text-gray-200">{debugInfo.message}</p>
                ) : (
                  <p className="text-gray-400">Click "Fetch Debug Info" to load debug information.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </main>
  );
}
