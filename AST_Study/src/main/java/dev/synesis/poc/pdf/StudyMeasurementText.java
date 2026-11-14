package dev.synesis.poc.pdf;

import java.util.regex.Pattern;

/** Keep simple volume counts in prose typography, without interpreting division. */
final class StudyMeasurementText {
    private static final String NUMBER = "[+-]?[0-9]+(?:,[0-9]{3})*(?:\\.[0-9]+)?(?:천|만)?";
    private static final Pattern COUNT = Pattern.compile(
        "(?:" + NUMBER + "(?:\\s*[~–−-]\\s*" + NUMBER + ")?\\s*)?/(?:μ|m|d)?L");

    private StudyMeasurementText() {}

    static String inline(String formula) {
        String text = formula.strip();
        // Only unwrap upright unit notation; arbitrary TeX remains a formula.
        for (int i = 0; i < 3; i++)
            text = text.replaceAll("\\\\(?:mathrm|text)\\{([^{}]*)\\}", "$1");
        text = text.replaceAll("\\\\mu(?![A-KM-Za-z])", "μ")
            .replace('µ', 'μ').replaceAll("\\\\[,;:!]", " ")
            .replaceAll("μ\\s+L", "μL").replaceAll("\\s*/\\s*", "/").strip();
        if (!COUNT.matcher(text).matches()) return null;
        return "<span class='study-measurement'>" + text + "</span>";
    }
}
