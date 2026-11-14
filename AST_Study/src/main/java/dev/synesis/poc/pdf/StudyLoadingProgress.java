package dev.synesis.poc.pdf;

/** Display-only phases; never feed these percentages back into engine progress. */
final class StudyLoadingProgress {
    private StudyLoadingProgress() {}
    static int display(int overall,boolean firstSummaryShown) {
        int bounded=Math.max(0,Math.min(100,overall));
        // Preparation/overview occupies the first 22 points of the engine timeline.
        // Actual visible content, not this estimate, completes the first phase.
        return firstSummaryShown?bounded:Math.min(99,(int)Math.round(bounded*100d/22));
    }
}
