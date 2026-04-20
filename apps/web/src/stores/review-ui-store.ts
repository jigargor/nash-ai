"use client";

import { create } from "zustand";

interface ReviewUiState {
  selectedFindingIndex: number | null;
  severityFilters: Record<string, boolean>;
  categoryFilters: Record<string, boolean>;
  expandedFiles: Record<string, boolean>;
  setSelectedFindingIndex: (index: number | null) => void;
  toggleSeverityFilter: (severity: string) => void;
  toggleCategoryFilter: (category: string) => void;
  toggleFileExpanded: (filePath: string) => void;
}

export const useReviewUiStore = create<ReviewUiState>((set) => ({
  selectedFindingIndex: null,
  severityFilters: {},
  categoryFilters: {},
  expandedFiles: {},
  setSelectedFindingIndex: (selectedFindingIndex) => set({ selectedFindingIndex }),
  toggleSeverityFilter: (severity) =>
    set((state) => ({
      severityFilters: {
        ...state.severityFilters,
        [severity]: !state.severityFilters[severity],
      },
    })),
  toggleCategoryFilter: (category) =>
    set((state) => ({
      categoryFilters: {
        ...state.categoryFilters,
        [category]: !state.categoryFilters[category],
      },
    })),
  toggleFileExpanded: (filePath) =>
    set((state) => ({
      expandedFiles: {
        ...state.expandedFiles,
        [filePath]: !state.expandedFiles[filePath],
      },
    })),
}));
