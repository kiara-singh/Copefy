import type { ChatTrace, PipelineLayer } from "../lib/api";

interface ChatTracePanelProps {
  trace: ChatTrace;
}

function layer_summary(layer: PipelineLayer): string {
  if (layer.name === "routing") {
    return `${layer.decision} via ${layer.router ?? "?"}`;
  }
  if (layer.name === "corpus") {
    return layer.decision;
  }
  if (layer.name === "retrieval") {
    const cats = layer.categories?.length ? layer.categories.join(", ") : "none";
    return `${layer.strategy ?? layer.decision} · ${cats} · ${layer.candidates ?? 0}→${layer.returned ?? 0} chunks`;
  }
  if (layer.name === "generation") {
    return `${layer.communication_style ?? layer.decision} · ${layer.model ?? "?"}`;
  }
  return layer.decision;
}

function layer_details(layer: PipelineLayer) {
  if (layer.name === "routing") {
    return (
      <dl className="mt-1 space-y-0.5 text-slate-600">
        <div>
          <dt className="inline font-medium">Reason: </dt>
          <dd className="inline">{layer.reason ?? trace_fallback(layer, "route_reason")}</dd>
        </div>
      </dl>
    );
  }
  if (layer.name === "corpus") {
    return (
      <p className="mt-1 text-slate-600">{layer.reason ?? "No additional detail."}</p>
    );
  }
  if (layer.name === "retrieval") {
    const sources = layer.sources ?? [];
    return (
      <div className="mt-2 space-y-2">
        {layer.search_query && (
          <p className="text-slate-600">
            <span className="font-medium">Query:</span> {layer.search_query}
          </p>
        )}
        {layer.top_similarity !== undefined && (
          <p className="text-slate-600">
            <span className="font-medium">Top similarity:</span> {layer.top_similarity}
          </p>
        )}
        {sources.length > 0 && (
          <div className="space-y-2">
            {sources.map((source, index) => (
              <div
                key={`${source.source_url ?? "doc"}-${index}`}
                className="rounded border border-slate-200 bg-white p-2"
              >
                <p className="font-medium text-slate-800">
                  {source.title ?? source.category ?? `Source ${index + 1}`}
                </p>
                <p className="text-slate-500">
                  {source.category ?? "uncategorized"}{source.similarity !== undefined && ` · similarity ${source.similarity}`}
                  {source.created_at ? ` · ${source.created_at}` : ""}
                </p>
                {(source.chunk_id || source.document_id) && (
                  <p className="mt-1 font-mono text-xs text-slate-500">
                    {source.chunk_id ?? source.document_id}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }
  if (layer.name === "generation") {
    return (
      <dl className="mt-1 space-y-0.5 text-slate-600">
        <div>
          <dt className="inline font-medium">Style: </dt>
          <dd className="inline">{layer.communication_style ?? layer.decision}</dd>
        </div>
        {layer.model && (
          <div>
            <dt className="inline font-medium">Model: </dt>
            <dd className="inline">{layer.model}</dd>
          </div>
        )}
        <div>
          <dt className="inline font-medium">History turns: </dt>
          <dd className="inline">{layer.history_turns ?? 0}</dd>
        </div>
        <div>
          <dt className="inline font-medium">KB chunks in prompt: </dt>
          <dd className="inline">{layer.kb_chunks_in_prompt ?? 0}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Name in prompt: </dt>
          <dd className="inline">{layer.preferred_name_set ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Goal in prompt: </dt>
          <dd className="inline">{layer.wellness_goal_set ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt className="inline font-medium">Coaching prefs in prompt: </dt>
          <dd className="inline">
            {layer.coaching_preferences_set ? "yes" : "no"}
          </dd>
        </div>
        {layer.structured_format_requested && (
          <div>
            <dt className="inline font-medium">Structured format: </dt>
            <dd className="inline">requested (e.g. bullets)</dd>
          </div>
        )}
      </dl>
    );
  }
  return null;
}

function trace_fallback(layer: PipelineLayer, _key: string): string {
  return layer.reason ?? "—";
}

function ChatTracePanel({ trace }: ChatTracePanelProps) {
  const pipeline = trace.pipeline;

  if (pipeline?.layers?.length) {
    return (
      <details className="mt-2 max-w-[80%] rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">
          Pipeline trace · {pipeline.total_ms}ms
          {trace.communication_style && (
            <span className="ml-2 font-normal text-slate-500">
              ({trace.communication_style})
            </span>
          )}
        </summary>
        <div className="mt-3 space-y-3">
          {pipeline.layers.map((layer) => (
            <div
              key={`${layer.layer}-${layer.name}`}
              className="rounded-lg border border-slate-200 bg-white p-2.5"
            >
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-semibold text-slate-800">
                  Layer {layer.layer}: {layer.name}
                </p>
                <span className="shrink-0 text-slate-400">{layer.ms}ms</span>
              </div>
              <p className="mt-0.5 text-slate-700">{layer_summary(layer)}</p>
              {layer_details(layer)}
            </div>
          ))}
        </div>
      </details>
    );
  }

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
        {trace.communication_style && (
          <div>
            <dt className="inline font-medium">Style: </dt>
            <dd className="inline">{trace.communication_style}</dd>
          </div>
        )}
        <div>
          <dt className="inline font-medium">KB used: </dt>
          <dd className="inline">{trace.kb_used ? "yes" : "no"}</dd>
        </div>
        {trace.model && (
          <div>
            <dt className="inline font-medium">Model: </dt>
            <dd className="inline">{trace.model}</dd>
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
              <p className="text-slate-500">
                {source.category ?? "uncategorized"}{source.similarity !== undefined && ` · similarity ${source.similarity}`}
                {source.created_at ? ` · ${source.created_at}` : ""}
              </p>
              {(source.chunk_id || source.document_id) && (
                <p className="mt-1 font-mono text-xs text-slate-500">
                  {source.chunk_id ?? source.document_id}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

export default ChatTracePanel;
