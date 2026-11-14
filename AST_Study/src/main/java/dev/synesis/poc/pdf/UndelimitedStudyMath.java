package dev.synesis.poc.pdf;

import java.util.function.BiFunction;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Recover explicit script notation in prose without treating ordinary identifiers as formulas. */
final class UndelimitedStudyMath {
    private static final String INDEX = "(?:\\{[A-Za-z0-9]+(?:\\s*[+−=,\\-]\\s*[A-Za-z0-9]+)*\\}|[A-Za-z]|[0-9]+)";
    private static final String SCRIPT = "[A-Za-z](?:[_^]" + INDEX + "){1,2}";
    private static final Pattern TOKEN = Pattern.compile(
        "(?<![A-Za-z0-9_\\\\:/@])(?:⟨\\s*" + SCRIPT + "\\s*⟩|〈\\s*" + SCRIPT
        + "\\s*〉|\\{" + SCRIPT + "\\}|" + SCRIPT + ")"
        + "(?![A-Za-z0-9_\\\\:/@]|\\.[A-Za-z])");

    private UndelimitedStudyMath() {}

    // Called only on prose after code and explicitly delimited math have been protected.
    static String restore(String source, BiFunction<String,String,String> render) {
        Matcher matcher = TOKEN.matcher(source);
        StringBuffer result = new StringBuffer();
        while (matcher.find()) {
            String original = matcher.group();
            if (insidePath(source, matcher.start(), matcher.end())) {
                matcher.appendReplacement(result, Matcher.quoteReplacement(original));
                continue;
            }
            String formula = original;
            if (original.startsWith("⟨") || original.startsWith("〈"))
                formula = "\\langle " + original.substring(1, original.length()-1).strip() + " \\rangle";
            else if (original.startsWith("{"))
                formula = "\\{" + original.substring(1, original.length()-1) + "\\}";
            matcher.appendReplacement(result, Matcher.quoteReplacement(render.apply(formula, original)));
        }
        matcher.appendTail(result);
        return result.toString();
    }

    private static boolean insidePath(String source, int start, int end) {
        int left = start, right = end;
        while (left > 0 && !Character.isWhitespace(source.charAt(left-1))) left--;
        while (right < source.length() && !Character.isWhitespace(source.charAt(right))) right++;
        String word = source.substring(left, right);
        return word.contains("://") || word.contains("\\\\")
            || word.matches(".*[A-Za-z]:[\\\\/].*") || word.startsWith("/") || word.startsWith("~/")
            || word.startsWith("./") || word.startsWith("../");
    }
}
