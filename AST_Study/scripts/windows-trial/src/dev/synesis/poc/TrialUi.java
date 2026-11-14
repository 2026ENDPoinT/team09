package dev.synesis.poc;

/** Shares app typography without changing the main application's entry point. */
public final class TrialUi {
    private TrialUi() {}
    public static void install(){UiFonts.install();}
}
