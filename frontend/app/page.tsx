"use client";
import { useState, useEffect, useCallback, useRef } from "react";
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
import { Copy as CopyIcon, Check as CheckIcon, Loader2, Database, Cpu, Lightbulb, Clock, Play } from "lucide-react";

export default function Home() {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState<{optimized_query?: string; explanation?: string; error?: string}>();
  const [loading, setLoading] = useState(false);

  type QueryStatus = "pending" | "analyzing_schema" | "running_explain" | "generating_suggestions" | "completed" | "error";

  type ExecutedQuery = {
    query: string;
    timestamp: string;
    result_preview?: string;
  };

  type SlowQuery = { 
    id: string; 
    query: string; 
    suggestions: string;
    status: QueryStatus;
    current_step?: string;
    progress_percentage: number;
    current_customer_query?: string;
    executed_queries: ExecutedQuery[];
  };

  type SlowQueriesResponse = {
    queries: SlowQuery[];
    session_id: string;
  };

  const [slowQueries, setSlowQueries] = useState<SlowQuery[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sqLoading, setSqLoading] = useState(false);
  const [sqError, setSqError] = useState<string | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const [debugInfo, setDebugInfo] = useState<{message?: string; error?: string}>();
  const [debugLoading, setDebugLoading] = useState(false);

  // Function to get status icon and color
  const getStatusDisplay = (status: QueryStatus, progress: number) => {
    switch (status) {
      case "pending":
        return { icon: <Loader2 className="w-4 h-4 animate-spin" />, color: "text-gray-400", bgColor: "bg-gray-900/50" };
      case "analyzing_schema":
        return { icon: <Database className="w-4 h-4 animate-pulse" />, color: "text-blue-400", bgColor: "bg-blue-900/20" };
      case "running_explain":
        return { icon: <Cpu className="w-4 h-4 animate-pulse" />, color: "text-yellow-400", bgColor: "bg-yellow-900/20" };
      case "generating_suggestions":
        return { icon: <Lightbulb className="w-4 h-4 animate-pulse" />, color: "text-green-400", bgColor: "bg-green-900/20" };
      case "completed":
        return { icon: <CheckIcon className="w-4 h-4" />, color: "text-green-500", bgColor: "bg-gray-900/50" };
      case "error":
        return { icon: <span className="w-4 h-4 text-red-500">⚠</span>, color: "text-red-500", bgColor: "bg-red-900/20" };
      default:
        return { icon: <Loader2 className="w-4 h-4 animate-spin" />, color: "text-gray-400", bgColor: "bg-gray-900/50" };
    }
  };

  // Function to poll for status updates
  const pollStatusUpdates = useCallback(async (sessionId: string) => {
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/slow_queries/${sessionId}/status`);
      if (r.ok) {
        const data: SlowQuery[] = await r.json();
        setSlowQueries(data);
        
        // Check if all queries are completed or errored
        const allDone = data.every(q => q.status === "completed" || q.status === "error");
        console.log(`Session ${sessionId}: ${data.length} queries, all done: ${allDone}`);
        
        if (allDone && pollIntervalRef.current) {
          console.log(`Stopping polling for session ${sessionId}`);
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          // Cleanup session after a longer delay to be safe
          setTimeout(() => {
            console.log(`Cleaning up session ${sessionId}`);
            fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/slow_queries/${sessionId}`, {
              method: 'DELETE'
            }).catch(console.error);
          }, 10000); // Increased delay to 10 seconds
        }
      } else {
        console.error(`Failed to poll status for session ${sessionId}: ${r.status} ${r.statusText}`);
        // If we get a 404, the session might have been cleaned up, stop polling
        if (r.status === 404 && pollIntervalRef.current) {
          console.log(`Session ${sessionId} not found, stopping polling`);
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
      }
    } catch (err) {
      console.error("Error polling status:", err);
    }
  }, []);

  const fetchSlowQueries = useCallback(async () => {
    setSqLoading(true);
    setSqError(null);
    
    // Clear any existing polling
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/slow_queries`);
      const data: SlowQueriesResponse = await r.json();
      setSlowQueries(data.queries ?? []);
      setSessionId(data.session_id);
      
      // Start polling for updates if there are pending queries
      const hasPending = data.queries.some(q => q.status !== "completed" && q.status !== "error");
      if (hasPending) {
        pollIntervalRef.current = setInterval(() => {
          pollStatusUpdates(data.session_id);
        }, 1000); // Poll every second
      }
    } catch (err) {
      console.error(err);
      setSqError("Failed to fetch slow queries.");
    } finally {
      setSqLoading(false);
    }
  }, [pollStatusUpdates]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
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

  // Skeleton component for loading state
  const SkeletonCard = ({ query, status, currentStep, progress }: { query: SlowQuery, status: any, currentStep?: string, progress: number }) => {
    // CopyButton for code blocks (same as in AI suggestion blocks)
    const CopyButton = ({ text }: { text: string }) => {
      const [copied, setCopied] = useState(false);
      const Icon = copied ? CheckIcon : CopyIcon;
      return (
        <button
          onClick={() => {
            navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          }}
          className="absolute top-2 right-2 p-1 bg-gray-700 hover:bg-gray-600 rounded-md transition-colors"
          aria-label="Copy code to clipboard"
        >
          <Icon className={`w-4 h-4 ${copied ? 'text-green-400' : ''}`} />
        </button>
      );
    };
    return (
      <Card className={`w-full ${status.bgColor} border-[#1f2a37]/80 shadow-lg backdrop-blur-md transition-all duration-300`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <span className={status.color}>{status.icon}</span>
            Slow Query #{query.id}
          </CardTitle>
          {currentStep && query.status !== "completed" && query.status !== "error" && (
            <div className="text-sm text-gray-400 mt-1 flex items-center gap-2">
              <div className="w-full bg-gray-700/50 rounded-full h-1">
                <div 
                  className={`h-1 rounded-full transition-all duration-500 ${
                    query.current_customer_query ? "bg-green-500 animate-pulse" : "bg-blue-500 animate-pulse"
                  }`}
                  style={{ width: "100%" }}
                />
              </div>
            </div>
          )}
          {currentStep && (
            <p className="text-sm text-gray-300">{currentStep}</p>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold mb-2 text-gray-300">Original Query</h3>
            <div className="relative">
              <CopyButton text={query.query} />
              <SyntaxHighlighter
                language="sql"
                style={atomOneDark}
                wrapLongLines
                customStyle={{
                  fontFamily: "var(--font-geist-mono)",
                  borderRadius: "0.75rem",
                  padding: "1.25rem",
                  background: "rgba(255,255,255,0.05)",
                  border: "1px solid rgba(255,255,255,0.1)",
                }}
              >
                {query.query}
              </SyntaxHighlighter>
            </div>
          </div>

          {/* Current customer query being executed */}
          {query.current_customer_query && (
            <div className="border border-blue-500/30 rounded-lg p-3 bg-blue-900/10">
              <div className="flex items-center gap-2 mb-2">
                <Play className="w-4 h-4 text-blue-400 animate-pulse" />
                <h3 className="text-sm font-semibold text-blue-400">Currently Running:</h3>
              </div>
              <SyntaxHighlighter
                language="sql"
                style={atomOneDark}
                wrapLongLines
                customStyle={{
                  fontFamily: "var(--font-geist-mono)",
                  borderRadius: "0.5rem",
                  padding: "0.75rem",
                  fontSize: "0.875rem",
                  background: "rgba(59, 130, 246, 0.05)"
                }}
              >
                {query.current_customer_query}
              </SyntaxHighlighter>
            </div>
          )}

          {/* History of executed queries */}
          {query.executed_queries.length > 0 && (
            <div className="border border-gray-600/30 rounded-lg p-3 bg-gray-900/20">
              <div className="flex items-center gap-2 mb-3">
                <Clock className="w-4 h-4 text-gray-400" />
                <h3 className="text-sm font-semibold text-gray-400">Customer DB Query History:</h3>
              </div>
              <div className="space-y-3 max-h-60 overflow-y-auto">
                {query.executed_queries.map((execQuery, idx) => (
                  <div key={idx} className="border-l-2 border-gray-600/50 pl-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-gray-500">{execQuery.timestamp}</span>
                      {execQuery.result_preview && (
                        <span className={`text-xs px-2 py-1 rounded ${
                          execQuery.result_preview === "Query failed" 
                            ? "bg-red-900/30 text-red-400" 
                            : "bg-green-900/30 text-green-400"
                        }`}>
                          {execQuery.result_preview}
                        </span>
                      )}
                    </div>
                    <SyntaxHighlighter
                      language="sql"
                      style={atomOneDarkReasonable}
                      wrapLongLines
                      customStyle={{
                        fontFamily: "var(--font-geist-mono)",
                        borderRadius: "0.375rem",
                        padding: "0.5rem",
                        fontSize: "0.75rem",
                        background: "rgba(255,255,255,0.02)",
                        margin: 0
                      }}
                    >
                      {execQuery.query}
                    </SyntaxHighlighter>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <h2 className="font-semibold mb-2">AI suggestions</h2>
            {query.status === "completed" ? (
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
                              borderRadius: "0.75rem",
                              padding: "1.25rem",
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
                  table: ({ node, ...props }) => (
                    <div className="my-6 overflow-x-auto">
                      <table
                        className="w-full border-collapse rounded-lg overflow-hidden border border-gray-700/60"
                        {...props}
                      />
                    </div>
                  ),
                  thead: ({ node, ...props }) => (
                    <thead className="bg-gray-900/70" {...props} />
                  ),
                  th: ({ node, ...props }) => (
                    <th
                      className="border border-gray-700/60 px-4 py-2 text-left font-semibold"
                      {...props}
                    />
                  ),
                  td: ({ node, ...props }) => (
                    <td className="border border-gray-700/60 px-4 py-2" {...props} />
                  ),
                }}
              >
                {query.suggestions}
              </ReactMarkdown>
            ) : query.status === "error" ? (
              <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
                <p className="text-red-400">{query.suggestions}</p>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Skeleton animation for suggestions */}
                <div className="animate-pulse">
                  <div className="h-4 bg-gray-700/50 rounded w-3/4 mb-2"></div>
                  <div className="h-4 bg-gray-700/50 rounded w-1/2 mb-2"></div>
                  <div className="h-4 bg-gray-700/50 rounded w-5/6 mb-4"></div>
                  <div className="h-20 bg-gray-700/30 rounded-lg mb-2"></div>
                  <div className="h-4 bg-gray-700/50 rounded w-2/3"></div>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    );
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
                    customStyle={{
                      fontFamily: "var(--font-geist-mono)",
                      borderRadius: "0.75rem",
                      padding: "1.25rem",
                    }}
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
              {sessionId && (
                <p className="text-sm text-gray-400">
                  Session: {sessionId.slice(0, 8)}...
                </p>
              )}
            </div>

            <div className="flex flex-col gap-6 w-full">
              {slowQueries.map((q, idx) => {
                const statusDisplay = getStatusDisplay(q.status, q.progress_percentage);
                return (
                  <SkeletonCard 
                    key={q.id ?? idx} 
                    query={q}
                    status={statusDisplay}
                    currentStep={q.current_step}
                    progress={q.progress_percentage}
                  />
                );
              })}
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
                  <p className="text-gray-400">Click &quot;Fetch Debug Info&quot; to load debug information.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </main>
  );
}
