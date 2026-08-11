import type { ChatTrace } from "../lib/api";

interface ChatTracePanelProps {
  trace: ChatTrace;
}

function ChatTracePanel({ trace }: ChatTracePanelProps) {
  return (
    <details className="mt-2 max-w-[80%] rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <summary className="cursor-pointer font-medium text-slate-700">
        Agent trace
      </summary>
      <dl className="mt-2 space-y-1">
        <div>
          <dt className="inline font-medium">Path: </dt>
          <dd className="inline">{trace.path}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Router: </dt>
          <dd className="inline">{trace.router}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Reason: </dt>
          <dd className="inline">{trace.route_reason}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Tools: </dt>
          <dd className="inline">
            {trace.tools_used.length > 0 ? trace.tools_used.join(", ") : "none"}
          </dd>
        </div>
        <div>
          <dt className="inline font-medium">KB used: </dt>
          <dd className="inline">{trace.kb_used ? "yes" : "no"}</dd>
        </div>
        {trace.search_query && (
          <div>
            <dt className="inline font-medium">Search query: </dt>
            <dd className="inline break-words">{trace.search_query}</dd>
          </div>
        )}
        {trace.categories.length > 0 && (
          <div>
            <dt className="inline font-medium">Categories: </dt>
            <dd className="inline">{trace.categories.join(", ")}</dd>
          </div>
        )}
        {trace.model && (
          <div>
            <dt className="inline font-medium">Model: </dt>
            <dd className="inline">{trace.model}</dd>
          </div>
        )}
        {trace.tool_status && (
          <div>
            <dt className="inline font-medium">Tool status: </dt>
            <dd className="inline">{trace.tool_status}</dd>
          </div>
        )}
      </dl>
      {trace.sources.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="font-medium text-slate-700">
            Documents ({trace.sources.length})
          </p>
          {trace.sources.map((source, index) => (
            <div
              key={`${source.source_url ?? "doc"}-${index}`}
              className="rounded border border-slate-200 bg-white p-2"
            >
              <p className="font-medium text-slate-800">
                {source.title ?? source.category ?? `Source ${index + 1}`}
              </p>
              {source.source_url && (
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-indigo-600 hover:underline"
                >
                  {source.source_url}
                </a>
              )}
              <p className="mt-1 text-slate-500">
                {source.category ?? "uncategorized"} · similarity{" "}
                {source.similarity}
              </p>
              <p className="mt-1 whitespace-pre-wrap text-slate-600">
                {source.excerpt}
              </p>
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

export default ChatTracePanel;
