import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { BlockExplanation, JobExplanation } from "../../api/types";
import { ErrorState, LoadingState } from "../shared/ViewStates";
import { BlockExplanationView } from "./BlockExplanationView";
import { JobExplanationView } from "./JobExplanationView";
import { SlideOver } from "./SlideOver";

export type WhySelection =
  | { kind: "block"; planId: string; blockId: string }
  | { kind: "job"; planId: string; jobId: string };

/**
 * Fetches and renders one explanation. Selecting a job from inside a block
 * view, or a block from inside a job view, re-selects within this same
 * component rather than opening a second panel -- there is one Why panel,
 * always answering the most recent question.
 */
export function WhyPanel({
  selection,
  onSelect,
  onClose,
}: {
  selection: WhySelection;
  onSelect: (next: WhySelection) => void;
  onClose: () => void;
}) {
  const [block, setBlock] = useState<BlockExplanation | null>(null);
  const [job, setJob] = useState<JobExplanation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    setBlock(null);
    setJob(null);

    const load = async () => {
      try {
        if (selection.kind === "block") {
          const result = await api.explainBlock(selection.planId, selection.blockId);
          if (!cancelled) setBlock(result);
        } else {
          const result = await api.explainJob(selection.planId, selection.jobId);
          if (!cancelled) setJob(result);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load the explanation.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [selection]);

  const title =
    selection.kind === "block" ? `Block ${selection.blockId}` : `Job ${selection.jobId}`;

  return (
    <SlideOver title={title} subtitle="Why" onClose={onClose}>
      {isLoading && <LoadingState label="Loading explanation…" />}
      {error && <ErrorState title="Could not explain this" detail={error} />}
      {!isLoading && !error && block && (
        <BlockExplanationView
          explanation={block}
          onSelectJob={(jobId) => onSelect({ kind: "job", planId: selection.planId, jobId })}
        />
      )}
      {!isLoading && !error && job && (
        <JobExplanationView
          explanation={job}
          onSelectBlock={(blockId) =>
            onSelect({ kind: "block", planId: selection.planId, blockId })
          }
        />
      )}
    </SlideOver>
  );
}
