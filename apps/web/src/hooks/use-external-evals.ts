"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  actionCancelExternalEval,
  actionCreateExternalEval,
  actionEstimateExternalEval,
  actionFetchExternalEvalDetail,
  actionFetchExternalEvals,
} from "@/app/actions/dashboard-api";
import {
  type ExternalEvalCreateRequest,
  type ExternalEvalEstimateRequest,
} from "@/lib/api/external-evals";

export function useExternalEvalEstimate() {
  return useMutation({
    mutationFn: (payload: ExternalEvalEstimateRequest) => actionEstimateExternalEval(payload),
  });
}

export function useCreateExternalEval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExternalEvalCreateRequest) => actionCreateExternalEval(payload),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["external-evals", variables.installation_id] });
    },
  });
}

export function useExternalEvals(installationId?: number) {
  return useQuery({
    queryKey: ["external-evals", installationId ?? null],
    queryFn: () => actionFetchExternalEvals(installationId as number),
    enabled: typeof installationId === "number" && installationId > 0,
    refetchInterval: 4000,
  });
}

export function useExternalEvalDetail(externalEvalId?: number, installationId?: number) {
  return useQuery({
    queryKey: ["external-eval", externalEvalId ?? null, installationId ?? null],
    queryFn: () => actionFetchExternalEvalDetail(externalEvalId as number, installationId as number),
    enabled:
      typeof externalEvalId === "number" &&
      externalEvalId > 0 &&
      typeof installationId === "number" &&
      installationId > 0,
    refetchInterval: 3500,
  });
}

export function useCancelExternalEval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ externalEvalId, installationId }: { externalEvalId: number; installationId: number }) =>
      actionCancelExternalEval(externalEvalId, installationId),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["external-evals", variables.installationId] });
      void queryClient.invalidateQueries({
        queryKey: ["external-eval", variables.externalEvalId, variables.installationId],
      });
    },
  });
}

